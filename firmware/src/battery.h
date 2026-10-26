#ifndef BTRK_BATTERY_H_
#define BTRK_BATTERY_H_
#include <stdint.h>
/* Battery level via the XIAO VBAT divider (AIN7), published through the
 * Battery Service. Samples every CONFIG_BTRK_BATTERY_PERIOD_S and on request. */
int battery_init(void);
/* Returns state of charge 0..100 (estimate from the cell voltage). */
uint8_t battery_level_pct(void);
/* Last measured cell voltage in mV (0 = not measured / ADC unavailable). */
uint16_t battery_mv(void);
/* Take a fresh sample soon (e.g. on connect). */
void battery_sample_soon(void);
#endif
