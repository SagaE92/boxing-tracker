/*
 * Battery level from the Seeed XIAO nRF52840 VBAT divider:
 *   VBAT -> 1 M -> P0.31 (AIN7) -> 510 k -> P0.14
 * P0.14 is driven LOW permanently (zephyr,user vbat-en-gpios). Seeed's caveat:
 * never drive P0.14 HIGH (or leave the divider low side floating) while a cell
 * is connected - P0.31 would then see the full battery voltage, above the
 * nRF52840's 3.6 V pin limit. Leaving it low costs ~2.8 uA (4.2 V / 1.51 M).
 *
 * SAADC: gain 1/4, internal 0.6 V reference (2.4 V full scale), 12 bit, 40 us
 * acquisition (high source impedance), 4x oversampling. Sampled every
 * CONFIG_BTRK_BATTERY_PERIOD_S and shortly after each connection; the result is
 * published through the Battery Service (0x180F). The voltage-to-% curve is a
 * generic 1-cell LiPo table (btrk_util.c) - expect +-10 % accuracy, and readings
 * rise while charging over USB.
 *
 * UNTESTED ON HARDWARE: verify against a multimeter (docs/bringup.md).
 */
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <zephyr/drivers/adc.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/bluetooth/services/bas.h>

#include "battery.h"
#include "btrk_util.h"

LOG_MODULE_REGISTER(battery, CONFIG_BTRK_LOG_LEVEL);

#define USER_NODE DT_PATH(zephyr_user)

#if DT_NODE_HAS_PROP(USER_NODE, io_channels) && DT_NODE_HAS_PROP(USER_NODE, vbat_en_gpios)
#define HAVE_VBAT 1
static const struct adc_dt_spec vbat = ADC_DT_SPEC_GET(USER_NODE);
static const struct gpio_dt_spec vbat_en = GPIO_DT_SPEC_GET(USER_NODE, vbat_en_gpios);
#else
#define HAVE_VBAT 0
#endif

static uint8_t level = 100;
static uint16_t last_mv;
static bool ok;

static void sample_fn(struct k_work *w);
static K_WORK_DELAYABLE_DEFINE(sample_work, sample_fn);

static int measure(void)
{
#if HAVE_VBAT
	int16_t raw = 0;
	struct adc_sequence seq = {.buffer = &raw, .buffer_size = sizeof(raw)};
	int err = adc_sequence_init_dt(&vbat, &seq);

	if (!err) {
		err = adc_read_dt(&vbat, &seq);
	}
	if (err) {
		LOG_WRN("adc read %d", err);
		return err;
	}
	int32_t mv = raw;
	err = adc_raw_to_millivolts_dt(&vbat, &mv);
	if (err) {
		return err;
	}
	last_mv = btrk_batt_mv_from_pin_mv(mv);
	level = btrk_batt_pct_from_mv(last_mv);
	LOG_INF("battery %u mV -> %u %%", last_mv, level);
	return 0;
#else
	return -ENOTSUP;
#endif
}

static void sample_fn(struct k_work *w)
{
	if (measure() == 0) {
		(void)bt_bas_set_battery_level(level);
	}
	k_work_reschedule(&sample_work, K_SECONDS(CONFIG_BTRK_BATTERY_PERIOD_S));
}

int battery_init(void)
{
#if HAVE_VBAT
	if (gpio_is_ready_dt(&vbat_en) && adc_is_ready_dt(&vbat)) {
		/* GPIO_ACTIVE_LOW: "active" drives P0.14 low, enabling the divider */
		int err = gpio_pin_configure_dt(&vbat_en, GPIO_OUTPUT_ACTIVE);
		if (!err) {
			err = adc_channel_setup_dt(&vbat);
		}
		ok = err == 0;
		if (err) {
			LOG_ERR("battery ADC setup %d", err);
		}
	}
#endif
	if (!ok) {
		LOG_WRN("no battery ADC: reporting a fixed 100 %%");
		return bt_bas_set_battery_level(level);
	}
	k_work_reschedule(&sample_work, K_MSEC(200));
	return 0;
}

void battery_sample_soon(void)
{
	if (ok) {
		k_work_reschedule(&sample_work, K_SECONDS(2));
	}
}

uint8_t battery_level_pct(void) { return level; }
uint16_t battery_mv(void) { return last_mv; }
