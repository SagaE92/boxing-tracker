/* punch_detect.h - streaming on-device strike detector (portable C).
 *
 * STUB / first cut: threshold on |a|-1g, refractory period, peak search,
 * per-axis gyro integrals. Classification is NOT done on-device yet
 * (type = UNKNOWN); analysis/detector.py is the reference implementation
 * that will be ported once validated on real recordings. */
#ifndef BTRK_PUNCH_DETECT_H_
#define BTRK_PUNCH_DETECT_H_
#include <stdbool.h>
#include <stdint.h>
#include "imu_sample.h"

struct pd_config {
	float threshold_g;      /* on |a| - 1 g, default 3.5 */
	uint32_t refractory_us; /* default 150 ms */
	uint32_t post_peak_us;  /* close the window this long after the peak (150 ms) */
};

struct pd_event {
	uint32_t t_start_us;
	uint32_t t_peak_us;
	uint32_t t_end_us;
	float peak_g;           /* |a|-1g at peak; lower bound if accel_sat */
	float peak_gyro_dps;
	float gyro_int_deg[3];  /* integral of gyro per chip axis over the window */
	float speed_mps_est;    /* crude: integral of (|a|-1g) from start to peak */
	bool accel_sat;
	bool gyro_sat;
};

struct pd_state {
	struct pd_config cfg;
	bool active;
	bool have_last;
	uint32_t last_peak_us;
	uint32_t prev_t_us;
	struct pd_event cur;
	float vel_acc;
};

void pd_init(struct pd_state *st, const struct pd_config *cfg);
/* Feed one sample. Returns true and fills *out when a strike window closes. */
bool pd_feed(struct pd_state *st, const struct imu_sample *s, struct pd_event *out);

#endif
