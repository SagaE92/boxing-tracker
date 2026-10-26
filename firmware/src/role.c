#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <zephyr/settings/settings.h>
#include <zephyr/drivers/hwinfo.h>
#include <zephyr/bluetooth/bluetooth.h>
#include <zephyr/bluetooth/conn.h>
#include <string.h>

#include "role.h"
#include "btrk_util.h"

LOG_MODULE_REGISTER(role, CONFIG_BTRK_LOG_LEVEL);

static struct {
	uint8_t role, wrist;
	uint16_t boot_id;
	uint32_t ack;
	bool persisted;
	bool window_from_reset;
} r;

static int set_cb(const char *key, size_t len, settings_read_cb read_cb, void *cb_arg)
{
	const char *next;
	void *dst = NULL;
	size_t want = 0;

	if (settings_name_steq(key, "role", &next) && !next) {
		dst = &r.role, want = sizeof(r.role);
	} else if (settings_name_steq(key, "wrist", &next) && !next) {
		dst = &r.wrist, want = sizeof(r.wrist);
	} else if (settings_name_steq(key, "boot", &next) && !next) {
		dst = &r.boot_id, want = sizeof(r.boot_id);
	} else if (settings_name_steq(key, "ack", &next) && !next) {
		dst = &r.ack, want = sizeof(r.ack);
	} else {
		return -ENOENT;
	}
	if (len != want) {
		return -EINVAL;
	}
	int n = read_cb(cb_arg, dst, want);
	if (n < 0) {
		return n;
	}
	if (dst == &r.role) {
		r.persisted = true;
	}
	return 0;
}

static struct settings_handler handler = {.name = "btrk", .h_set = set_cb};

int role_settings_register(void)
{
	return settings_register(&handler);
}

void role_boot(uint32_t cause)
{
	if (r.role > BTRK_ROLE_REAR) {
		r.role = BTRK_ROLE_UNSET;
	}
	if (r.wrist > BTRK_WRIST_RIGHT) {
		r.wrist = BTRK_WRIST_UNKNOWN;
	}
	r.boot_id++;
	(void)settings_save_one("btrk/boot", &r.boot_id, sizeof(r.boot_id));
	/* Pairing window after a deliberate reset (RESET tap, UF2/OTA reset) or a
	 * fresh power-on (battery connected), but NOT after a wake from System OFF
	 * (motion in a gym bag): that reports RESET_LOW_POWER_WAKE (nRF RESETREAS.OFF).
	 * A plain power-on reports no bits on nRF52. Watchdog / lockup resets do not
	 * open it either. (The UF2 bootloader runs before us on every reset; if it
	 * ever cleared RESETREAS, a wake would look like a power-on and open the
	 * window - see docs/bringup.md troubleshooting.) */
	bool pin_or_por = !(cause & (RESET_LOW_POWER_WAKE | RESET_WATCHDOG | RESET_CPU_LOCKUP));
	r.window_from_reset = pin_or_por;
	LOG_INF("boot %u role %u wrist %u window %s", r.boot_id, r.role, r.wrist,
		pin_or_por ? "open" : "closed");
}

uint8_t role_get(void) { return r.role; }
uint8_t role_wrist(void) { return r.wrist; }
uint16_t role_boot_id(void) { return r.boot_id; }
bool role_persisted(void) { return r.persisted; }

bool role_window_open(void)
{
	return btrk_window_open(r.window_from_reset, (uint32_t)(k_uptime_get() / 1000),
				CONFIG_BTRK_ROLE_WINDOW_S);
}

uint8_t role_window_left_s(void)
{
	if (!role_window_open()) {
		return 0;
	}
	int64_t left = CONFIG_BTRK_ROLE_WINDOW_S - k_uptime_get() / 1000;
	return (uint8_t)CLAMP(left, 0, 255);
}

struct bond_q {
	const bt_addr_le_t *dst;
	bool found;
};

static void bond_cb(const struct bt_bond_info *info, void *user)
{
	struct bond_q *q = user;

	if (bt_addr_le_eq(&info->addr, q->dst)) {
		q->found = true;
	}
}

bool role_link_bonded(struct bt_conn *conn)
{
	struct bt_conn_info info;

	if (!conn || bt_conn_get_info(conn, &info) || bt_conn_get_security(conn) < BT_SECURITY_L2) {
		return false;
	}
	struct bond_q q = {.dst = info.le.dst, .found = false};
	bt_foreach_bond(BT_ID_DEFAULT, bond_cb, &q);
	return q.found;
}

bool role_write_allowed(struct bt_conn *conn)
{
	return btrk_role_write_allowed(r.role, role_window_open(), role_link_bonded(conn));
}

int role_set(uint8_t role, uint8_t wrist)
{
	if (role > BTRK_ROLE_REAR || wrist > BTRK_WRIST_RIGHT) {
		return -EINVAL;
	}
	if (role == BTRK_ROLE_UNSET) {
		wrist = BTRK_WRIST_UNKNOWN;
	}
	r.role = role;
	r.wrist = wrist;
	int err = settings_save_one("btrk/role", &r.role, sizeof(r.role));
	if (!err) {
		err = settings_save_one("btrk/wrist", &r.wrist, sizeof(r.wrist));
	}
	r.persisted = err == 0;
	LOG_INF("role %u wrist %u saved (%d)", role, wrist, err);
	return err;
}

int role_forget(void)
{
	int err = role_set(BTRK_ROLE_UNSET, BTRK_WRIST_UNKNOWN);
	int e2 = bt_unpair(BT_ID_DEFAULT, BT_ADDR_LE_ANY);

	return err ? err : e2;
}

uint32_t role_log_ack(void) { return r.ack; }

void role_set_log_ack(uint32_t seq)
{
	if (seq > r.ack) {
		r.ack = seq;
		(void)settings_save_one("btrk/ack", &r.ack, sizeof(r.ack));
	}
}
