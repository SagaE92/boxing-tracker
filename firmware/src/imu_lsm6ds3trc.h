/* imu_lsm6ds3trc.h - LSM6DS3TR-C FIFO driver (raw register access over I2C) */
#ifndef BTRK_IMU_H_
#define BTRK_IMU_H_
#include <stddef.h>
#include <stdint.h>
#include "imu_sample.h"

#define IMU_ODR_HZ 416
#define IMU_FLAG_FIFO_OVERRUN 0x01
#define IMU_FLAG_TS_RESYNC    0x02

/* Called from the IMU thread for each batch read from the FIFO. */
typedef void (*imu_batch_cb_t)(const struct imu_sample *s, size_t n, uint8_t flags);

int imu_init(imu_batch_cb_t cb);
/* Streaming: accel +-16 g, gyro +-2000 dps, 416 Hz, FIFO continuous + watermark IRQ */
int imu_start(void);
/* Power-down both sensors (~3 uA, datasheet IddPD) */
int imu_stop(void);
/* Accel-only 12.5 Hz low-power + latched wake-up on INT1, then the caller enters System OFF */
int imu_arm_wake_on_motion(uint16_t threshold_mg);
/* Configure INT1 as nRF System OFF wake source (GPIO SENSE, level high). */
int imu_configure_wake_pin(void);

#endif
