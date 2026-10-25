#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <zephyr/bluetooth/bluetooth.h>
#include <zephyr/bluetooth/conn.h>
#include <zephyr/bluetooth/gatt.h>
#include <zephyr/bluetooth/uuid.h>
#include <zephyr/bluetooth/services/bas.h>
#include <zephyr/sys/byteorder.h>
#include <string.h>

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

static struct bt_conn *cur_conn;
static atomic_t raw_on;
static bool punch_ntf, sum_ntf, raw_ntf, status_ntf, ctrl_ind;
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
	if (session_set_config(&cfg)) {
		return BT_GATT_ERR(BT_ATT_ERR_VALUE_NOT_ALLOWED);
	}
	return len;
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
);

#define ATTR_PUNCH  (&btrk_svc.attrs[2])
#define ATTR_CTRL   (&btrk_svc.attrs[5])
#define ATTR_SUM    (&btrk_svc.attrs[8])
#define ATTR_RAW    (&btrk_svc.attrs[11])
#define ATTR_STATUS (&btrk_svc.attrs[16])

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
	/* TODO(CONFIG_BTRK_SESSION_STORAGE): append to flash log when disconnected */
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

static const struct bt_data ad[] = {
	BT_DATA_BYTES(BT_DATA_FLAGS, (BT_LE_AD_GENERAL | BT_LE_AD_NO_BREDR)),
	BT_DATA_BYTES(BT_DATA_UUID128_ALL, BTRK_UUID(BTRK_UUID_SERVICE)),
};
static const struct bt_data sd[] = {
	BT_DATA(BT_DATA_NAME_COMPLETE, CONFIG_BT_DEVICE_NAME, sizeof(CONFIG_BT_DEVICE_NAME) - 1),
};

int ble_adv_start(bool fast)
{
	/* fast: 100-150 ms; slow: ~1 s (units of 0.625 ms) */
	const struct bt_le_adv_param *p = fast ?
		BT_LE_ADV_PARAM(BT_LE_ADV_OPT_CONN, 160, 240, NULL) :
		BT_LE_ADV_PARAM(BT_LE_ADV_OPT_CONN, 1600, 1700, NULL);

	(void)bt_le_adv_stop();
	int err = bt_le_adv_start(p, ad, ARRAY_SIZE(ad), sd, ARRAY_SIZE(sd));
	if (err) {
		LOG_WRN("adv start %d", err);
	}
	return err;
}

int ble_adv_stop(void) { return bt_le_adv_stop(); }
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
	LOG_INF("disconnected 0x%02x", reason);
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
};

int ble_svc_init(void)
{
	sample_ring_init(&ring, ring_storage, CONFIG_BTRK_RING_SAMPLES);
	int err = bt_enable(NULL);
	if (err) {
		LOG_ERR("bt_enable %d", err);
	}
	return err;
}
