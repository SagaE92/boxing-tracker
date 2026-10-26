/* session.h - session lifecycle, calibration and summary */
#ifndef BTRK_SESSION_H_
#define BTRK_SESSION_H_
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include "bt_proto.h"
#include "imu_sample.h"

enum cal_state {
	CAL_NONE = 0,   /* no session                                     */
	CAL_GUARD,      /* hold neutral guard: average gravity vector     */
	CAL_JAB,        /* waiting for the first (known) jab: forward axis */
	CAL_DONE,
};

void session_init(void);
int session_start(uint32_t session_id);
int session_stop(void);
bool session_active(void);
int session_recalibrate(void);
enum cal_state session_cal_state(void);
void session_get_summary(struct btrk_session_summary *out);
void session_get_config(struct btrk_config *out);
int session_set_config(const struct btrk_config *cfg);
/* Role (hand) changed over GATT: Config.hand follows it. */
void session_role_changed(void);
/* Control op ROUND_MARK: log it (with device time). */
void session_round_mark(uint8_t round);

/* IMU thread hook: run detector / calibration on each batch */
void session_on_samples(const struct imu_sample *s, size_t n);

#endif
