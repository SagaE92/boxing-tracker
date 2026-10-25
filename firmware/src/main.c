/*
 * Boxing Tracker firmware - main.
 * Board-specific config lives in the boards/ overlays; see README.md.
 */
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <zephyr/drivers/hwinfo.h>

#include "battery.h"
#include "ble_svc.h"
#include "imu_lsm6ds3trc.h"
#include "power.h"
#include "session.h"

LOG_MODULE_REGISTER(main, CONFIG_BTRK_LOG_LEVEL);

/* IMU thread callback: feed the on-device detector and the raw stream. */
static void on_imu_batch(const struct imu_sample *s, size_t n, uint8_t flags)
{
	session_on_samples(s, n);
	ble_raw_push(s, n, flags);
}

int main(void)
{
	uint32_t cause = 0;

	(void)hwinfo_get_reset_cause(&cause);
	(void)hwinfo_clear_reset_cause();
	LOG_INF("boot, reset cause 0x%08x (wake from System OFF via IMU = GPIO/OFF)", cause);

	session_init();
	if (imu_init(on_imu_batch)) {
		LOG_ERR("IMU init failed");
	}
	if (ble_svc_init()) {
		return 0;
	}
	(void)battery_init();
	/* MCUmgr SMP-over-BLE service is registered automatically
	 * (CONFIG_MCUMGR_TRANSPORT_BT); OTA images are swapped by MCUboot. */
	power_init();
	return 0;
}
