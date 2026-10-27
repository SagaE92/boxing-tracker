/* event_log.h - on-device event log (evlog ring on the QSPI NOR) + GATT transfer.
 * Appends are queued from any thread and written by the log thread. */
#ifndef BTRK_EVENT_LOG_H_
#define BTRK_EVENT_LOG_H_
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <zephyr/kernel.h>
#include "bt_proto.h"

int elog_init(uint16_t boot_id);
bool elog_ready(void);
/* Queue a record (non-blocking). -ENOMSG if the queue is full, -ENODEV if no flash. */
int elog_append(uint8_t type, const void *payload, size_t len);
void elog_info(struct btrk_log_info *out);
uint32_t elog_next_seq(void);
/* Records exist that the host has not ACKed. */
bool elog_pending(void);
/* GATT 0x000A control ops (return BTRK_ST_*) */
uint8_t elog_op(const uint8_t *p, uint16_t len);
/* Called on disconnect: stop any transfer. */
void elog_abort(void);
/* Wait until queued appends are on flash (before System OFF). */
int elog_flush(k_timeout_t timeout);

#endif
