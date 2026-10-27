#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <zephyr/bluetooth/bluetooth.h>
#include <zephyr/bluetooth/conn.h>
#include <zephyr/bluetooth/gatt.h>
#include <zephyr/bluetooth/uuid.h>
#include <zephyr/bluetooth/services/bas.h>
#include <zephyr/drivers/hwinfo.h>
#include <zephyr/sys/byteorder.h>
#include <string.h>

#include "btrk_util.h"
#include "event_log.h"
#include "role.h"

#include "ble_svc.h"
#include "imu_lsm6ds3trc.h"
#include "power.h"
#include "raw_pack.h"
#include "ringbuf.h"
#include "session.h"

LOG_MODULE_REGISTER(ble_svc, CONFIG_BTRK_LOG_LEVEL);

/* 6e7bXXXX-4b1d-4c8a-9a3e-2f5b0c1d7a00 */
#define BTRK_UUID(x) BT_UUID_128_ENCODE(0x6e7b0000 | (x), 0x4b1d, 0x4c8a, 0x9a3e, 0x2f5b0c1d7a00)

static struct bt_uuid_128 uuid_svc = BT_UUID_INIT_128(BTRK_UUID(BTRK_UUID_SERVICE));
static struct bt_uuid_128 uuid_punch = BT_UUID_INIT_128(BTRK_UUID(BTRK_UUID_PUNCH_EVENT));
static struct bt_uuid_128 uuid_ctrl = BT_UUID_INIT_128(BTRK_UUID(BTRK_UUID_SESSION_CTRL));
static struct bt_uuid_128 uuid_sum = BT_UUID_INIT_128(BTRK_UUID(BTRK_UUID_SESSION_SUM));
static struct bt_uuid_128 uuid_raw = BT_UUID_INIT_128(BTRK_UUID(BTRK_UUID_RAW_STREAM));
static struct bt_uuid_128 uuid_cfg = BT_UUID_INIT_128(BTRK_UUID(BTRK_UUID_CONFIG));
static struct bt_uuid_128 uuid_status = BT_UUID_INIT_128(BTRK_UUID(BTRK_UUID_STATUS));
static struct bt_uuid_128 uuid_time = BT_UUID_INIT_128(BTRK_UUID(BTRK_UUID_TIME_SYNC));
static struct bt_uuid_128 uuid_role = BT_UUID_INIT_128(BTRK_UUID(BTRK_UUID_ROLE));
static struct bt_uuid_128 uuid_log = BT_UUID_INIT_128(BTRK_UUID(BTRK_UUID_EVENT_LOG));

static struct bt_conn *cur_conn;
static atomic_t raw_on;
static bool punch_ntf, sum_ntf, raw_ntf, status_ntf, ctrl_ind, log_ntf;
static uint16_t raw_seq;
static atomic_t raw_flags;

/* raw sample ring (IMU thread -> raw TX thread) */
static struct imu_sample ring_storage[CONFIG_BTRK_RING_SAMPLES];
static struct sample_ring ring;
static K_SEM_DEFINE(raw_sem, 0, 1);

/* ---------------- GATT callbacks ---------------- */

static void ccc_punch(const struct bt_gatt_attr *a, uint16_t v) { punch_ntf = v == BT_GATT_CCC_NOTIFY; }
static void ccc_sum(const struct bt_gatt_attr *a, uint16_t v) { sum_ntf = v == BT_GATT_CCC_NOTIFY; }
static void ccc_raw(const struct bt_gatt_attr *a, uint16_t v) { raw_ntf = v == BT_GATT_CCC_NOTIFY; }
static void ccc_status(const struct bt_gatt_attr *a, uint16_t v) { status_ntf = v == BT_GATT_CCC_NOTIFY; }
static void ccc_ctrl(const struct bt_gatt_attr *a, uint16_t v) { ctrl_ind = v == BT_GATT_CCC_INDICATE; }
static void ccc_log(const struct bt_gatt_attr *a, uint16_t v) { log_ntf = v == BT_GATT_CCC_NOTIFY; }

/* ATT error for a refused role change: ask unencrypted centrals to pair first. */
static ssize_t role_denied(struct bt_conn *c)
{
	return BT_GATT_ERR(bt_conn_get_security(c) < BT_SECURITY_L2 ? BT_ATT_ERR_AUTHENTICATION
								     : BT_ATT_ERR_WRITE_NOT_PERMITTED);
}

static ssize_t read_sum(struct bt_conn *c, const struct bt_gatt_attr *attr, void *buf,
			uint16_t len, uint16_t off)
{
	struct btrk_session_summary sm;

	session_get_summary(&sm);
	return bt_gatt_attr_read(c, attr, buf, len, off, &sm, sizeof(sm));
}

static ssize_t read_cfg(struct bt_conn *c, const struct bt_gatt_attr *attr, void *buf,
			uint16_t len, uint16_t off)
{
	struct btrk_config cfg;

	session_get_config(&cfg);
	return bt_gatt_attr_read(c, attr, buf, len, off, &cfg, sizeof(cfg));
}

static ssize_t write_cfg(struct bt_conn *c, const struct bt_gatt_attr *attr, const void *buf,
			 uint16_t len, uint16_t off, uint8_t flags)
{
	struct btrk_config cfg;

	if (off != 0 || len != sizeof(cfg)) {
		return BT_GATT_ERR(BT_ATT_ERR_INVALID_ATTRIBUTE_LEN);
	}
	memcpy(&cfg, buf, sizeof(cfg));
	uint8_t role = role_get();
	/* v1.1: the hand comes from the role once one is set; a conflicting hand is
	 * refused. With no role yet, Config.hand assigns it (v1.0 centrals). */
	if (role != BTRK_ROLE_UNSET && cfg.hand != (role == BTRK_ROLE_REAR ? 1 : 0)) {
		return BT_GATT_ERR(BT_ATT_ERR_VALUE_NOT_ALLOWED);
	}
	if (session_set_config(&cfg)) {
		return BT_GATT_ERR(BT_ATT_ERR_VALUE_NOT_ALLOWED);
	}
	if (role == BTRK_ROLE_UNSET) {
		uint8_t nr = cfg.hand ? BTRK_ROLE_REAR : BTRK_ROLE_LEAD;
		(void)role_set(nr, btrk_default_wrist(nr, cfg.stance));
		ble_svc_update_adv();
	}
	return len;
}

static ssize_t read_time(struct bt_conn *c, const struct bt_gatt_attr *attr, void *buf,
			 uint16_t len, uint16_t off)
{
	struct btrk_time_sync ts = {
		/* same clock as raw-stream t0_us and the IMU sample timestamps */
		.device_time_us = (uint32_t)k_ticks_to_us_floor64(k_uptime_ticks()),
		.boot_id = role_boot_id(),
		.flags = session_active() ? BTRK_TS_F_SESSION : 0,
	};

	return bt_gatt_attr_read(c, attr, buf, len, off, &ts, sizeof(ts));
}

static ssize_t write_time(struct bt_conn *c, const struct bt_gatt_attr *attr, const void *buf,
			  uint16_t len, uint16_t off, uint8_t flags)
{
	struct btrk_log_anchor la = {0};

	if (off != 0 || len != sizeof(la.a)) {
		return BT_GATT_ERR(BT_ATT_ERR_INVALID_ATTRIBUTE_LEN);
	}
	memcpy(&la.a, buf, sizeof(la.a));
	(void)elog_append(BTRK_LOG_ANCHOR, &la, sizeof(la));
	return len;
}

static void fill_role(struct bt_conn *c, struct btrk_role_chr *r)
{
	r->role = role_get();
	r->wrist = role_wrist();
	r->flags = (role_window_open() ? BTRK_ROLE_F_WINDOW_OPEN : 0) |
		   (role_link_bonded(c) ? BTRK_ROLE_F_BONDED_LINK : 0) |
		   (role_persisted() ? BTRK_ROLE_F_PERSISTED : 0);
	r->window_s = role_window_left_s();
}

static ssize_t read_role(struct bt_conn *c, const struct bt_gatt_attr *attr, void *buf,
			 uint16_t len, uint16_t off)
{
	struct btrk_role_chr r;

	fill_role(c, &r);
	return bt_gatt_attr_read(c, attr, buf, len, off, &r, sizeof(r));
}

static ssize_t write_role(struct bt_conn *c, const struct bt_gatt_attr *attr, const void *buf,
			  uint16_t len, uint16_t off, uint8_t flags)
{
	const uint8_t *p = buf;

	if (off != 0 || (len != 2 && len != sizeof(struct btrk_role_chr))) {
		return BT_GATT_ERR(BT_ATT_ERR_INVALID_ATTRIBUTE_LEN);
	}
	if (p[0] > BTRK_ROLE_REAR || p[1] > BTRK_WRIST_RIGHT) {
		return BT_GATT_ERR(BT_ATT_ERR_VALUE_NOT_ALLOWED);
	}
	if (session_active()) {
		return BT_GATT_ERR(BT_ATT_ERR_WRITE_NOT_PERMITTED);
	}
	if (!role_write_allowed(c)) {
		return role_denied(c);
	}
	if (role_set(p[0], p[1])) {
		return BT_GATT_ERR(BT_ATT_ERR_UNLIKELY);
	}
	session_role_changed();
	ble_svc_update_adv();
	return len;
}

static ssize_t read_log(struct bt_conn *c, const struct bt_gatt_attr *attr, void *buf,
			uint16_t len, uint16_t off)
{
	struct btrk_log_info li;

	elog_info(&li);
	return bt_gatt_attr_read(c, attr, buf, len, off, &li, sizeof(li));
}

static ssize_t write_log(struct bt_conn *c, const struct bt_gatt_attr *attr, const void *buf,
			 uint16_t len, uint16_t off, uint8_t flags)
{
	if (off != 0 || len < 1) {
		return BT_GATT_ERR(BT_ATT_ERR_INVALID_ATTRIBUTE_LEN);
	}
	switch (elog_op(buf, len)) {
	case BTRK_ST_OK:
		ble_svc_update_adv();
		return len;
	case BTRK_ST_INVALID_PARAM:
		return BT_GATT_ERR(BT_ATT_ERR_VALUE_NOT_ALLOWED);
	case BTRK_ST_UNSUPPORTED:
		return BT_GATT_ERR(BT_ATT_ERR_NOT_SUPPORTED);
	default:
		return BT_GATT_ERR(BT_ATT_ERR_PROCEDURE_IN_PROGRESS);
	}
}

static void fill_status(struct btrk_status *st)
{
	enum cal_state cs = session_cal_state();

	st->power_state = (uint8_t)power_state_get();
	st->flags = (atomic_get(&raw_on) ? 0x01 : 0) | (session_active() ? 0x02 : 0) |
		    (cs == CAL_DONE ? 0x04 : 0) |
		    ((cs == CAL_GUARD || cs == CAL_JAB) ? 0x08 : 0);
	st->dropped = (uint16_t)MIN(ring.dropped, 0xffff);
}

static ssize_t read_status(struct bt_conn *c, const struct bt_gatt_attr *attr, void *buf,
			   uint16_t len, uint16_t off)
{
	struct btrk_status st;

	fill_status(&st);
	return bt_gatt_attr_read(c, attr, buf, len, off, &st, sizeof(st));
}

static void ctrl_respond(uint8_t op, uint8_t status);

static ssize_t write_ctrl(struct bt_conn *c, const struct bt_gatt_attr *attr, const void *buf,
			  uint16_t len, uint16_t off, uint8_t flags)
{
	const uint8_t *p = buf;
	uint8_t st = BTRK_ST_OK;
	int err = 0;

	if (off != 0 || len < 1) {
		return BT_GATT_ERR(BT_ATT_ERR_INVALID_ATTRIBUTE_LEN);
	}
	switch (p[0]) {
	case BTRK_OP_SESSION_START:
		if (len != 5) {
			st = BTRK_ST_INVALID_PARAM;
			break;
		}
		err = session_start(sys_get_le32(p + 1));
		break;
	case BTRK_OP_SESSION_STOP:
		err = session_stop();
		break;
	case BTRK_OP_RAW_START:
		if (!IS_ENABLED(CONFIG_BTRK_RAW_STREAM)) {
			st = BTRK_ST_UNSUPPORTED; /* debug mode compiled out */
			break;
		}
		sample_ring_reset(&ring);
		atomic_set(&raw_on, 1);
		atomic_or(&raw_flags, BTRK_RAW_F_TS_RESYNC);
		power_event(PWR_EVT_RAW_START);
		break;
	case BTRK_OP_RAW_STOP:
		atomic_set(&raw_on, 0);
		power_event(PWR_EVT_RAW_STOP);
		break;
	case BTRK_OP_ROUND_MARK:
		LOG_INF("round mark %u", len > 1 ? p[1] : 0);
		session_round_mark(len > 1 ? p[1] : 0);
		break;
	case BTRK_OP_FORGET:
		if (session_active()) {
			st = BTRK_ST_BAD_STATE;
		} else if (!role_write_allowed(c)) {
			st = BTRK_ST_NOT_PERMITTED;
		} else {
			err = role_forget(); /* also drops this link's bond */
			session_role_changed();
			ble_svc_update_adv();
		}
		break;
	case BTRK_OP_POWER_OFF:
		power_event(PWR_EVT_OFF_REQUEST);
		break;
	case BTRK_OP_CALIBRATE:
		err = session_recalibrate();
		break;
	default:
		st = BTRK_ST_UNSUPPORTED;
	}
	if (st == BTRK_ST_OK && err) {
		st = BTRK_ST_BAD_STATE;
	}
	ctrl_respond(p[0], st);
	ble_svc_notify_status();
	return len;
}

BT_GATT_SERVICE_DEFINE(btrk_svc,
	BT_GATT_PRIMARY_SERVICE(&uuid_svc),
	/* [1,2,3] punch event */
	BT_GATT_CHARACTERISTIC(&uuid_punch.uuid, BT_GATT_CHRC_NOTIFY, BT_GATT_PERM_NONE,
			       NULL, NULL, NULL),
	BT_GATT_CCC(ccc_punch, BT_GATT_PERM_READ | BT_GATT_PERM_WRITE),
	/* [4,5,6] session control point */
	BT_GATT_CHARACTERISTIC(&uuid_ctrl.uuid, BT_GATT_CHRC_WRITE | BT_GATT_CHRC_INDICATE,
			       BT_GATT_PERM_WRITE, NULL, write_ctrl, NULL),
	BT_GATT_CCC(ccc_ctrl, BT_GATT_PERM_READ | BT_GATT_PERM_WRITE),
	/* [7,8,9] session summary */
	BT_GATT_CHARACTERISTIC(&uuid_sum.uuid, BT_GATT_CHRC_READ | BT_GATT_CHRC_NOTIFY,
			       BT_GATT_PERM_READ, read_sum, NULL, NULL),
	BT_GATT_CCC(ccc_sum, BT_GATT_PERM_READ | BT_GATT_PERM_WRITE),
	/* [10,11,12] raw stream */
	BT_GATT_CHARACTERISTIC(&uuid_raw.uuid, BT_GATT_CHRC_NOTIFY, BT_GATT_PERM_NONE,
			       NULL, NULL, NULL),
	BT_GATT_CCC(ccc_raw, BT_GATT_PERM_READ | BT_GATT_PERM_WRITE),
	/* [13,14] config */
	BT_GATT_CHARACTERISTIC(&uuid_cfg.uuid, BT_GATT_CHRC_READ | BT_GATT_CHRC_WRITE,
			       BT_GATT_PERM_READ | BT_GATT_PERM_WRITE, read_cfg, write_cfg, NULL),
	/* [15,16,17] status */
	BT_GATT_CHARACTERISTIC(&uuid_status.uuid, BT_GATT_CHRC_READ | BT_GATT_CHRC_NOTIFY,
			       BT_GATT_PERM_READ, read_status, NULL, NULL),
	BT_GATT_CCC(ccc_status, BT_GATT_PERM_READ | BT_GATT_PERM_WRITE),
	/* [18,19] time sync (v1.1) */
	BT_GATT_CHARACTERISTIC(&uuid_time.uuid, BT_GATT_CHRC_READ | BT_GATT_CHRC_WRITE,
			       BT_GATT_PERM_READ | BT_GATT_PERM_WRITE, read_time, write_time, NULL),
	/* [20,21] hand role (v1.1); write policy in write_role() */
	BT_GATT_CHARACTERISTIC(&uuid_role.uuid, BT_GATT_CHRC_READ | BT_GATT_CHRC_WRITE,
			       BT_GATT_PERM_READ | BT_GATT_PERM_WRITE, read_role, write_role, NULL),
	/* [22,23,24] event log (v1.1) */
	BT_GATT_CHARACTERISTIC(&uuid_log.uuid,
			       BT_GATT_CHRC_READ | BT_GATT_CHRC_WRITE | BT_GATT_CHRC_NOTIFY,
			       BT_GATT_PERM_READ | BT_GATT_PERM_WRITE, read_log, write_log, NULL),
	BT_GATT_CCC(ccc_log, BT_GATT_PERM_READ | BT_GATT_PERM_WRITE),
);

#define ATTR_PUNCH  (&btrk_svc.attrs[2])
#define ATTR_CTRL   (&btrk_svc.attrs[5])
#define ATTR_SUM    (&btrk_svc.attrs[8])
#define ATTR_RAW    (&btrk_svc.attrs[11])
#define ATTR_STATUS (&btrk_svc.attrs[16])
#define ATTR_LOG    (&btrk_svc.attrs[23])

static struct bt_gatt_indicate_params ind_params;
static uint8_t ind_buf[3];

static void ctrl_respond(uint8_t op, uint8_t status)
{
	if (!cur_conn || !ctrl_ind) {
		return;
	}
	ind_buf[0] = BTRK_OP_RESPONSE;
	ind_buf[1] = op;
	ind_buf[2] = status;
	memset(&ind_params, 0, sizeof(ind_params));
	ind_params.attr = ATTR_CTRL;
	ind_params.data = ind_buf;
	ind_params.len = sizeof(ind_buf);
	(void)bt_gatt_indicate(cur_conn, &ind_params);
}

void ble_svc_notify_punch(const struct btrk_punch_evt *ev)
{
	if (cur_conn && punch_ntf) {
		(void)bt_gatt_notify(cur_conn, ATTR_PUNCH, ev, sizeof(*ev));
	}
	/* every event is also appended to the flash log by session.c */
}

size_t ble_svc_log_room(void)
{
	struct bt_conn *c = cur_conn;

	return (c && log_ntf) ? (size_t)bt_gatt_get_mtu(c) - 3 : 0;
}

int ble_svc_log_send(const void *buf, size_t len)
{
	struct bt_conn *c = cur_conn;

	if (!c || !log_ntf) {
		return -ENOTCONN;
	}
	return bt_gatt_notify(c, ATTR_LOG, buf, (uint16_t)len);
}

void ble_svc_notify_summary(void)
{
	struct btrk_session_summary sm;

	if (cur_conn && sum_ntf) {
		session_get_summary(&sm);
		(void)bt_gatt_notify(cur_conn, ATTR_SUM, &sm, sizeof(sm));
	}
}

void ble_svc_notify_status(void)
{
	struct btrk_status st;

	if (cur_conn && status_ntf) {
		fill_status(&st);
		(void)bt_gatt_notify(cur_conn, ATTR_STATUS, &st, sizeof(st));
	}
	ble_svc_update_adv(); /* session flag in the advertising data */
}

bool ble_raw_streaming(void) { return atomic_get(&raw_on); }

void ble_raw_push(const struct imu_sample *s, size_t n, uint8_t imu_flags)
{
	if (!atomic_get(&raw_on)) {
		return;
	}
	if (imu_flags & IMU_FLAG_FIFO_OVERRUN) {
		atomic_or(&raw_flags, BTRK_RAW_F_FIFO_OVERRUN);
	}
	if (imu_flags & IMU_FLAG_TS_RESYNC) {
		atomic_or(&raw_flags, BTRK_RAW_F_TS_RESYNC);
	}
	for (size_t i = 0; i < n; i++) {
		if (!sample_ring_put(&ring, &s[i])) {
			atomic_or(&raw_flags, BTRK_RAW_F_RING_OVERRUN);
		}
	}
	k_sem_give(&raw_sem);
}

/* Raw TX thread: pack as many samples as the MTU allows into each notification. */
static void raw_tx_thread(void *a, void *b, void *c)
{
	static struct imu_sample batch[BTRK_RAW_MAX_SAMPLES];
	static uint8_t pkt[BTRK_RAW_HDR_SIZE + BTRK_RAW_MAX_SAMPLES * BTRK_RAW_SAMPLE_SIZE];

	for (;;) {
		k_sem_take(&raw_sem, K_FOREVER);
		while (atomic_get(&raw_on) && cur_conn && raw_ntf) {
			size_t max = btrk_raw_samples_for_mtu(bt_gatt_get_mtu(cur_conn));
			if (max == 0 || sample_ring_count(&ring) < max) {
				break; /* wait for a full packet */
			}
			size_t n = sample_ring_get(&ring, batch, max);
			uint8_t fl = (uint8_t)atomic_clear(&raw_flags);
			size_t len = btrk_raw_pack(pkt, sizeof(pkt), batch, n, raw_seq++, fl);
			/* bt_gatt_notify blocks for a TX buffer when the link is busy */
			if (len && bt_gatt_notify(cur_conn, ATTR_RAW, pkt, len)) {
				atomic_or(&raw_flags, BTRK_RAW_F_RING_OVERRUN);
			}
		}
	}
}
K_THREAD_DEFINE(raw_tx_tid, 1536, raw_tx_thread, NULL, NULL, NULL, 5, 0, 0);

/* ---------------- connection / advertising ---------------- */

/* ADV: flags + service UUID + manufacturer data (role); scan response: name
 * "BoxTrk-L" / "BoxTrk-R" / "BoxTrk". 3 + 18 + 10 = 31 bytes. */
static struct btrk_adv_mfg mfg;
static uint16_t dev_suffix;
static char name_buf[16];
static struct bt_data ad[] = {
	BT_DATA_BYTES(BT_DATA_FLAGS, (BT_LE_AD_GENERAL | BT_LE_AD_NO_BREDR)),
	BT_DATA_BYTES(BT_DATA_UUID128_ALL, BTRK_UUID(BTRK_UUID_SERVICE)),
	BT_DATA(BT_DATA_MANUFACTURER_DATA, &mfg, sizeof(mfg)),
};
static struct bt_data sd[] = {
	BT_DATA(BT_DATA_NAME_COMPLETE, name_buf, 0),
};
static bool adv_on;

static void build_adv(void)
{
	uint8_t fl = (session_active() ? BTRK_ADV_F_SESSION : 0) |
		     (elog_pending() ? BTRK_ADV_F_LOG_PENDING : 0) |
		     (role_window_open() ? BTRK_ADV_F_WINDOW_OPEN : 0);
	const char *nm = btrk_role_name(role_get());

	btrk_adv_mfg_fill(&mfg, role_get(), role_wrist(), fl, dev_suffix);
	if (strcmp(nm, name_buf) != 0) {
		strncpy(name_buf, nm, sizeof(name_buf) - 1);
		(void)bt_set_name(name_buf); /* GAP Device Name characteristic too */
	}
	sd[0].data_len = (uint8_t)strlen(name_buf);
}

static void adv_update_fn(struct k_work *w);
static K_WORK_DELAYABLE_DEFINE(adv_update_work, adv_update_fn);

static void adv_update_fn(struct k_work *w)
{
	build_adv();
	if (adv_on) {
		int err = bt_le_adv_update_data(ad, ARRAY_SIZE(ad), sd, ARRAY_SIZE(sd));
		if (err) {
			LOG_DBG("adv update %d", err);
		}
	}
	if (role_window_open()) { /* clear WINDOW_OPEN in the adv data when it closes */
		(void)k_work_reschedule(&adv_update_work, K_SECONDS(role_window_left_s() + 1));
	}
}

void ble_svc_update_adv(void)
{
	(void)k_work_reschedule(&adv_update_work, K_MSEC(20));
}

int ble_adv_start(bool fast)
{
	/* fast: 100-150 ms; slow: ~1 s (units of 0.625 ms) */
	const struct bt_le_adv_param *p = fast ?
		BT_LE_ADV_PARAM(BT_LE_ADV_OPT_CONN, 160, 240, NULL) :
		BT_LE_ADV_PARAM(BT_LE_ADV_OPT_CONN, 1600, 1700, NULL);

	(void)bt_le_adv_stop();
	build_adv();
	int err = bt_le_adv_start(p, ad, ARRAY_SIZE(ad), sd, ARRAY_SIZE(sd));
	if (err) {
		LOG_WRN("adv start %d", err);
	}
	adv_on = err == 0;
	if (role_window_open()) {
		(void)k_work_reschedule(&adv_update_work, K_SECONDS(role_window_left_s() + 1));
	}
	return err;
}

int ble_adv_stop(void)
{
	adv_on = false;
	return bt_le_adv_stop();
}
bool ble_connected(void) { return cur_conn != NULL; }

void ble_disconnect(void)
{
	if (cur_conn) {
		(void)bt_conn_disconnect(cur_conn, BT_HCI_ERR_REMOTE_USER_TERM_CONN);
	}
}

void ble_set_conn_profile(bool low_latency)
{
	if (!cur_conn) {
		return;
	}
	/* raw: 7.5-15 ms; events: 100-200 ms, latency 4 (units 1.25 ms / 10 ms) */
	const struct bt_le_conn_param *p = low_latency ?
		BT_LE_CONN_PARAM(6, 12, 0, 400) : BT_LE_CONN_PARAM(80, 160, 4, 600);
	(void)bt_conn_le_param_update(cur_conn, p);
}

static void connected(struct bt_conn *conn, uint8_t err)
{
	if (err) {
		return;
	}
	cur_conn = bt_conn_ref(conn);
	adv_on = false; /* connectable advertising stops on connection */
	(void)bt_conn_le_data_len_update(conn, BT_LE_DATA_LEN_PARAM_MAX);
	(void)bt_conn_le_phy_update(conn, BT_CONN_LE_PHY_PARAM_2M);
	power_event(PWR_EVT_CONNECTED);
}

static void disconnected(struct bt_conn *conn, uint8_t reason)
{
	if (cur_conn == conn) {
		bt_conn_unref(cur_conn);
		cur_conn = NULL;
	}
	atomic_set(&raw_on, 0);
	punch_ntf = sum_ntf = raw_ntf = status_ntf = ctrl_ind = log_ntf = false;
	elog_abort();
	LOG_INF("disconnected 0x%02x", reason);
}

static void security_changed(struct bt_conn *conn, bt_security_t level, enum bt_security_err err)
{
	LOG_INF("security level %u err %d bonded %d", level, err, role_link_bonded(conn));
}

static void recycled(void)
{
	/* connection object is free again: safe to restart advertising */
	power_event(PWR_EVT_DISCONNECTED);
}

BT_CONN_CB_DEFINE(conn_cbs) = {
	.connected = connected,
	.disconnected = disconnected,
	.recycled = recycled,
	.security_changed = security_changed,
};

/* ---------------- pairing (Just Works, see docs/gatt-spec.md "Security") ----------------
 * New bonds are accepted only while the pairing window is open or while the device
 * has no bonds at all; otherwise pairing requests are rejected. */
static void count_bond(const struct bt_bond_info *info, void *user)
{
	(*(int *)user)++;
}

static enum bt_security_err pairing_accept(struct bt_conn *conn,
					   const struct bt_conn_pairing_feat *const feat)
{
	int bonds = 0;

	bt_foreach_bond(BT_ID_DEFAULT, count_bond, &bonds);
	if (role_window_open() || bonds == 0) {
		return BT_SECURITY_ERR_SUCCESS;
	}
	LOG_WRN("pairing refused: window closed, %d bond(s)", bonds);
	return BT_SECURITY_ERR_PAIR_NOT_ALLOWED;
}

static void pairing_complete(struct bt_conn *conn, bool bonded)
{
	LOG_INF("paired, bonded %d", bonded);
}

static void pairing_failed(struct bt_conn *conn, enum bt_security_err reason)
{
	LOG_WRN("pairing failed %d", reason);
}

static struct bt_conn_auth_cb auth_cb = {
	.pairing_accept = pairing_accept,
};
static struct bt_conn_auth_info_cb auth_info_cb = {
	.pairing_complete = pairing_complete,
	.pairing_failed = pairing_failed,
};

int ble_svc_init(void)
{
	sample_ring_init(&ring, ring_storage, CONFIG_BTRK_RING_SAMPLES);
	uint8_t id[8] = {0};
	ssize_t n = hwinfo_get_device_id(id, sizeof(id));

	dev_suffix = n >= 2 ? (uint16_t)(id[0] | (id[1] << 8)) : 0;
	int err = bt_enable(NULL);
	if (err) {
		LOG_ERR("bt_enable %d", err);
		return err;
	}
	(void)bt_conn_auth_cb_register(&auth_cb);
	(void)bt_conn_auth_info_cb_register(&auth_info_cb);
	return 0;
}
