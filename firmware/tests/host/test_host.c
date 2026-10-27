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
#include "evlog.h"
#include "btrk_util.h"

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

/* ---------------------------------------------------------------- detector */
#define FS 416.0
static struct imu_sample mk(int i, double ax, double gz)
{
	struct imu_sample s = {0};
	double a = ax / 0.000488;

	s.t_us = 0xFFFF0000u + (uint32_t)llround(i * 1e6 / FS); /* crosses the u32 wrap */
	s.a[0] = (int16_t)(a > 32767 ? 32767 : a);
	s.a[2] = (int16_t)lround(1.0 / 0.000488);
	s.g[2] = (int16_t)lround(gz / 0.07);
	return s;
}
static double pulse(double t, double t0, double amp, double sd) { return amp * exp(-0.5 * pow((t - t0) / sd, 2)); }

static struct pd_config cfg_default(void)
{
	struct pd_config c = {.threshold_g = 3.5f, .refractory_ms = 150.0f, .window_ms = 150.0f, .fs_hz = (float)FS};
	return c;
}

static int run(double (*sig)(double), double (*gyr)(double), int n, struct pd_event *all, int max)
{
	static struct pd_state st;
	struct pd_event out[PD_MAX_OUT];
	struct pd_config c = cfg_default();
	int k = 0;

	CHECK(pd_init(&st, &c) == 0);
	CHECK(st.win == 62 && st.refr == 62);
	for (int i = 0; i < n; i++) {
		struct imu_sample s = mk(i, sig(i / FS), gyr ? gyr(i / FS) : 0.0);
		int m = pd_feed(&st, &s, out);
		for (int j = 0; j < m && k < max; j++) {
			all[k++] = out[j];
		}
	}
	int m = pd_flush(&st, out);
	for (int j = 0; j < m && k < max; j++) {
		all[k++] = out[j];
	}
	return k;
}

static double sig_three(double t) { return pulse(t, 0.5, 8, 0.03) + pulse(t, 0.6, 6, 0.03) + pulse(t, 1.2, 9, 0.03); }
static double gyr_three(double t) { return pulse(t, 1.2, 500, 0.04); }
static double sig_sat(double t) { return pulse(t, 0.4, 20, 0.02); }
static double sig_long(double t) { return (t > 0.3 && t < 0.9) ? 5.0 + pulse(t, 0.8, 3, 0.01) : 0.0; }
static double sig_edge(double t) { return pulse(t, 1.98, 7, 0.02); }
static double sig_gap(double t) { return pulse(t, 0.3, 6, 0.02) + pulse(t, 0.3 + 0.200, 6, 0.02); }
static double sig_quiet(double t) { return 0.8 * sin(t * 20); }

static void test_detector(void)
{
	struct pd_event e[16];
	int n;

	/* 0.5 s and 0.6 s peaks: the second starts inside refractory -> one event */
	n = run(sig_three, gyr_three, 832, e, 16);
	CHECK(n == 2);
	CHECK(e[0].n_peak == 208);                   /* 0.5 s * 416 */
	CHECK(fabsf(e[1].peak_g - 8.055f) < 0.02f);  /* sqrt(9^2 + 1) - 1 */
	CHECK(e[1].gyro_int_deg[2] > 30.0f && e[1].peak_gyro_dps > 450.0f);
	CHECK(e[0].speed_mps_est > 0.5f && e[0].n_start < e[0].n_peak && e[0].n_end > e[0].n_peak);
	CHECK(e[0].t_peak_us == 0xFFFF0000u + (uint32_t)llround(208 * 1e6 / FS)); /* wrapped */
	CHECK(!e[0].accel_sat && !e[0].gyro_sat);
	/* clipped peak -> accel_sat, peak_g is the rail */
	n = run(sig_sat, NULL, 416, e, 16);
	CHECK(n == 1 && e[0].accel_sat && e[0].peak_g < 16.0f);
	/* a 0.6 s plateau is longer than 2 * win: the first candidate is capped at 124
	 * samples (peak = first sample, 0.3 s), the next starts at j and finds the bump at
	 * 0.8 s; same as detector.find_peaks */
	n = run(sig_long, NULL, 416, e, 16);
	CHECK(n == 2 && e[0].n_peak == 125 && e[1].n_peak == 333);
	/* 200 ms apart: two events */
	n = run(sig_gap, NULL, 416, e, 16);
	CHECK(n == 2 && e[1].n_peak - e[0].n_peak == 83);
	/* peak at the very end: flush emits it with a truncated window */
	n = run(sig_edge, NULL, 832, e, 16);
	CHECK(n == 1 && e[0].n_peak > 820);
	/* below threshold: nothing */
	n = run(sig_quiet, NULL, 832, e, 16);
	CHECK(n == 0);
	/* bad config */
	struct pd_state st;
	struct pd_config c = cfg_default();
	c.window_ms = 1000.0f;
	CHECK(pd_init(&st, &c) != 0);
}

/* ---------------------------------------------------------------- event log */
#define FL_SECT 4096u
#define FL_SIZE (8u * FL_SECT)
static uint8_t flash[FL_SIZE];
static int torn_next; /* program only the first N bytes of the next write */
static int fl_read(void *c, uint32_t off, void *b, size_t n) { (void)c; memcpy(b, flash + off, n); return 0; }
static int fl_write(void *c, uint32_t off, const void *b, size_t n)
{
	(void)c;
	const uint8_t *p = b;
	if (torn_next) {
		n = (size_t)torn_next;
		torn_next = 0;
	}
	for (size_t i = 0; i < n; i++) {
		flash[off + i] &= p[i]; /* NOR: 1 -> 0 only */
	}
	return 0;
}
static int fl_erase(void *c, uint32_t off, uint32_t n) { (void)c; memset(flash + off, 0xFF, n); return 0; }
static const struct evlog_ops ops = {fl_read, fl_write, fl_erase, NULL, FL_SIZE, FL_SECT};

static uint32_t count_from(struct evlog *l, uint32_t from, uint32_t *first, uint32_t *last)
{
	struct evlog_iter it;
	struct btrk_log_rec r;
	uint32_t n = 0, prev = 0;

	evlog_iter_start(l, &it, from);
	while (evlog_iter_next(l, &it, &r) == 1) {
		if (n == 0 && first) {
			*first = r.seq;
		}
		CHECK(r.seq > prev); /* strictly increasing */
		prev = r.seq;
		n++;
	}
	if (last) {
		*last = prev;
	}
	return n;
}

static struct evlog lg, lg2;

static void test_evlog(void)
{
	uint32_t seq, f = 0, la = 0;
	uint8_t pl[22];

	memset(flash, 0xFF, sizeof(flash));
	CHECK(evlog_mount(&lg, &ops) == 0);
	CHECK(lg.next_seq == 1 && evlog_first_seq(&lg) == 1);
	CHECK(evlog_capacity(&lg) == 7 * 128);
	CHECK(count_from(&lg, 0, NULL, NULL) == 0);
	lg.boot_id = 7;
	for (int i = 0; i < 300; i++) {
		memset(pl, i, sizeof(pl));
		CHECK(evlog_append(&lg, BTRK_LOG_EVENT, pl, sizeof(pl), &seq) == 0);
	}
	CHECK(seq == 300);
	CHECK(count_from(&lg, 0, &f, &la) == 300 && f == 1 && la == 300);
	CHECK(count_from(&lg, 250, &f, NULL) == 51 && f == 250);
	CHECK(count_from(&lg, 301, NULL, NULL) == 0);
	/* remount finds the write position */
	CHECK(evlog_mount(&lg2, &ops) == 0);
	CHECK(lg2.next_seq == 301 && lg2.head == lg.head && lg2.slot == lg.slot);
	/* wrap: 8 sectors x 128; write 1200 more -> oldest sectors recycled */
	for (int i = 0; i < 1200; i++) {
		CHECK(evlog_append(&lg2, BTRK_LOG_EVENT, pl, sizeof(pl), &seq) == 0);
	}
	CHECK(seq == 1500);
	uint32_t n = count_from(&lg2, 0, &f, &la);
	CHECK(la == 1500 && n == 1500 - f + 1 && n >= evlog_capacity(&lg2));
	CHECK(evlog_first_seq(&lg2) == f);
	CHECK(count_from(&lg2, 1400, &f, NULL) == 101 && f == 1400);
	/* torn write: power lost mid-record; slot skipped, sequence continues */
	torn_next = 10;
	CHECK(evlog_append(&lg2, BTRK_LOG_EVENT, pl, sizeof(pl), &seq) == 0);
	CHECK(evlog_mount(&lg, &ops) == 0);
	CHECK(lg.next_seq == 1501); /* torn record had seq 1501 but is invalid */
	CHECK(evlog_append(&lg, BTRK_LOG_ANCHOR, pl, 14, &seq) == 0 && seq == 1501);
	CHECK(count_from(&lg, 1499, &f, &la) == 3 && la == 1501);
	/* record CRC + layout */
	struct btrk_log_rec r;
	struct evlog_iter it;
	evlog_iter_start(&lg, &it, 1501);
	CHECK(evlog_iter_next(&lg, &it, &r) == 1 && r.type == BTRK_LOG_ANCHOR && r.boot_id == 7);
	r.payload[3] ^= 1;
	CHECK(!evlog_rec_valid(&r));
	/* erase keeps the sequence monotonic */
	CHECK(evlog_erase_all(&lg) == 0);
	CHECK(count_from(&lg, 0, &f, NULL) == 1 && f == 1502);
	CHECK(evlog_mount(&lg2, &ops) == 0 && lg2.next_seq == 1503);
	CHECK(evlog_append(&lg, 0xFF, pl, 1, NULL) != 0 && evlog_append(&lg, 1, pl, 23, NULL) != 0);
}

/* one record for the Python decoder test (tools/tests) */
static void print_record(void)
{
	struct btrk_log_event ev;
	struct btrk_log_rec r;

	memset(&ev, 0, sizeof(ev));
	memset(&r, 0, sizeof(r));
	ev.dev_t_peak_us = 0xFFFFFF00u;
	ev.type = BTRK_PUNCH_CROSS;
	ev.flags = BTRK_PUNCH_F_ACCEL_SAT | BTRK_PUNCH_F_REAR_HAND;
	ev.peak_cg = 1612;
	ev.speed_cms = 734;
	ev.peak_gyro_dps = 1450;
	ev.confidence = 100;
	ev.pre_2ms = 30;
	ev.post_2ms = 41;
	ev.gyro_int_ddeg[0] = -1234;
	ev.gyro_int_ddeg[1] = 56;
	ev.gyro_int_ddeg[2] = 32767;
	r.type = BTRK_LOG_EVENT;
	r.boot_id = 0x1234;
	r.seq = 0xA0B0C0D0u;
	memcpy(r.payload, &ev, sizeof(ev));
	evlog_rec_seal(&r);
	printf("REC ");
	for (size_t i = 0; i < sizeof(r); i++) {
		printf("%02x", ((uint8_t *)&r)[i]);
	}
	printf("\n");
}

/* ---------------------------------------------------------------- helpers */
static void test_util(void)
{
	struct btrk_adv_mfg m;
	uint8_t *b = (uint8_t *)&m;

	CHECK(btrk_crc16("123456789", 9) == 0x29B1); /* CRC-16/CCITT-FALSE check value */
	btrk_adv_mfg_fill(&m, BTRK_ROLE_REAR, BTRK_WRIST_RIGHT, BTRK_ADV_F_SESSION, 0xC0DE);
	CHECK(b[0] == 0xFF && b[1] == 0xFF && b[2] == 0x11 && b[3] == 2 && b[4] == 2 && b[5] == 1);
	CHECK(b[6] == 0xDE && b[7] == 0xC0);
	printf("ADV ");
	for (size_t i = 0; i < sizeof(m); i++) {
		printf("%02x", b[i]);
	}
	printf("\n");
	CHECK(strcmp(btrk_role_name(BTRK_ROLE_LEAD), "BoxTrk-L") == 0);
	CHECK(strcmp(btrk_role_name(BTRK_ROLE_REAR), "BoxTrk-R") == 0);
	CHECK(strcmp(btrk_role_name(BTRK_ROLE_UNSET), "BoxTrk") == 0);
	/* role policy */
	CHECK(btrk_role_write_allowed(BTRK_ROLE_UNSET, false, false));
	CHECK(!btrk_role_write_allowed(BTRK_ROLE_LEAD, false, false));
	CHECK(btrk_role_write_allowed(BTRK_ROLE_LEAD, true, false));
	CHECK(btrk_role_write_allowed(BTRK_ROLE_REAR, false, true));
	CHECK(btrk_window_open(true, 10, 120) && !btrk_window_open(true, 120, 120));
	CHECK(!btrk_window_open(false, 1, 120)); /* wake from System OFF: closed */
	CHECK(btrk_default_wrist(BTRK_ROLE_LEAD, 0) == BTRK_WRIST_LEFT);
	CHECK(btrk_default_wrist(BTRK_ROLE_REAR, 0) == BTRK_WRIST_RIGHT);
	CHECK(btrk_default_wrist(BTRK_ROLE_LEAD, 1) == BTRK_WRIST_RIGHT);
	CHECK(btrk_default_wrist(BTRK_ROLE_UNSET, 0) == BTRK_WRIST_UNKNOWN);
	/* battery */
	CHECK(btrk_batt_pct_from_mv(4250) == 100 && btrk_batt_pct_from_mv(3200) == 0);
	CHECK(btrk_batt_pct_from_mv(3800) == 50 && btrk_batt_pct_from_mv(3725) == 33);
	CHECK(btrk_batt_mv_from_pin_mv(1418) == 4198); /* 4.2 V cell -> 1.418 V at AIN7 */
	CHECK(btrk_batt_mv_from_pin_mv(-5) == 0);
}

int main(void)
{
	test_ring();
	test_mtu();
	test_pack();
	test_detector();
	test_evlog();
	test_util();
	print_record();
	printf(fails ? "HOST TESTS FAILED (%d)\n" : "HOST TESTS OK\n", fails);
	return fails ? 1 : 0;
}
