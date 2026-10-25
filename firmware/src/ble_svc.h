/* ble_svc.h - Boxing Tracker GATT service (layout in bt_proto.h / docs/gatt-spec.md) */
#ifndef BTRK_BLE_SVC_H_
#define BTRK_BLE_SVC_H_
#include <stdbool.h>
#include <stddef.h>
#include "bt_proto.h"
#include "imu_sample.h"

int ble_svc_init(void);
int ble_adv_start(bool fast);
int ble_adv_stop(void);
bool ble_connected(void);
void ble_disconnect(void);
/* Prefer low-power connection params (punch events) or low latency (raw). */
void ble_set_conn_profile(bool low_latency);

void ble_svc_notify_punch(const struct btrk_punch_evt *ev);
void ble_svc_notify_summary(void);
void ble_svc_notify_status(void);
bool ble_raw_streaming(void);
/* IMU thread: push raw samples (only when raw streaming is enabled). */
void ble_raw_push(const struct imu_sample *s, size_t n, uint8_t imu_flags);

#endif
