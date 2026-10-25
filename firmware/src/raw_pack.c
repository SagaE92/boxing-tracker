#include "raw_pack.h"
#include <string.h>

static inline void put_u16(uint8_t *p, uint16_t v) { p[0] = v & 0xff; p[1] = v >> 8; }
static inline void put_u32(uint8_t *p, uint32_t v)
{
	p[0] = v & 0xff; p[1] = (v >> 8) & 0xff; p[2] = (v >> 16) & 0xff; p[3] = v >> 24;
}

static inline int iabs16(int16_t v) { return v < 0 ? -(int)v : (int)v; }

size_t btrk_raw_samples_for_mtu(uint16_t mtu)
{
	if (mtu < BTRK_RAW_MIN_MTU) {
		return 0;
	}
	size_t n = (size_t)(mtu - 3 - BTRK_RAW_HDR_SIZE) / BTRK_RAW_SAMPLE_SIZE;
	return n > BTRK_RAW_MAX_SAMPLES ? BTRK_RAW_MAX_SAMPLES : n;
}

int btrk_accel_saturated(const struct imu_sample *s)
{
	for (int i = 0; i < 3; i++) {
		if (iabs16(s->a[i]) >= BTRK_ACCEL_SAT_RAW) {
			return 1;
		}
	}
	return 0;
}

int btrk_gyro_saturated(const struct imu_sample *s)
{
	for (int i = 0; i < 3; i++) {
		if (iabs16(s->g[i]) >= BTRK_GYRO_SAT_RAW) {
			return 1;
		}
	}
	return 0;
}

size_t btrk_raw_pack(uint8_t *buf, size_t cap, const struct imu_sample *s, size_t n,
		     uint16_t seq, uint8_t flags)
{
	size_t len = BTRK_RAW_HDR_SIZE + n * BTRK_RAW_SAMPLE_SIZE;
	uint32_t amask = 0, gmask = 0;
	uint32_t period = 0;

	if (n == 0 || n > BTRK_RAW_MAX_SAMPLES || cap < len) {
		return 0;
	}
	if (n > 1) {
		/* unsigned subtraction handles 32-bit wrap */
		uint32_t span = s[n - 1].t_us - s[0].t_us;
		period = (span + (uint32_t)(n - 1) / 2) / (uint32_t)(n - 1);
		if (period > 0xffff) {
			period = 0xffff;
			flags |= BTRK_RAW_F_TS_RESYNC;
		}
	}

	uint8_t *p = buf + BTRK_RAW_HDR_SIZE;
	for (size_t i = 0; i < n; i++) {
		if (btrk_accel_saturated(&s[i])) {
			amask |= 1u << i;
		}
		if (btrk_gyro_saturated(&s[i])) {
			gmask |= 1u << i;
		}
		for (int k = 0; k < 3; k++) {
			put_u16(p + 2 * k, (uint16_t)s[i].a[k]);
			put_u16(p + 6 + 2 * k, (uint16_t)s[i].g[k]);
		}
		p += BTRK_RAW_SAMPLE_SIZE;
	}

	put_u16(buf + 0, seq);
	buf[2] = (uint8_t)n;
	buf[3] = flags;
	put_u32(buf + 4, s[0].t_us);
	put_u16(buf + 8, (uint16_t)period);
	put_u32(buf + 10, amask);
	put_u32(buf + 14, gmask);
	return len;
}
