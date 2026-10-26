/* pd_cli - run the firmware strike detector (src/punch_detect.c) on raw samples.
 * stdin : one sample per line "t_us ax ay az gx gy gz" (raw LSB, chip axes)
 * stdout: one event per line
 *   "EV n_peak n_start n_end t_peak_us peak_g speed gyro_peak gix giy giz asat gsat"
 * Used by analysis/tests/test_firmware_detector.py to compare with detector.py. */
#include <stdio.h>
#include <stdlib.h>
#include "punch_detect.h"

static void print(const struct pd_event *e)
{
	printf("EV %u %u %u %u %.5f %.5f %.3f %.4f %.4f %.4f %d %d\n", e->n_peak, e->n_start, e->n_end,
	       e->t_peak_us, e->peak_g, e->speed_mps_est, e->peak_gyro_dps, e->gyro_int_deg[0],
	       e->gyro_int_deg[1], e->gyro_int_deg[2], e->accel_sat, e->gyro_sat);
}

int main(int argc, char **argv)
{
	static struct pd_state st;
	struct pd_config c = {3.5f, 150.0f, 150.0f, 416.0f};
	struct pd_event out[PD_MAX_OUT];
	unsigned long t;
	int v[6];

	if (argc > 1) {
		c.fs_hz = (float)atof(argv[1]);
	}
	if (argc > 2) {
		c.threshold_g = (float)atof(argv[2]);
	}
	if (pd_init(&st, &c)) {
		return 2;
	}
	while (scanf("%lu %d %d %d %d %d %d", &t, &v[0], &v[1], &v[2], &v[3], &v[4], &v[5]) == 7) {
		struct imu_sample s = {.t_us = (uint32_t)t};
		for (int i = 0; i < 3; i++) {
			s.a[i] = (int16_t)v[i];
			s.g[i] = (int16_t)v[3 + i];
		}
		int n = pd_feed(&st, &s, out);
		for (int i = 0; i < n; i++) {
			print(&out[i]);
		}
	}
	int n = pd_flush(&st, out);
	for (int i = 0; i < n; i++) {
		print(&out[i]);
	}
	fprintf(stderr, "samples %u dropped %u\n", st.n, st.dropped);
	return 0;
}
