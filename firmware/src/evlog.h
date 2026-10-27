/* evlog.h - append-only ring log of fixed 32-byte records on NOR flash (portable C).
 *
 * Layout: the area is split into erase sectors; each holds sector_size / 32
 * records (struct btrk_log_rec, CRC-16 protected). Records are programmed once
 * (NOR: 1 -> 0 only); an erased slot reads 0xFF. Sequence numbers are global
 * and monotonic (they survive ERASE: the first record after an erase is an
 * ERASED marker that continues the sequence). When the ring is full the oldest
 * sector is erased. A torn write (power loss) leaves a slot with a bad CRC: it is
 * skipped by readers and never reused. Mount = read each sector's first record
 * (to find the newest sector) + scan that sector for the first free slot.
 *
 * Flash access goes through evlog_ops so the same code runs on the device (Zephyr
 * flash_area on the QSPI NOR, see log.c) and in the host tests (RAM-backed NOR).
 */
#ifndef BTRK_EVLOG_H_
#define BTRK_EVLOG_H_
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include "bt_proto.h"

#define EVLOG_MAX_SECT 512           /* 2 MB / 4 KB                     */
#define EVLOG_NONE     0xFFFFFFFFu   /* sector empty                    */

struct evlog_ops {
	int (*read)(void *ctx, uint32_t off, void *buf, size_t len);
	int (*write)(void *ctx, uint32_t off, const void *buf, size_t len);
	int (*erase)(void *ctx, uint32_t off, uint32_t len);
	void *ctx;
	uint32_t size;        /* bytes, multiple of sector_size */
	uint32_t sector_size; /* erase unit, multiple of 32      */
};

struct evlog {
	const struct evlog_ops *ops;
	uint32_t nsect, per_sect;
	uint32_t first[EVLOG_MAX_SECT]; /* first valid seq per sector or EVLOG_NONE */
	uint32_t head, slot;            /* next write position                      */
	uint32_t next_seq;
	uint16_t boot_id;               /* stamped into appended records            */
};

struct evlog_iter {
	uint32_t from_seq;
	uint32_t k;     /* sector number in ring order, 0 = oldest */
	uint32_t slot;
	bool done;
};

int evlog_mount(struct evlog *l, const struct evlog_ops *ops);
/* Append one record (payload up to 22 bytes, zero padded). *seq_out may be NULL. */
int evlog_append(struct evlog *l, uint8_t type, const void *payload, size_t len, uint32_t *seq_out);
int evlog_erase_all(struct evlog *l);
uint32_t evlog_first_seq(const struct evlog *l);
uint32_t evlog_capacity(const struct evlog *l);
bool evlog_rec_valid(const struct btrk_log_rec *r);
void evlog_rec_seal(struct btrk_log_rec *r); /* compute the CRC */

/* Iterate records with seq >= from_seq, oldest first. next(): 1 = record, 0 = end. */
void evlog_iter_start(const struct evlog *l, struct evlog_iter *it, uint32_t from_seq);
int evlog_iter_next(const struct evlog *l, struct evlog_iter *it, struct btrk_log_rec *out);

#endif
