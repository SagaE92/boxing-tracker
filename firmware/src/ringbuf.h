/* ringbuf.h - lock-free single-producer/single-consumer sample ring (portable C).
 * Producer: IMU thread. Consumer: BLE raw-stream thread. On overflow the
 * producer drops the NEW sample and counts it (consumer never sees torn data). */
#ifndef BTRK_RINGBUF_H_
#define BTRK_RINGBUF_H_
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include "imu_sample.h"

struct sample_ring {
	struct imu_sample *buf;
	uint32_t mask;           /* capacity - 1, capacity is a power of two */
	volatile uint32_t head;  /* written by producer */
	volatile uint32_t tail;  /* written by consumer */
	volatile uint32_t dropped;
};

int sample_ring_init(struct sample_ring *r, struct imu_sample *storage, uint32_t capacity);
bool sample_ring_put(struct sample_ring *r, const struct imu_sample *s);
size_t sample_ring_get(struct sample_ring *r, struct imu_sample *out, size_t max);
uint32_t sample_ring_count(const struct sample_ring *r);
void sample_ring_reset(struct sample_ring *r);

#endif
