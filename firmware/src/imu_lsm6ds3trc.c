/*
 * LSM6DS3TR-C driver: continuous FIFO (gyro + accel, no decimation) at 416 Hz,
 * watermark interrupt on INT1 (level), burst reads of FIFO_DATA_OUT.
 * Register values from ST datasheet DocID030071 Rev 3. Burst-reading
 * FIFO_DATA_OUT_L with IF_INC=1 follows ST's reference driver
 * (lsm6ds3tr_c_fifo_raw_data_get). NOT YET VERIFIED ON HARDWARE.
 */
#include <zephyr/kernel.h>
#include <zephyr/device.h>
#include <zephyr/devicetree.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/drivers/i2c.h>
#include <zephyr/logging/log.h>
#include <zephyr/sys/byteorder.h>

#include "imu_lsm6ds3trc.h"

LOG_MODULE_REGISTER(imu, CONFIG_BTRK_LOG_LEVEL);

#define IMU_NODE DT_CHOSEN(boxtrk_imu)
BUILD_ASSERT(DT_NODE_HAS_COMPAT(IMU_NODE, boxtrk_lsm6ds3trc_fifo),
	     "chosen boxtrk,imu must be a boxtrk,lsm6ds3trc-fifo node");

/* Registers */
#define REG_FIFO_CTRL1   0x06
#define REG_FIFO_CTRL2   0x07
#define REG_FIFO_CTRL3   0x08
#define REG_FIFO_CTRL4   0x09
#define REG_FIFO_CTRL5   0x0A
#define REG_INT1_CTRL    0x0D
#define REG_WHO_AM_I     0x0F
#define REG_CTRL1_XL     0x10
#define REG_CTRL2_G      0x11
#define REG_CTRL3_C      0x12
#define REG_CTRL6_C      0x15
#define REG_CTRL7_G      0x16
#define REG_WAKE_UP_SRC  0x1B
#define REG_FIFO_STATUS1 0x3A
#define REG_FIFO_DATA_L  0x3E
#define REG_TAP_CFG      0x58
#define REG_WAKE_UP_THS  0x5B
#define REG_WAKE_UP_DUR  0x5C
#define REG_MD1_CFG      0x5E

#define WHO_AM_I_VAL     0x6A
#define CTRL3_SW_RESET   0x01
#define CTRL3_BDU_IFINC  0x44
#define CTRL1_XL_416_16G 0x64 /* ODR 0110 = 416 Hz, FS 01 = +-16 g */
#define CTRL2_G_416_2000 0x6C /* ODR 0110 = 416 Hz, FS 11 = 2000 dps */
#define CTRL1_XL_12_2G   0x10 /* 12.5 Hz, +-2 g */
#define CTRL6_XL_LP      0x10 /* XL_HM_MODE = 1: low-power/normal */
#define FIFO_CTRL3_NODEC 0x09 /* gyro + accel in FIFO, no decimation */
#define FIFO_CTRL5_CONT  ((0x6 << 3) | 0x6) /* FIFO ODR 416 Hz, continuous */
#define INT1_FTH         0x08
#define TAP_CFG_WU_LATCH 0x81 /* INTERRUPTS_ENABLE | LIR (slope filter) */
#define MD1_INT1_WU      0x20

#define WORDS_PER_SAMPLE 6    /* gyro xyz, accel xyz */
#define BURST_SAMPLES    16   /* 192 bytes per I2C transaction */

static const struct i2c_dt_spec i2c = I2C_DT_SPEC_GET(IMU_NODE);
static const struct gpio_dt_spec irq = GPIO_DT_SPEC_GET(IMU_NODE, irq_gpios);
static struct gpio_callback irq_cb;
static imu_batch_cb_t batch_cb;
static K_SEM_DEFINE(irq_sem, 0, 1);
static atomic_t streaming;

/* timestamp model */
static int64_t next_ts_us;
static float period_us = 1e6f / IMU_ODR_HZ;
static bool ts_valid;

static int wr(uint8_t reg, uint8_t val)
{
	return i2c_reg_write_byte_dt(&i2c, reg, val);
}

static int rd(uint8_t reg, uint8_t *val)
{
	return i2c_reg_read_byte_dt(&i2c, reg, val);
}

static void irq_handler(const struct device *dev, struct gpio_callback *cb, uint32_t pins)
{
	ARG_UNUSED(dev); ARG_UNUSED(cb); ARG_UNUSED(pins);
	/* Level interrupt (uses GPIO SENSE/PORT event, cheaper than a GPIOTE
	 * IN channel); mask until the FIFO has been drained. */
	gpio_pin_interrupt_configure_dt(&irq, GPIO_INT_DISABLE);
	k_sem_give(&irq_sem);
}

static uint8_t assign_timestamps(struct imu_sample *s, size_t n, int64_t t_read_us)
{
	uint8_t flags = 0;
	/* newest sample was produced within one period before the read */
	int64_t measured_last = t_read_us - (int64_t)(period_us / 2);
	int64_t predicted_last = next_ts_us + (int64_t)(period_us * (n - 1));
	int64_t err = measured_last - predicted_last;

	if (!ts_valid || err > 20000 || err < -20000) {
		next_ts_us = measured_last - (int64_t)(period_us * (n - 1));
		ts_valid = true;
		flags |= IMU_FLAG_TS_RESYNC;
	} else {
		/* slow PLL: absorb the sensor's ODR tolerance vs the 32 kHz RTC */
		period_us += 0.0005f * (float)err / (float)n;
		next_ts_us += err / 8;
	}
	for (size_t i = 0; i < n; i++) {
		s[i].t_us = (uint32_t)(next_ts_us + (int64_t)(period_us * i));
	}
	next_ts_us += (int64_t)(period_us * n);
	return flags;
}

static int drain_fifo(void)
{
	uint8_t st[4];
	uint8_t raw[BURST_SAMPLES * WORDS_PER_SAMPLE * 2];
	struct imu_sample out[BURST_SAMPLES];
	int ret = i2c_burst_read_dt(&i2c, REG_FIFO_STATUS1, st, sizeof(st));

	if (ret) {
		return ret;
	}
	int64_t t_read = k_ticks_to_us_floor64(k_uptime_ticks());
	uint16_t words = ((st[1] & 0x07) << 8) | st[0];
	uint16_t pattern = ((st[3] & 0x03) << 8) | st[2];
	uint8_t flags = (st[1] & 0x40) ? IMU_FLAG_FIFO_OVERRUN : 0;

	/* Re-align to the start of a gyro+accel set (pattern 0). */
	if (pattern != 0 && words > 0) {
		uint16_t skip = WORDS_PER_SAMPLE - (pattern % WORDS_PER_SAMPLE);
		if (skip > words) {
			skip = words;
		}
		ret = i2c_burst_read_dt(&i2c, REG_FIFO_DATA_L, raw, skip * 2);
		if (ret) {
			return ret;
		}
		words -= skip;
		ts_valid = false;
	}

	size_t total = words / WORDS_PER_SAMPLE;
	size_t done = 0;

	while (done < total) {
		size_t n = MIN(total - done, BURST_SAMPLES);
		ret = i2c_burst_read_dt(&i2c, REG_FIFO_DATA_L, raw, n * WORDS_PER_SAMPLE * 2);
		if (ret) {
			return ret;
		}
		for (size_t i = 0; i < n; i++) {
			const uint8_t *p = &raw[i * WORDS_PER_SAMPLE * 2];
			out[i].g[0] = (int16_t)sys_get_le16(p + 0);
			out[i].g[1] = (int16_t)sys_get_le16(p + 2);
			out[i].g[2] = (int16_t)sys_get_le16(p + 4);
			out[i].a[0] = (int16_t)sys_get_le16(p + 6);
			out[i].a[1] = (int16_t)sys_get_le16(p + 8);
			out[i].a[2] = (int16_t)sys_get_le16(p + 10);
		}
		/* samples still in FIFO after this chunk are newer: shift read time back */
		int64_t t_chunk = t_read - (int64_t)(period_us * (total - done - n));
		uint8_t f = assign_timestamps(out, n, t_chunk);
		if (f & IMU_FLAG_TS_RESYNC) {
			flags |= IMU_FLAG_TS_RESYNC;
		}
		if (batch_cb) {
			batch_cb(out, n, flags);
		}
		flags = 0;
		done += n;
	}
	return 0;
}

static void imu_thread(void *a, void *b, void *c)
{
	ARG_UNUSED(a); ARG_UNUSED(b); ARG_UNUSED(c);
	for (;;) {
		k_sem_take(&irq_sem, K_FOREVER);
		if (!atomic_get(&streaming)) {
			continue;
		}
		if (drain_fifo()) {
			LOG_WRN("FIFO read failed");
		}
		gpio_pin_interrupt_configure_dt(&irq, GPIO_INT_LEVEL_ACTIVE);
	}
}
K_THREAD_DEFINE(imu_tid, 2048, imu_thread, NULL, NULL, NULL, 3, 0, 0);

int imu_init(imu_batch_cb_t cb)
{
	uint8_t who = 0;
	int ret;

	batch_cb = cb;
	if (!i2c_is_ready_dt(&i2c) || !gpio_is_ready_dt(&irq)) {
		return -ENODEV;
	}
	ret = rd(REG_WHO_AM_I, &who);
	if (ret || who != WHO_AM_I_VAL) {
		LOG_ERR("WHO_AM_I 0x%02x (ret %d)", who, ret);
		return -EIO;
	}
	ret = wr(REG_CTRL3_C, CTRL3_SW_RESET);
	k_msleep(20);
	ret |= wr(REG_CTRL3_C, CTRL3_BDU_IFINC);
	ret |= gpio_pin_configure_dt(&irq, GPIO_INPUT);
	gpio_init_callback(&irq_cb, irq_handler, BIT(irq.pin));
	ret |= gpio_add_callback(irq.port, &irq_cb);
	return ret ? -EIO : 0;
}

int imu_start(void)
{
	uint16_t fth = CONFIG_BTRK_FIFO_WTM_SAMPLES * WORDS_PER_SAMPLE;
	int ret = 0;

	ret |= wr(REG_MD1_CFG, 0x00);
	ret |= wr(REG_TAP_CFG, 0x00);
	ret |= wr(REG_CTRL6_C, 0x00);          /* accel high-performance */
	ret |= wr(REG_CTRL7_G, 0x00);          /* gyro high-performance */
	ret |= wr(REG_CTRL1_XL, CTRL1_XL_416_16G);
	ret |= wr(REG_CTRL2_G, CTRL2_G_416_2000);
	ret |= wr(REG_FIFO_CTRL5, 0x00);       /* bypass = reset FIFO */
	ret |= wr(REG_FIFO_CTRL1, fth & 0xff);
	ret |= wr(REG_FIFO_CTRL2, (fth >> 8) & 0x07);
	ret |= wr(REG_FIFO_CTRL3, FIFO_CTRL3_NODEC);
	ret |= wr(REG_FIFO_CTRL4, 0x00);
	ret |= wr(REG_FIFO_CTRL5, FIFO_CTRL5_CONT);
	ret |= wr(REG_INT1_CTRL, INT1_FTH);
	ts_valid = false;
	atomic_set(&streaming, 1);
	ret |= gpio_pin_interrupt_configure_dt(&irq, GPIO_INT_LEVEL_ACTIVE);
	LOG_INF("IMU streaming 416 Hz, wtm %u samples", CONFIG_BTRK_FIFO_WTM_SAMPLES);
	return ret ? -EIO : 0;
}

int imu_stop(void)
{
	int ret = 0;

	atomic_set(&streaming, 0);
	gpio_pin_interrupt_configure_dt(&irq, GPIO_INT_DISABLE);
	ret |= wr(REG_INT1_CTRL, 0x00);
	ret |= wr(REG_FIFO_CTRL5, 0x00);
	ret |= wr(REG_CTRL1_XL, 0x00);
	ret |= wr(REG_CTRL2_G, 0x00);
	return ret ? -EIO : 0;
}

int imu_arm_wake_on_motion(uint16_t threshold_mg)
{
	/* WK_THS LSB = FS_XL / 64 = 31.25 mg at +-2 g */
	uint8_t ths = CLAMP((threshold_mg + 15) / 31, 1, 63);
	uint8_t dummy;
	int ret = imu_stop();

	ret |= wr(REG_CTRL6_C, CTRL6_XL_LP);
	ret |= wr(REG_CTRL1_XL, CTRL1_XL_12_2G); /* ~9 uA, datasheet LA_IddLM @12.5 Hz */
	ret |= wr(REG_WAKE_UP_DUR, 0x00);
	ret |= wr(REG_WAKE_UP_THS, ths);
	ret |= wr(REG_TAP_CFG, TAP_CFG_WU_LATCH);
	k_msleep(200);                         /* let the slope filter settle */
	ret |= rd(REG_WAKE_UP_SRC, &dummy);    /* clear any latched event */
	ret |= wr(REG_MD1_CFG, MD1_INT1_WU);
	return ret ? -EIO : 0;
}

int imu_configure_wake_pin(void)
{
	/* On nRF52 a level interrupt sets PIN_CNF.SENSE, which wakes System OFF. */
	int ret = gpio_pin_configure_dt(&irq, GPIO_INPUT);

	return ret ? ret : gpio_pin_interrupt_configure_dt(&irq, GPIO_INT_LEVEL_ACTIVE);
}
