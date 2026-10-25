/* power.h - power state machine (docs/power.md) */
#ifndef BTRK_POWER_H_
#define BTRK_POWER_H_

enum pwr_state {
	PWR_ST_BOOT = 0,
	PWR_ST_ADV_FAST = 1,    /* just woke: fast advertising            */
	PWR_ST_ADV_SLOW = 2,    /* ~1 s advertising, IMU powered down     */
	PWR_ST_CONNECTED = 3,   /* connected, no session, IMU powered down */
	PWR_ST_SESSION = 4,     /* IMU 416 Hz + detector (+ raw if enabled) */
	PWR_ST_OFF = 5,         /* System OFF, IMU wake-on-motion armed    */
};

enum pwr_event {
	PWR_EVT_CONNECTED,
	PWR_EVT_DISCONNECTED,
	PWR_EVT_SESSION_START,
	PWR_EVT_SESSION_STOP,
	PWR_EVT_RAW_START,
	PWR_EVT_RAW_STOP,
	PWR_EVT_ACTIVITY,       /* a strike was detected */
	PWR_EVT_OFF_REQUEST,
	PWR_EVT_TIMEOUT,        /* internal */
};

void power_init(void);
void power_event(enum pwr_event evt);
enum pwr_state power_state_get(void);

#endif
