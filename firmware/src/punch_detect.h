/* punch_detect.h - streaming on-device strike detector (portable C, no Zephyr).
 *
 * A sample-by-sample port of the core of analysis/detector.py (find_peaks +
 * event_bounds + the speed / gyro-integral features), so the device and the
 * offline reference find the same peaks (checked by
 * analysis/tests/test_firmware_detector.py, which runs this code on a synthetic
 * session and compares it with detector.find_peaks):
 *
 *   dyn = |a| - 1 g
 *   * a candidate starts at the first sample with dyn >= threshold that is not
 *     before `nxt` (end of the previous candidate / refractory);
 *   * the candidate extends while dyn >= threshold / 2, at most 2 * win samples;
 *     its peak is the FIRST maximum of dyn inside it;
 *   * nxt = max(end of candidate, peak + refractory);
 *   * features use the window [peak - win, peak + win]: event bounds at
 *     threshold / 4 around the peak, speed = 9.81 * sum(max(dyn, 0)) * dt from
 *     the event start to the peak, gyro integrals and peak |w| over the window,
 *     saturation if any sample in the window is at the rails.
 *   win = int(window_ms / 1000 * fs), refractory = int(refractory_ms / 1000 * fs).
 *
 * Classification (strike type) is NOT ported: on-device events are type
 * "unknown" except the calibration strike. Gyro integrals are in the chip frame.
 */
#ifndef BTRK_PUNCH_DETECT_H_
#define BTRK_PUNCH_DETECT_H_
#include <stdbool.h>
#include <stdint.h>
#include "imu_sample.h"

#define PD_HIST     256  /* history ring (power of two, >= 3 * win + 2) */
#define PD_MAX_PEND 4    /* peaks waiting for their post-peak window     */
#define PD_MAX_OUT  4    /* events one pd_feed()/pd_flush() call can emit */

struct pd_config {
	float threshold_g;   /* on |a| - 1 g, default 3.5   */
	float refractory_ms; /* default 150                 */
	float window_ms;     /* default 150                 */
	float fs_hz;         /* sample rate, 416            */
};

struct pd_event {
	uint32_t n_start, n_peak, n_end; /* sample indices since pd_init         */
	uint32_t t_start_us, t_peak_us, t_end_us;
	float peak_g;           /* dyn at peak; lower bound if accel_sat           */
	float peak_gyro_dps;    /* max |w| over the window                         */
	float gyro_int_deg[3];  /* integral of w per chip axis over the window     */
	float speed_mps_est;    /* heuristic, as detector.py                        */
	float duration_ms;      /* (n_end - n_start) / fs                           */
	int16_t peak_a[3];      /* raw accel at the peak (calibration forward axis) */
	bool accel_sat;
	bool gyro_sat;
};

struct pd_hist {
	uint32_t t_us;
	float dyn;
	int16_t a[3];
	int16_t g[3];
};

struct pd_state {
	struct pd_config cfg;
	uint32_t win, refr;     /* in samples                    */
	float lo_lvl, bound_lvl, dt;
	uint32_t n;             /* samples fed so far            */
	uint32_t nxt;
	bool in_seg;
	uint32_t seg_i, seg_ip;
	float seg_max;
	uint32_t pend[PD_MAX_PEND];
	uint8_t npend;
	uint32_t dropped;       /* peaks lost (pending queue full) */
	struct pd_hist hist[PD_HIST];
};

/* Returns 0, or -1 if the config does not fit the history ring. */
int pd_init(struct pd_state *st, const struct pd_config *cfg);
/* Feed one sample; returns the number of events written to out[0..PD_MAX_OUT). */
int pd_feed(struct pd_state *st, const struct imu_sample *s, struct pd_event *out);
/* End of stream: close an open candidate and emit everything pending (window
 * truncated at the last sample, like detector.py at the end of a recording). */
int pd_flush(struct pd_state *st, struct pd_event *out);

#endif
