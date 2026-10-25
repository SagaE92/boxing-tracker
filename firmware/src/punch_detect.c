#include "punch_detect.h"
#include "bt_proto.h"
#include "raw_pack.h"
#include <math.h>
#include <string.h>

#define G_PER_LSB   (BTRK_ACCEL_UG_PER_LSB * 1e-6f)
#define DPS_PER_LSB (BTRK_GYRO_UDPS_PER_LSB * 1e-6f)

void pd_init(struct pd_state *st, const struct pd_config *cfg)
{
	memset(st, 0, sizeof(*st));
	st->cfg = *cfg;
}

bool pd_feed(struct pd_state *st, const struct imu_sample *s, struct pd_event *out)
{
	float ax = s->a[0] * G_PER_LSB, ay = s->a[1] * G_PER_LSB, az = s->a[2] * G_PER_LSB;
	float gx = s->g[0] * DPS_PER_LSB, gy = s->g[1] * DPS_PER_LSB, gz = s->g[2] * DPS_PER_LSB;
	float dyn = sqrtf(ax * ax + ay * ay + az * az) - 1.0f;
	float gmag = sqrtf(gx * gx + gy * gy + gz * gz);
	float dt = 0.0f;
	bool emitted = false;

	if (st->prev_t_us != 0) {
		dt = (float)(uint32_t)(s->t_us - st->prev_t_us) * 1e-6f;
	}
	st->prev_t_us = s->t_us;

	if (!st->active) {
		bool refractory = st->have_last &&
				  (uint32_t)(s->t_us - st->last_peak_us) < st->cfg.refractory_us;
		if (dyn >= st->cfg.threshold_g && !refractory) {
			memset(&st->cur, 0, sizeof(st->cur));
			st->active = true;
			st->cur.t_start_us = s->t_us;
			st->cur.t_peak_us = s->t_us;
			st->cur.peak_g = dyn;
			st->vel_acc = 0.0f;
		} else {
			return false;
		}
	}

	struct pd_event *e = &st->cur;
	e->gyro_int_deg[0] += gx * dt;
	e->gyro_int_deg[1] += gy * dt;
	e->gyro_int_deg[2] += gz * dt;
	if (gmag > e->peak_gyro_dps) {
		e->peak_gyro_dps = gmag;
	}
	if (btrk_accel_saturated(s)) {
		e->accel_sat = true;
	}
	if (btrk_gyro_saturated(s)) {
		e->gyro_sat = true;
	}
	/* crude speed: integrate positive dynamic accel up to the peak */
	st->vel_acc += (dyn > 0.0f ? dyn : 0.0f) * 9.81f * dt;
	if (dyn > e->peak_g) {
		e->peak_g = dyn;
		e->t_peak_us = s->t_us;
		e->speed_mps_est = st->vel_acc;
	}

	if ((uint32_t)(s->t_us - e->t_peak_us) >= st->cfg.post_peak_us) {
		e->t_end_us = s->t_us;
		*out = *e;
		st->active = false;
		st->have_last = true;
		st->last_peak_us = e->t_peak_us;
		emitted = true;
	}
	return emitted;
}
