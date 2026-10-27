/* role.h - hand role (lead/rear + wrist), boot counter and log ACK, persisted with
 * Zephyr settings (NVS on the internal storage_partition). See docs/gatt-spec.md
 * "Hand role". */
#ifndef BTRK_ROLE_H_
#define BTRK_ROLE_H_
#include <stdbool.h>
#include <stdint.h>

struct bt_conn;

/* Register the settings handler (call before settings_load()). */
int role_settings_register(void);
/* After settings_load(): bump the boot counter, decide the pairing window. */
void role_boot(uint32_t reset_cause);

uint8_t role_get(void);
uint8_t role_wrist(void);
uint16_t role_boot_id(void);
bool role_persisted(void);
bool role_window_open(void);
uint8_t role_window_left_s(void);
/* True if conn is encrypted and its peer is in the bond list. */
bool role_link_bonded(struct bt_conn *conn);
/* Check the write policy for conn (window / bonded link / role unset). */
bool role_write_allowed(struct bt_conn *conn);
/* Set and persist (role 0 = unset clears it). -EINVAL on bad values. */
int role_set(uint8_t role, uint8_t wrist);
/* Clear role + wrist and delete all bonds. */
int role_forget(void);

uint32_t role_log_ack(void);
void role_set_log_ack(uint32_t seq);

#endif
