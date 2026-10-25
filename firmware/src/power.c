/*
 * Power state machine. No button: the only wake source is IMU motion.
 *
 *   System OFF --(IMU wake-up INT1, GPIO SENSE)--> reset/boot
 *   BOOT -> ADV_FAST (CONFIG_BTRK_ADV_FAST_TIMEOUT_S) -> ADV_SLOW
 *   ADV_* --(no connection for CONFIG_BTRK_ADV_TIMEOUT_S)--> System OFF
 *   ADV_* --connect--> CONNECTED --(idle CONFIG_BTRK_CONN_IDLE_TIMEOUT_S)--> disconnect -> ADV_SLOW
 *   CONNECTED --session start--> SESSION (IMU 416 Hz, detector)
 *   SESSION --(no strike for CONFIG_BTRK_SESSION_IDLE_TIMEOUT_S)--> session stop
 *   SESSION survives disconnects (advertises slowly to reconnect); events are
 *   lost while disconnected until CONFIG_BTRK_SESSION_STORAGE is implemented.
 *
 * The IMU runs only in SESSION (or raw mode); otherwise it is powered down
 * (~3 uA) or, in System OFF, in 12.5 Hz low-power wake-up mode (~9 uA).
 */
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <zephyr/sys/poweroff.h>

#include "power.h"
#include "ble_svc.h"
#include "imu_lsm6ds3trc.h"
#include "session.h"

LOG_MODULE_REGISTER(power, CONFIG_BTRK_LOG_LEVEL);

static enum pwr_state state = PWR_ST_BOOT;
static int64_t adv_started_ms;
static bool raw_mode;

static void sm_work_fn(struct k_work *w);
static void timeout_fn(struct k_work *w);
static K_WORK_DELAYABLE_DEFINE(timeout_work, timeout_fn);

/* small event queue processed on the system workqueue */
K_MSGQ_DEFINE(evt_q, sizeof(uint8_t), 16, 1);
static K_WORK_DEFINE(sm_work, sm_work_fn);

enum pwr_state power_state_get(void) { return state; }

static void arm_timeout(uint32_t seconds)
{
	k_work_reschedule(&timeout_work, K_SECONDS(seconds));
}

static void enter(enum pwr_state ns)
{
	LOG_INF("power %d -> %d", state, ns);
	state = ns;
	switch (ns) {
	case PWR_ST_ADV_FAST:
		imu_stop();
		adv_started_ms = k_uptime_get();
		ble_adv_start(true);
		arm_timeout(CONFIG_BTRK_ADV_FAST_TIMEOUT_S);
		break;
	case PWR_ST_ADV_SLOW:
		if (!session_active()) {
			imu_stop();
		}
		ble_adv_start(false);
		arm_timeout(session_active() ? CONFIG_BTRK_SESSION_IDLE_TIMEOUT_S :
			    MAX(1, CONFIG_BTRK_ADV_TIMEOUT_S - CONFIG_BTRK_ADV_FAST_TIMEOUT_S));
		break;
	case PWR_ST_CONNECTED:
		if (!raw_mode) {
			imu_stop();
		}
		ble_set_conn_profile(raw_mode);
		arm_timeout(CONFIG_BTRK_CONN_IDLE_TIMEOUT_S);
		break;
	case PWR_ST_SESSION:
		imu_start();
		ble_set_conn_profile(raw_mode);
		arm_timeout(CONFIG_BTRK_SESSION_IDLE_TIMEOUT_S);
		break;
	case PWR_ST_OFF:
		k_work_cancel_delayable(&timeout_work);
		ble_adv_stop();
		ble_disconnect();
		if (imu_arm_wake_on_motion(CONFIG_BTRK_WOM_THRESHOLD_MG) == 0 &&
		    imu_configure_wake_pin() == 0) {
			LOG_INF("System OFF (wake on motion)");
			k_msleep(50); /* flush logs */
			sys_poweroff();
		}
		LOG_ERR("could not arm wake-on-motion; staying on (slow adv)");
		state = PWR_ST_ADV_SLOW;
		ble_adv_start(false);
		break;
	default:
		break;
	}
}

static void handle(enum pwr_event e)
{
	switch (e) {
	case PWR_EVT_CONNECTED:
		enter(session_active() ? PWR_ST_SESSION : PWR_ST_CONNECTED);
		break;
	case PWR_EVT_DISCONNECTED:
		raw_mode = false;
		enter(PWR_ST_ADV_SLOW);
		break;
	case PWR_EVT_SESSION_START:
		enter(PWR_ST_SESSION);
		break;
	case PWR_EVT_SESSION_STOP:
		enter(ble_connected() ? PWR_ST_CONNECTED : PWR_ST_ADV_SLOW);
		break;
	case PWR_EVT_RAW_START:
		raw_mode = true;
		imu_start();
		ble_set_conn_profile(true);
		break;
	case PWR_EVT_RAW_STOP:
		raw_mode = false;
		if (!session_active()) {
			imu_stop();
		}
		ble_set_conn_profile(false);
		break;
	case PWR_EVT_ACTIVITY:
		if (state == PWR_ST_SESSION || session_active()) {
			arm_timeout(CONFIG_BTRK_SESSION_IDLE_TIMEOUT_S);
		}
		break;
	case PWR_EVT_OFF_REQUEST:
		if (session_active()) {
			session_stop();
		}
		enter(PWR_ST_OFF);
		break;
	case PWR_EVT_TIMEOUT:
		switch (state) {
		case PWR_ST_ADV_FAST:
			enter(PWR_ST_ADV_SLOW);
			break;
		case PWR_ST_ADV_SLOW:
			if (session_active()) {
				session_stop(); /* idle session while disconnected */
			} else {
				enter(PWR_ST_OFF);
			}
			break;
		case PWR_ST_CONNECTED:
			if (raw_mode) {
				arm_timeout(CONFIG_BTRK_CONN_IDLE_TIMEOUT_S);
			} else {
				ble_disconnect(); /* -> DISCONNECTED -> ADV_SLOW -> OFF */
			}
			break;
		case PWR_ST_SESSION:
			LOG_INF("session idle timeout");
			session_stop();
			break;
		default:
			break;
		}
		break;
	}
}

static void sm_work_fn(struct k_work *w)
{
	uint8_t e;

	while (k_msgq_get(&evt_q, &e, K_NO_WAIT) == 0) {
		handle((enum pwr_event)e);
	}
}

static void timeout_fn(struct k_work *w)
{
	handle(PWR_EVT_TIMEOUT);
}

void power_event(enum pwr_event evt)
{
	uint8_t e = (uint8_t)evt;

	if (k_msgq_put(&evt_q, &e, K_NO_WAIT) == 0) {
		k_work_submit(&sm_work);
	}
}

void power_init(void)
{
	enter(PWR_ST_ADV_FAST);
}
