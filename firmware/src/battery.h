#ifndef BTRK_BATTERY_H_
#define BTRK_BATTERY_H_
#include <stdint.h>
int battery_init(void);
/* Returns state of charge 0..100 (estimate). */
uint8_t battery_level_pct(void);
#endif
