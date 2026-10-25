/* raw_pack.h - pack samples into a raw-stream notification (docs/gatt-spec.md) */
#ifndef BTRK_RAW_PACK_H_
#define BTRK_RAW_PACK_H_
#include <stddef.h>
#include <stdint.h>
#include "imu_sample.h"
#include "bt_proto.h"

/* Max samples that fit in one notification for a given ATT MTU (0 if MTU too small). */
size_t btrk_raw_samples_for_mtu(uint16_t mtu);

/* Sample saturation helpers (|raw| >= BTRK_*_SAT_RAW on any axis). */
int btrk_accel_saturated(const struct imu_sample *s);
int btrk_gyro_saturated(const struct imu_sample *s);

/* Pack n (1..BTRK_RAW_MAX_SAMPLES) samples into buf. Returns bytes written, 0 on error. */
size_t btrk_raw_pack(uint8_t *buf, size_t cap, const struct imu_sample *s, size_t n,
		     uint16_t seq, uint8_t flags);

#endif
