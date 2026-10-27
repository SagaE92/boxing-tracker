/* punch_detect.c - see punch_detect.h (port of analysis/detector.py find_peaks). */
#include "punch_detect.h"
#include "bt_proto.h"
#include <math.h>
#include <string.h>

#define G_PER_LSB   (BTRK_ACCEL_UG_PER_LSB * 1e-6f)
#define DPS_PER_LSB (BTRK_GYRO_UDPS_PER_LSB * 1e-6f)
#define H(st, k)    (&(st)->hist[(k) & (PD_HIST - 1)])

static int16_t iabs16(int16_t v) { return (int16_t)(v < 0 ? (v == -32768 ? 32767 : -v) : v); }

int pd_init(struct pd_state *st, const struct pd_config *cfg)
{
	memset(st, 0, sizeof(*st));
	st->cfg = *cfg;
	/* same truncation as detector.py: int(ms / 1000 * fs) */
	st->win = (uint32_t)(cfg->window_ms / 1000.0f * cfg->fs_hz);
	st->refr = (uint32_t)(cfg->refractory_ms / 1000.0f * cfg->fs_hz);
	st->lo_lvl = 0.5f * cfg->threshold_g;
	st->bound_lvl = 0.25f * cfg->threshold_g;
	st->dt = 1.0f / cfg->fs_hz;
	if (st->win == 0 || 3 * st->win + 2 > PD_HIST) {
		return -1;
	}
	return 0;
}

/* Features over [lo, hi) around ip (detector.features / event_bounds). */
static void make_event(const struct pd_state *st, uint32_t ip, uint32_t hi, struct pd_event *e)
{
	uint32_t lo = ip >= st->win ? ip - st->win : 0;
	uint32_t a = ip, b = ip;
	float v = 0.0f;

	memset(e, 0, sizeof(*e));
	while (a > lo && H(st, a - 1)->dyn >= st->bound_lvl) {
		a--;
	}
	while (b + 1 < hi && H(st, b + 1)->dyn >= st->bound_lvl) {
		b++;
	}
	for (uint32_t k = a; k <= ip; k++) {
		float d = H(st, k)->dyn;
		v += d > 0.0f ? d : 0.0f;
	}
	for (uint32_t k = lo; k < hi; k++) {
		const struct pd_hist *x = H(st, k);
		float gx = x->g[0] * DPS_PER_LSB, gy = x->g[1] * DPS_PER_LSB, gz = x->g[2] * DPS_PER_LSB;
		float gm = sqrtf(gx * gx + gy * gy + gz * gz);

		e->gyro_int_deg[0] += gx * st->dt;
		e->gyro_int_deg[1] += gy * st->dt;
		e->gyro_int_deg[2] += gz * st->dt;
		if (gm > e->peak_gyro_dps) {
			e->peak_gyro_dps = gm;
		}
		for (int i = 0; i < 3; i++) {
			if (iabs16(x->a[i]) >= BTRK_ACCEL_SAT_RAW) {
				e->accel_sat = true;
			}
			if (iabs16(x->g[i]) >= BTRK_GYRO_SAT_RAW) {
				e->gyro_sat = true;
			}
		}
	}
	const struct pd_hist *p = H(st, ip);
	e->n_start = a;
	e->n_peak = ip;
	e->n_end = b;
	e->t_start_us = H(st, a)->t_us;
	e->t_peak_us = p->t_us;
	e->t_end_us = H(st, b)->t_us;
	e->peak_g = p->dyn;
	e->speed_mps_est = v * st->dt * 9.81f;
	e->duration_ms = (float)(b - a) * st->dt * 1000.0f;
	memcpy(e->peak_a, p->a, sizeof(e->peak_a));
}

static void push_pending(struct pd_state *st, uint32_t ip)
{
	if (st->npend < PD_MAX_PEND) {
		st->pend[st->npend++] = ip;
	} else {
		st->dropped++;
	}
}

/* Emit pending peaks whose window is complete (k = last index available). */
static int emit_ready(struct pd_state *st, uint32_t avail_end, bool flush, struct pd_event *out)
{
	int n = 0;
	uint8_t keep = 0;

	for (uint8_t i = 0; i < st->npend; i++) {
		uint32_t ip = st->pend[i];
		uint32_t hi = ip + st->win + 1;

		if (hi <= avail_end || flush) {
			if (hi > avail_end) {
				hi = avail_end;
			}
			if (n < PD_MAX_OUT) {
				make_event(st, ip, hi, &out[n++]);
			} else {
				st->dropped++;
			}
		} else {
			st->pend[keep++] = ip;
		}
	}
	st->npend = keep;
	return n;
}

int pd_feed(struct pd_state *st, const struct imu_sample *s, struct pd_event *out)
{
	float ax = s->a[0] * G_PER_LSB, ay = s->a[1] * G_PER_LSB, az = s->a[2] * G_PER_LSB;
	float dyn = sqrtf(ax * ax + ay * ay + az * az) - 1.0f;
	uint32_t k = st->n;
	struct pd_hist *h = H(st, k);

	h->t_us = s->t_us;
	h->dyn = dyn;
	memcpy(h->a, s->a, sizeof(h->a));
	memcpy(h->g, s->g, sizeof(h->g));

	if (st->in_seg) {
		if (k < st->seg_i + 2 * st->win && dyn >= st->lo_lvl) {
			if (dyn > st->seg_max) { /* first maximum wins, like np.argmax */
				st->seg_max = dyn;
				st->seg_ip = k;
			}
		} else {
			uint32_t nx = st->seg_ip + st->refr;

			st->in_seg = false;
			st->nxt = k > nx ? k : nx;
			push_pending(st, st->seg_ip);
		}
	}
	if (!st->in_seg && dyn >= st->cfg.threshold_g && k >= st->nxt) {
		st->in_seg = true;
		st->seg_i = st->seg_ip = k;
		st->seg_max = dyn;
	}
	st->n = k + 1;
	return emit_ready(st, st->n, false, out);
}

int pd_flush(struct pd_state *st, struct pd_event *out)
{
	if (st->in_seg) {
		st->in_seg = false;
		push_pending(st, st->seg_ip);
	}
	return emit_ready(st, st->n, true, out);
}
