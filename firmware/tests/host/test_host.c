/* Host-side unit tests for the portable firmware modules (no Zephyr).
 *   make -C firmware/tests/host run
 * Prints one hex-encoded raw-stream packet on stdout (line "PKT <hex>") so the
 * Python tests can check that tools/proto.py decodes exactly what the C packer
 * produced (wire-format consistency between firmware and host tools). */
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

#include "bt_proto.h"
#include "imu_sample.h"
#include "punch_detect.h"
#include "raw_pack.h"
#include "ringbuf.h"

static int fails;
#define CHECK(c) do { if (!(c)) { printf("FAIL %s:%d %s\n", __FILE__, __LINE__, #c); fails++; } } while (0)

static void test_ring(void)
{
	static struct imu_sample st[8], out[8];
	struct sample_ring r;
	struct imu_sample s = {0};

	CHECK(sample_ring_init(&r, st, 6) != 0); /* not power of 2 */
	CHECK(sample_ring_init(&r, st, 8) == 0);
	for (int i = 0; i < 10; i++) {
		s.t_us = (uint32_t)i;
		sample_ring_put(&r, &s);
	}
	CHECK(sample_ring_count(&r) == 8);
	CHECK(r.dropped == 2);
	CHECK(sample_ring_get(&r, out, 5) == 5);
	CHECK(out[0].t_us == 0 && out[4].t_us == 4);
	CHECK(sample_ring_get(&r, out, 8) == 3);
	CHECK(sample_ring_count(&r) == 0);
}

static void test_mtu(void)
{
	CHECK(btrk_raw_samples_for_mtu(23) == 0);
	CHECK(btrk_raw_samples_for_mtu(33) == 1);
	CHECK(btrk_raw_samples_for_mtu(185) == 13);
	CHECK(btrk_raw_samples_for_mtu(247) == 18);
	CHECK(btrk_raw_samples_for_mtu(517) == 18);
}

static void test_pack(void)
{
	struct imu_sample s[18];
	uint8_t buf[300];

	for (int i = 0; i < 18; i++) {
		s[i].t_us = 0xFFFFF000u + (uint32_t)i * 2404u; /* crosses the 32-bit wrap */
		s[i].a[0] = (int16_t)(i * 100); s[i].a[1] = (int16_t)-i; s[i].a[2] = 2049;
		s[i].g[0] = (int16_t)(i * 10); s[i].g[1] = -5; s[i].g[2] = 7;
	}
	s[3].a[1] = 32767;   /* accel saturated */
	s[5].a[2] = -32768;  /* accel saturated */
	s[7].g[0] = 28571;   /* gyro ~2000 dps -> saturated */
	size_t len = btrk_raw_pack(buf, sizeof(buf), s, 18, 0xBEEF, BTRK_RAW_F_TS_RESYNC);
	CHECK(len == 18 + 18 * 12);
	CHECK(buf[2] == 18);
	uint32_t amask, gmask;
	memcpy(&amask, buf + 10, 4);
	memcpy(&gmask, buf + 14, 4);
	CHECK(amask == ((1u << 3) | (1u << 5)));
	CHECK(gmask == (1u << 7));
	CHECK(btrk_raw_pack(buf, 10, s, 18, 0, 0) == 0);
	CHECK(btrk_raw_pack(buf, sizeof(buf), s, 19, 0, 0) == 0);
	printf("PKT ");
	for (size_t i = 0; i < len; i++) {
		printf("%02x", buf[i]);
	}
	printf("\n");
}

static void test_detector(void)
{
	struct pd_config cfg = {.threshold_g = 3.5f, .refractory_us = 150000, .post_peak_us = 150000};
	struct pd_state st;
	struct pd_event e;
	int n_ev = 0;
	float peak = 0;

	pd_init(&st, &cfg);
	/* 2 s at 416 Hz; Gaussian 8 g pulses along x at 0.5 s and 0.6 s (100 ms apart:
	 * second one inside refractory -> merged) and at 1.2 s */
	for (int i = 0; i < 832; i++) {
		struct imu_sample s = {0};
		double t = i / 416.0;
		double ax = 8.0 * exp(-0.5 * pow((t - 0.5) / 0.03, 2)) +
			    6.0 * exp(-0.5 * pow((t - 0.6) / 0.03, 2)) +
			    9.0 * exp(-0.5 * pow((t - 1.2) / 0.03, 2));
		s.t_us = (uint32_t)(t * 1e6);
		s.a[0] = (int16_t)(ax / 0.000488 > 32767 ? 32767 : ax / 0.000488);
		s.a[2] = (int16_t)(1.0 / 0.000488);
		s.g[2] = (int16_t)(500.0 / 0.07 * exp(-0.5 * pow((t - 1.2) / 0.04, 2)));
		if (pd_feed(&st, &s, &e)) {
			n_ev++;
			peak = e.peak_g;
			CHECK(e.speed_mps_est > 0.5f);
		}
	}
	CHECK(n_ev == 2);
	CHECK(fabsf(peak - 8.06f) < 0.3f); /* sqrt(9^2+1)-1 */
	CHECK(e.gyro_int_deg[2] > 30.0f);
}

int main(void)
{
	test_ring();
	test_mtu();
	test_pack();
	test_detector();
	printf(fails ? "HOST TESTS FAILED (%d)\n" : "HOST TESTS OK\n", fails);
	return fails ? 1 : 0;
}
