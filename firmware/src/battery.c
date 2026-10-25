/*
 * Battery level - STUB.
 * XIAO nRF52840: VBAT -> 1M/510k divider -> P0.31 (AIN7), divider enabled by
 * driving P0.14 LOW. TODO: add a zephyr,user io-channels node in the board
 * overlay and read it with the ADC API, sampling only every few minutes and
 * enabling the divider briefly (it drains ~2.7 uA at 4.2 V when left on).
 * Check the Seeed wiki's P0.14 caveat before driving that pin.
 * Until then we report a fixed value through the Battery Service.
 */
#include <zephyr/kernel.h>
#include <zephyr/bluetooth/services/bas.h>
#include "battery.h"

int battery_init(void)
{
	return bt_bas_set_battery_level(battery_level_pct());
}

uint8_t battery_level_pct(void)
{
	return 100; /* placeholder */
}
