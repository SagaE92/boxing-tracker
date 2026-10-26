/*
 * Event log glue: evlog.c on the P25Q16H QSPI NOR (eventlog_partition, 2 MB =
 * 512 x 4 KB sectors = 65,408 records), written by one thread. The QSPI flash
 * sits in deep power-down between accesses (zephyr,pm-device-runtime-auto).
 *
 * READ transfers send records as notifications on 0x000A, floor((MTU-3)/32)
 * records per notification, terminated by an END record (type 0xFE) carrying
 * {u32 records_sent, u32 device_next_seq}. See docs/gatt-spec.md "Event log".
 */
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <zephyr/storage/flash_map.h>
#include <zephyr/sys/byteorder.h>
#include <string.h>

#include "event_log.h"
#include "evlog.h"
#include "ble_svc.h"
#include "role.h"

LOG_MODULE_REGISTER(evlog, CONFIG_BTRK_LOG_LEVEL);

#define LOG_PART FIXED_PARTITION_ID(eventlog_partition)

struct append_item {
	uint8_t type; /* 0 = wake-up only */
	uint8_t len;
	uint8_t payload[22];
};

K_MSGQ_DEFINE(append_q, sizeof(struct append_item), 32, 4);
static K_MUTEX_DEFINE(lock);
static K_SEM_DEFINE(idle_sem, 0, 1);

static const struct flash_area *fa;
static struct evlog lg;
static struct evlog_ops ops;
static bool ready;

static struct {
	bool active;
	bool abort;
	bool erase;
	uint32_t from, max, sent;
	struct evlog_iter it;
} xfer;

static int fa_read(void *c, uint32_t off, void *b, size_t n) { return flash_area_read(c, off, b, n); }
static int fa_write(void *c, uint32_t off, const void *b, size_t n) { return flash_area_write(c, off, b, n); }
static int fa_erase(void *c, uint32_t off, uint32_t n) { return flash_area_erase(c, off, n); }

int elog_init(uint16_t boot_id)
{
	int err = flash_area_open(LOG_PART, &fa);

	if (err) {
		LOG_ERR("eventlog partition: %d", err);
		return err;
	}
	if (!flash_area_device_is_ready(fa)) {
		LOG_ERR("QSPI flash not ready");
		return -ENODEV;
	}
	ops = (struct evlog_ops){fa_read, fa_write, fa_erase, (void *)fa, (uint32_t)fa->fa_size, 4096};
	k_mutex_lock(&lock, K_FOREVER);
	err = evlog_mount(&lg, &ops);
	lg.boot_id = boot_id;
	ready = err == 0;
	k_mutex_unlock(&lock);
	LOG_INF("event log: %d, seq %u..%u, cap %u", err, evlog_first_seq(&lg), lg.next_seq,
		evlog_capacity(&lg));
	return err;
}

bool elog_ready(void) { return ready; }

int elog_append(uint8_t type, const void *payload, size_t len)
{
	struct append_item it = {.type = type, .len = (uint8_t)len};

	if (!ready) {
		return -ENODEV;
	}
	if (len > sizeof(it.payload) || type == 0) {
		return -EINVAL;
	}
	memcpy(it.payload, payload, len);
	return k_msgq_put(&append_q, &it, K_NO_WAIT);
}

static void wake(void)
{
	struct append_item it = {0};

	(void)k_msgq_put(&append_q, &it, K_NO_WAIT);
}

uint32_t elog_next_seq(void) { return lg.next_seq; }

bool elog_pending(void)
{
	return ready && lg.next_seq > MAX(role_log_ack(), evlog_first_seq(&lg));
}

void elog_info(struct btrk_log_info *out)
{
	k_mutex_lock(&lock, K_FOREVER);
	out->first_seq = ready ? evlog_first_seq(&lg) : 0;
	out->next_seq = ready ? lg.next_seq : 0;
	out->capacity = ready ? evlog_capacity(&lg) : 0;
	out->boot_id = role_boot_id();
	out->rec_size = BTRK_LOG_REC_SIZE;
	out->flags = (xfer.active ? 0x01 : 0) | (ready ? 0 : 0x80);
	k_mutex_unlock(&lock);
}

uint8_t elog_op(const uint8_t *p, uint16_t len)
{
	uint8_t st = BTRK_ST_OK;

	if (!ready) {
		return BTRK_ST_BAD_STATE;
	}
	k_mutex_lock(&lock, K_FOREVER);
	switch (p[0]) {
	case BTRK_LOG_OP_READ:
		if (len != 9) {
			st = BTRK_ST_INVALID_PARAM;
		} else if (xfer.active) {
			st = BTRK_ST_BAD_STATE;
		} else {
			xfer.from = sys_get_le32(p + 1);
			xfer.max = sys_get_le32(p + 5);
			xfer.sent = 0;
			xfer.abort = false;
			evlog_iter_start(&lg, &xfer.it, xfer.from);
			xfer.active = true;
		}
		break;
	case BTRK_LOG_OP_ABORT:
		xfer.abort = true;
		break;
	case BTRK_LOG_OP_ERASE:
		if (len != 5 || sys_get_le32(p + 1) != BTRK_LOG_ERASE_MAGIC) {
			st = BTRK_ST_INVALID_PARAM;
		} else if (xfer.active) {
			st = BTRK_ST_BAD_STATE;
		} else {
			xfer.erase = true;
		}
		break;
	case BTRK_LOG_OP_ACK:
		if (len != 5) {
			st = BTRK_ST_INVALID_PARAM;
		} else {
			role_set_log_ack(MIN(sys_get_le32(p + 1), lg.next_seq));
		}
		break;
	default:
		st = BTRK_ST_UNSUPPORTED;
	}
	k_mutex_unlock(&lock);
	wake();
	return st;
}

void elog_abort(void)
{
	xfer.abort = true;
	wake();
}

int elog_flush(k_timeout_t timeout)
{
	if (!ready) {
		return 0;
	}
	k_sem_reset(&idle_sem);
	wake();
	return k_sem_take(&idle_sem, timeout);
}

static void write_one(const struct append_item *it)
{
	int err;

	k_mutex_lock(&lock, K_FOREVER);
	err = evlog_append(&lg, it->type, it->payload, it->len, NULL);
	k_mutex_unlock(&lock);
	if (err) {
		LOG_WRN("append type %u: %d", it->type, err);
	}
}

/* One transfer step: up to floor((MTU-3)/32) records in one notification. */
static void xfer_step(void)
{
	static uint8_t buf[7 * BTRK_LOG_REC_SIZE];
	struct btrk_log_rec *r = (struct btrk_log_rec *)buf;
	size_t room = ble_svc_log_room() / BTRK_LOG_REC_SIZE;
	size_t n = 0;
	bool end = false;

	room = MIN(room, ARRAY_SIZE(buf) / BTRK_LOG_REC_SIZE);
	if (room == 0 || xfer.abort) {
		xfer.active = false;
		return;
	}
	k_mutex_lock(&lock, K_FOREVER);
	while (n < room) {
		if (xfer.max && xfer.sent >= xfer.max) {
			end = true;
			break;
		}
		int rc = evlog_iter_next(&lg, &xfer.it, &r[n]);
		if (rc != 1) {
			end = true;
			break;
		}
		n++;
		xfer.sent++;
	}
	if (end && n < room) {
		struct btrk_log_rec *e = &r[n++];
		memset(e, 0, sizeof(*e));
		e->type = BTRK_LOG_END;
		e->boot_id = lg.boot_id;
		e->seq = n > 1 ? r[n - 2].seq + 1 : xfer.from;
		sys_put_le32(xfer.sent, e->payload);
		sys_put_le32(lg.next_seq, e->payload + 4);
		evlog_rec_seal(e);
		xfer.active = false;
	}
	k_mutex_unlock(&lock);
	if (n && ble_svc_log_send(buf, n * BTRK_LOG_REC_SIZE)) {
		xfer.active = false; /* disconnected / notifications off */
	}
}

static void log_thread(void *a, void *b, void *c)
{
	struct append_item it;

	for (;;) {
		bool busy = xfer.active || xfer.erase;
		if (k_msgq_get(&append_q, &it, busy ? K_NO_WAIT : K_FOREVER) == 0) {
			if (it.type) {
				write_one(&it);
			}
			continue; /* drain appends first */
		}
		if (xfer.erase) {
			k_mutex_lock(&lock, K_FOREVER);
			LOG_INF("erasing event log");
			int err = evlog_erase_all(&lg);
			xfer.erase = false;
			k_mutex_unlock(&lock);
			LOG_INF("erase done: %d", err);
			ble_svc_update_adv();
		} else if (xfer.active) {
			xfer_step();
		}
		if (!xfer.active && !xfer.erase && k_msgq_num_used_get(&append_q) == 0) {
			k_sem_give(&idle_sem);
		}
	}
}
K_THREAD_DEFINE(log_tid, 1536, log_thread, NULL, NULL, NULL, 8, 0, 0);
