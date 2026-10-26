/* btrk_util.h - small portable helpers shared by firmware and host tests (no Zephyr). */
#ifndef BTRK_UTIL_H_
#define BTRK_UTIL_H_
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include "bt_proto.h"

/* CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF), as tools/proto.py crc16. */
uint16_t btrk_crc16(const void *data, size_t len);

/* Manufacturer advertising payload (little-endian, packed). */
void btrk_adv_mfg_fill(struct btrk_adv_mfg *m, uint8_t role, uint8_t wrist, uint8_t flags,
		       uint16_t dev_suffix);

/* Device name for a role: "BoxTrk-L" (lead), "BoxTrk-R" (rear), "BoxTrk" (unset). */
const char *btrk_role_name(uint8_t role);

/* Role write policy (docs/gatt-spec.md "Hand role"): allowed while the pairing
 * window after a reset/power-on is open, on a bonded+encrypted link, or while
 * the role is still unset. */
bool btrk_role_write_allowed(uint8_t cur_role, bool window_open, bool link_bonded);
/* Pairing window: open for window_s after a pin reset or power-on (NOT after a
 * wake from System OFF, so motion in a gym bag never opens it). */
bool btrk_window_open(bool reset_by_pin_or_power_on, uint32_t uptime_s, uint32_t window_s);

/* Default wrist for a role and stance (orthodox: lead = left wrist). */
uint8_t btrk_default_wrist(uint8_t role, uint8_t stance);

/* LiPo state of charge from the cell voltage (mV), piecewise-linear 0..100 %. */
uint8_t btrk_batt_pct_from_mv(uint16_t mv);
/* XIAO divider: VBAT -> 1 M / 510 k -> AIN7. mv_pin -> mv_battery. */
uint16_t btrk_batt_mv_from_pin_mv(int32_t mv_pin);

#endif
