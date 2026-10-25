/*
 * Session flow (see docs/gatt-spec.md "Session start / calibration"):
 *   START -> IMU streaming -> CAL_GUARD: user holds a neutral guard for
 *   CONFIG_BTRK_CAL_GUARD_MS while the gravity vector is averaged (restarts
 *   if the wrist moves) -> CAL_JAB: the first detected strike is taken as a
 *   known jab; its peak acceleration direction defines the forward axis ->
 *   CAL_DONE. Events before CAL_DONE carry BTRK_PUNCH_F_UNCALIBRATED.
 * On-device classification is a TODO (type UNKNOWN); the offline reference
 * classifier is analysis/detector.py.
 */
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <math.h>
#include <string.h>

#include "session.h"
#include "punch_detect.h"
#include "ble_svc.h"
#include "power.h"
#include "imu_lsm6ds3trc.h"

LOG_MODULE_REGISTER(session, CONFIG_BTRK_LOG_LEVEL);

#define G_PER_LSB (BTRK_ACCEL_UG_PER_LSB * 1e-6f)

static struct {
	struct k_mutex lock;
	bool active;
	uint32_t id;
	int64_t start_ms;
	uint32_t t0_us;
	struct btrk_config cfg;
	struct btrk_session_summary sum;
	uint32_t peak_sum_cg;
	struct pd_state pd;
	enum cal_state cal;
	/* calibration accumulators */
	float g_acc[3];
	float g2_acc;
	uint32_t g_n;
	uint32_t guard_t0_us;
	float gravity[3];   /* unit vector, chip frame, guard pose      */
	float forward[3];   /* unit vector, chip frame, from first jab  */
} s;

static void pd_cfg_from(const struct btrk_config *c, struct pd_config *pc)
{
	pc->threshold_g = c->threshold_cg / 100.0f;
	pc->refractory_us = (uint32_t)c->refractory_ms * 1000U;
	pc->post_peak_us = 150000U;
}

void session_init(void)
{
	k_mutex_init(&s.lock);
	s.cfg.version = BTRK_PROTO_VERSION;
	s.cfg.hand = 0;   /* lead */
	s.cfg.stance = 0; /* orthodox */
	s.cfg.odr_code = 0;
	s.cfg.threshold_cg = CONFIG_BTRK_DETECT_THRESHOLD_CG;
	s.cfg.refractory_ms = CONFIG_BTRK_DETECT_REFRACTORY_MS;
}

bool session_active(void) { return s.active; }
enum cal_state session_cal_state(void) { return s.cal; }

static void cal_reset_guard(void)
{
	memset(s.g_acc, 0, sizeof(s.g_acc));
	s.g2_acc = 0;
	s.g_n = 0;
	s.guard_t0_us = 0;
}

int session_start(uint32_t id)
{
	struct pd_config pc;

	if (s.active) {
		return -EALREADY;
	}
	k_mutex_lock(&s.lock, K_FOREVER);
	memset(&s.sum, 0, sizeof(s.sum));
	s.peak_sum_cg = 0;
	s.id = id;
	s.sum.session_id = id;
	s.sum.state = BTRK_SESS_ACTIVE;
	s.start_ms = k_uptime_get();
	s.t0_us = (uint32_t)k_ticks_to_us_floor64(k_uptime_ticks());
	pd_cfg_from(&s.cfg, &pc);
	pd_init(&s.pd, &pc);
	s.cal = CAL_GUARD;
	cal_reset_guard();
	s.active = true;
	k_mutex_unlock(&s.lock);
	LOG_INF("session %u start: hold guard pose", id);
	power_event(PWR_EVT_SESSION_START);
	ble_svc_notify_status();
	return 0;
}

int session_stop(void)
{
	if (!s.active) {
		return -EALREADY;
	}
	k_mutex_lock(&s.lock, K_FOREVER);
	s.active = false;
	s.cal = CAL_NONE;
	s.sum.duration_ms = (uint32_t)(k_uptime_get() - s.start_ms);
	s.sum.state = 0;
	k_mutex_unlock(&s.lock);
	ble_svc_notify_summary();
	power_event(PWR_EVT_SESSION_STOP);
	ble_svc_notify_status();
	return 0;
}

int session_recalibrate(void)
{
	if (!s.active) {
		return -EINVAL;
	}
	k_mutex_lock(&s.lock, K_FOREVER);
	s.cal = CAL_GUARD;
	cal_reset_guard();
	k_mutex_unlock(&s.lock);
	return 0;
}

void session_get_summary(struct btrk_session_summary *out)
{
	k_mutex_lock(&s.lock, K_FOREVER);
	*out = s.sum;
	if (s.active) {
		out->duration_ms = (uint32_t)(k_uptime_get() - s.start_ms);
	}
	if (out->duration_ms > 0) {
		out->rate_ppm_x10 = (uint16_t)MIN(0xffff, (uint64_t)out->punch_count * 600000ULL /
							       out->duration_ms);
	}
	k_mutex_unlock(&s.lock);
}

void session_get_config(struct btrk_config *out) { *out = s.cfg; }

int session_set_config(const struct btrk_config *c)
{
	if (c->hand > 1 || c->stance > 1 || c->odr_code != 0 ||
	    c->threshold_cg < 100 || c->threshold_cg > 1500 || c->refractory_ms > 1000) {
		return -EINVAL;
	}
	k_mutex_lock(&s.lock, K_FOREVER);
	s.cfg = *c;
	s.cfg.version = BTRK_PROTO_VERSION;
	k_mutex_unlock(&s.lock);
	return 0;
}

static void normalize(float v[3])
{
	float n = sqrtf(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]);
	if (n > 1e-6f) {
		v[0] /= n; v[1] /= n; v[2] /= n;
	}
}

static void cal_guard_feed(const struct imu_sample *x)
{
	float a[3] = {x->a[0] * G_PER_LSB, x->a[1] * G_PER_LSB, x->a[2] * G_PER_LSB};
	float m = sqrtf(a[0] * a[0] + a[1] * a[1] + a[2] * a[2]);

	if (fabsf(m - 1.0f) > 0.15f) { /* moving: restart the guard window */
		cal_reset_guard();
		return;
	}
	if (s.g_n == 0) {
		s.guard_t0_us = x->t_us;
	}
	for (int i = 0; i < 3; i++) {
		s.g_acc[i] += a[i];
	}
	s.g_n++;
	if ((uint32_t)(x->t_us - s.guard_t0_us) >= CONFIG_BTRK_CAL_GUARD_MS * 1000U) {
		for (int i = 0; i < 3; i++) {
			s.gravity[i] = s.g_acc[i] / s.g_n;
		}
		normalize(s.gravity);
		s.cal = CAL_JAB;
		LOG_INF("guard captured; throw one jab");
	}
}

static void handle_event(const struct pd_event *e, const struct imu_sample *peak_sample)
{
	struct btrk_punch_evt ev = {0};
	uint16_t peak_cg = (uint16_t)MIN(65535.0f, e->peak_g * 100.0f);

	if (s.cal == CAL_GUARD) {
		return; /* moving during guard: ignore, guard restarts */
	}
	if (s.cal == CAL_JAB && peak_sample) {
		/* forward axis = accel direction at the jab peak minus gravity */
		for (int i = 0; i < 3; i++) {
			s.forward[i] = peak_sample->a[i] * G_PER_LSB - s.gravity[i];
		}
		normalize(s.forward);
		s.cal = CAL_DONE;
		ev.type = BTRK_PUNCH_JAB; /* the calibration strike is a known jab */
		ev.confidence = 100;
		ble_svc_notify_status();
	} else {
		ev.type = BTRK_PUNCH_UNKNOWN; /* TODO: port analysis/detector.py rules */
		ev.confidence = 0;
		ev.flags |= (s.cal != CAL_DONE) ? BTRK_PUNCH_F_UNCALIBRATED : 0;
	}
	ev.index = s.sum.punch_count;
	ev.t_ms = (uint32_t)(e->t_peak_us - s.t0_us) / 1000U;
	ev.peak_cg = peak_cg;
	ev.speed_cms = (uint16_t)MIN(65535.0f, e->speed_mps_est * 100.0f);
	ev.peak_gyro_dps = (uint16_t)MIN(65535.0f, e->peak_gyro_dps);
	ev.flags |= e->accel_sat ? BTRK_PUNCH_F_ACCEL_SAT : 0;
	ev.flags |= e->gyro_sat ? BTRK_PUNCH_F_GYRO_SAT : 0;
	ev.flags |= s.cfg.hand ? BTRK_PUNCH_F_REAR_HAND : 0;

	s.sum.punch_count++;
	if (ev.type < BTRK_PUNCH_TYPE_COUNT) {
		s.sum.by_type[ev.type]++;
	}
	s.sum.max_peak_cg = MAX(s.sum.max_peak_cg, peak_cg);
	s.peak_sum_cg += peak_cg;
	s.sum.mean_peak_cg = (uint16_t)(s.peak_sum_cg / s.sum.punch_count);
	if (e->accel_sat && s.sum.saturated_count < 255) {
		s.sum.saturated_count++;
	}
	ble_svc_notify_punch(&ev);
	power_event(PWR_EVT_ACTIVITY);
}

void session_on_samples(const struct imu_sample *x, size_t n)
{
	struct pd_event e;
	static struct imu_sample peak;

	if (!s.active) {
		return;
	}
	k_mutex_lock(&s.lock, K_FOREVER);
	for (size_t i = 0; i < n; i++) {
		if (s.cal == CAL_GUARD) {
			cal_guard_feed(&x[i]);
		}
		bool was_active = s.pd.active;
		uint32_t prev_peak = s.pd.cur.t_peak_us;
		if (pd_feed(&s.pd, &x[i], &e)) {
			handle_event(&e, &peak);
		} else if (s.pd.active && (!was_active || s.pd.cur.t_peak_us != prev_peak)) {
			peak = x[i]; /* remember the raw sample at the running peak */
		}
	}
	k_mutex_unlock(&s.lock);
}
