/*
 * Session flow (see docs/gatt-spec.md "Session start / calibration"):
 *   START -> IMU streaming -> CAL_GUARD: user holds a neutral guard for
 *   CONFIG_BTRK_CAL_GUARD_MS while the gravity vector is averaged (restarts
 *   if the wrist moves) -> CAL_JAB: the first detected strike is taken as a
 *   known jab; its peak acceleration direction defines the forward axis ->
 *   CAL_DONE. Events before CAL_DONE carry BTRK_PUNCH_F_UNCALIBRATED.
 * On-device classification is a TODO (type UNKNOWN); the offline reference
 * classifier is analysis/detector.py.
 *
 * Every event (and session start/stop, round marks) is also appended to the
 * flash event log (event_log.c), connected or not, so a session survives
 * disconnects and can be fetched later over 0x000A. The hand comes from the
 * role (role.c) once one is assigned.
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
#include "event_log.h"
#include "role.h"

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

static void handle_event(const struct pd_event *e);

static void pd_cfg_from(const struct btrk_config *c, struct pd_config *pc)
{
	pc->threshold_g = c->threshold_cg / 100.0f;
	pc->refractory_ms = (float)c->refractory_ms;
	pc->window_ms = 150.0f;      /* detector.py Params.window_ms */
	pc->fs_hz = (float)IMU_ODR_HZ;
}

static void hand_from_role(void)
{
	uint8_t r = role_get();

	if (r != BTRK_ROLE_UNSET) {
		s.cfg.hand = (r == BTRK_ROLE_REAR) ? 1 : 0;
	}
}

void session_role_changed(void)
{
	k_mutex_lock(&s.lock, K_FOREVER);
	hand_from_role();
	k_mutex_unlock(&s.lock);
}

void session_round_mark(uint8_t round)
{
	struct btrk_log_round r = {0};

	r.dev_t_us = (uint32_t)k_ticks_to_us_floor64(k_uptime_ticks());
	r.round = round;
	(void)elog_append(BTRK_LOG_ROUND_MARK, &r, sizeof(r));
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
	hand_from_role();
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
	hand_from_role();
	pd_cfg_from(&s.cfg, &pc);
	if (pd_init(&s.pd, &pc)) {
		k_mutex_unlock(&s.lock);
		return -EINVAL;
	}
	s.cal = CAL_GUARD;
	cal_reset_guard();
	s.active = true;
	struct btrk_log_session_start ls = {
		.session_id = id, .dev_t0_us = s.t0_us,
		.role = role_get(), .wrist = role_wrist(), .stance = s.cfg.stance,
		.odr_code = s.cfg.odr_code, .threshold_cg = s.cfg.threshold_cg,
		.refractory_ms = s.cfg.refractory_ms,
		.fw_major = 0, .fw_minor = 2, .fw_patch = 0,
	};
	(void)elog_append(BTRK_LOG_SESSION_START, &ls, sizeof(ls));
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
	struct pd_event e[PD_MAX_OUT];
	int m = pd_flush(&s.pd, e); /* a strike right before STOP */
	for (int j = 0; j < m; j++) {
		handle_event(&e[j]);
	}
	s.active = false;
	s.cal = CAL_NONE;
	s.sum.duration_ms = (uint32_t)(k_uptime_get() - s.start_ms);
	s.sum.state = 0;
	struct btrk_log_session_stop lt = {
		.session_id = s.id, .duration_ms = s.sum.duration_ms,
		.dev_t_us = (uint32_t)k_ticks_to_us_floor64(k_uptime_ticks()),
		.punch_count = s.sum.punch_count,
	};
	(void)elog_append(BTRK_LOG_SESSION_STOP, &lt, sizeof(lt));
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

void session_get_config(struct btrk_config *out)
{
	k_mutex_lock(&s.lock, K_FOREVER);
	hand_from_role();
	*out = s.cfg;
	k_mutex_unlock(&s.lock);
}

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

static uint8_t sat_u8(uint32_t v) { return (uint8_t)MIN(v, 255U); }

static void handle_event(const struct pd_event *e)
{
	struct imu_sample peak = {.t_us = e->t_peak_us};
	const struct imu_sample *peak_sample = &peak;

	memcpy(peak.a, e->peak_a, sizeof(peak.a));

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
		/* the calibration strike is a known straight: jab (lead) / cross (rear) */
		ev.type = s.cfg.hand ? BTRK_PUNCH_CROSS : BTRK_PUNCH_JAB;
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
	struct btrk_log_event le = {
		.dev_t_peak_us = e->t_peak_us,
		.type = ev.type, .flags = ev.flags, .peak_cg = ev.peak_cg,
		.speed_cms = ev.speed_cms, .peak_gyro_dps = ev.peak_gyro_dps,
		.confidence = ev.confidence,
		.pre_2ms = sat_u8((e->t_peak_us - e->t_start_us) / 2000U),
		.post_2ms = sat_u8((e->t_end_us - e->t_peak_us) / 2000U),
	};
	for (int i = 0; i < 3; i++) {
		le.gyro_int_ddeg[i] = (int16_t)CLAMP(lroundf(e->gyro_int_deg[i] * 10.0f), -32767, 32767);
	}
	if (elog_append(BTRK_LOG_EVENT, &le, sizeof(le)) == -ENOMSG) {
		LOG_WRN("event log queue full");
	}
	power_event(PWR_EVT_ACTIVITY);
}

void session_on_samples(const struct imu_sample *x, size_t n)
{
	struct pd_event e[PD_MAX_OUT];

	if (!s.active) {
		return;
	}
	k_mutex_lock(&s.lock, K_FOREVER);
	for (size_t i = 0; i < n; i++) {
		if (s.cal == CAL_GUARD) {
			cal_guard_feed(&x[i]);
		}
		int m = pd_feed(&s.pd, &x[i], e);
		for (int j = 0; j < m; j++) {
			handle_event(&e[j]);
		}
	}
	k_mutex_unlock(&s.lock);
}
