#include "ringbuf.h"

#if defined(__ZEPHYR__)
#include <zephyr/sys/barrier.h>
#define RB_DMB() barrier_dmem_fence_full()
#else
#define RB_DMB() __atomic_thread_fence(__ATOMIC_SEQ_CST)
#endif

int sample_ring_init(struct sample_ring *r, struct imu_sample *storage, uint32_t capacity)
{
	if (capacity == 0 || (capacity & (capacity - 1)) != 0) {
		return -1;
	}
	r->buf = storage;
	r->mask = capacity - 1;
	r->head = r->tail = r->dropped = 0;
	return 0;
}

uint32_t sample_ring_count(const struct sample_ring *r)
{
	return r->head - r->tail;
}

bool sample_ring_put(struct sample_ring *r, const struct imu_sample *s)
{
	uint32_t head = r->head;

	if (head - r->tail > r->mask) {
		r->dropped++;
		return false;
	}
	r->buf[head & r->mask] = *s;
	RB_DMB();
	r->head = head + 1;
	return true;
}

size_t sample_ring_get(struct sample_ring *r, struct imu_sample *out, size_t max)
{
	uint32_t tail = r->tail;
	uint32_t avail = r->head - tail;
	size_t n = avail < max ? avail : max;

	RB_DMB();
	for (size_t i = 0; i < n; i++) {
		out[i] = r->buf[(tail + i) & r->mask];
	}
	RB_DMB();
	r->tail = tail + (uint32_t)n;
	return n;
}

void sample_ring_reset(struct sample_ring *r)
{
	r->tail = r->head;
}
