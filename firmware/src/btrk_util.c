#include "btrk_util.h"
#include <string.h>

uint16_t btrk_crc16(const void *data, size_t len)
{
	const uint8_t *p = data;
	uint16_t crc = 0xFFFF;

	while (len--) {
		crc ^= (uint16_t)(*p++) << 8;
		for (int i = 0; i < 8; i++) {
			crc = (crc & 0x8000) ? (uint16_t)((crc << 1) ^ 0x1021) : (uint16_t)(crc << 1);
		}
	}
	return crc;
}

static void put_le16(uint8_t *p, uint16_t v)
{
	p[0] = (uint8_t)v;
	p[1] = (uint8_t)(v >> 8);
}

void btrk_adv_mfg_fill(struct btrk_adv_mfg *m, uint8_t role, uint8_t wrist, uint8_t flags,
		       uint16_t dev_suffix)
{
	uint8_t *b = (uint8_t *)m;

	put_le16(b, BTRK_ADV_COMPANY_ID);
	b[2] = BTRK_ADV_PROTO;
	b[3] = role;
	b[4] = wrist;
	b[5] = flags;
	put_le16(b + 6, dev_suffix);
}

const char *btrk_role_name(uint8_t role)
{
	return role == BTRK_ROLE_LEAD ? "BoxTrk-L" : role == BTRK_ROLE_REAR ? "BoxTrk-R" : "BoxTrk";
}

bool btrk_role_write_allowed(uint8_t cur_role, bool window_open, bool link_bonded)
{
	return window_open || link_bonded || cur_role == BTRK_ROLE_UNSET;
}

bool btrk_window_open(bool reset_by_pin_or_power_on, uint32_t uptime_s, uint32_t window_s)
{
	return reset_by_pin_or_power_on && uptime_s < window_s;
}

uint8_t btrk_default_wrist(uint8_t role, uint8_t stance)
{
	if (role == BTRK_ROLE_UNSET) {
		return BTRK_WRIST_UNKNOWN;
	}
	bool lead = role == BTRK_ROLE_LEAD;
	bool southpaw = stance == 1;
	/* orthodox: lead = left; southpaw: lead = right */
	return (lead != southpaw) ? BTRK_WRIST_LEFT : BTRK_WRIST_RIGHT;
}

/* Typical 1-cell LiPo, light load (mV -> %); conservative at the bottom. */
static const struct { uint16_t mv; uint8_t pct; } curve[] = {
	{3300, 0}, {3500, 5}, {3600, 10}, {3700, 25}, {3750, 40}, {3800, 50},
	{3850, 60}, {3900, 70}, {4000, 80}, {4100, 92}, {4200, 100},
};

uint8_t btrk_batt_pct_from_mv(uint16_t mv)
{
	const size_t n = sizeof(curve) / sizeof(curve[0]);

	if (mv <= curve[0].mv) {
		return 0;
	}
	if (mv >= curve[n - 1].mv) {
		return 100;
	}
	for (size_t i = 1; i < n; i++) {
		if (mv < curve[i].mv) {
			uint32_t span = curve[i].mv - curve[i - 1].mv;
			uint32_t d = mv - curve[i - 1].mv;
			return (uint8_t)(curve[i - 1].pct + (d * (curve[i].pct - curve[i - 1].pct) + span / 2) / span);
		}
	}
	return 100;
}

uint16_t btrk_batt_mv_from_pin_mv(int32_t mv_pin)
{
	if (mv_pin <= 0) {
		return 0;
	}
	/* (1000k + 510k) / 510k */
	return (uint16_t)((mv_pin * 1510 + 255) / 510);
}
