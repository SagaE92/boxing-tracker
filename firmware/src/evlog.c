#include "evlog.h"
#include "btrk_util.h"
#include <errno.h>
#include <string.h>

#define RS BTRK_LOG_REC_SIZE

static uint32_t off_of(const struct evlog *l, uint32_t sect, uint32_t slot)
{
	return sect * l->ops->sector_size + slot * RS;
}

static int rd(const struct evlog *l, uint32_t sect, uint32_t slot, struct btrk_log_rec *r)
{
	return l->ops->read(l->ops->ctx, off_of(l, sect, slot), r, RS);
}

void evlog_rec_seal(struct btrk_log_rec *r)
{
	r->crc = btrk_crc16(r, offsetof(struct btrk_log_rec, crc));
}

bool evlog_rec_valid(const struct btrk_log_rec *r)
{
	return r->type != BTRK_LOG_EMPTY && r->crc == btrk_crc16(r, offsetof(struct btrk_log_rec, crc));
}

int evlog_mount(struct evlog *l, const struct evlog_ops *ops)
{
	struct btrk_log_rec r;
	uint32_t best = 0;
	bool any = false;

	l->ops = ops;
	l->per_sect = ops->sector_size / RS;
	l->nsect = ops->size / ops->sector_size;
	if (l->nsect < 2 || l->nsect > EVLOG_MAX_SECT || l->per_sect == 0) {
		return -EINVAL;
	}
	l->head = 0;
	l->slot = 0;
	l->next_seq = 1;
	for (uint32_t s = 0; s < l->nsect; s++) {
		l->first[s] = EVLOG_NONE;
		for (uint32_t k = 0; k < l->per_sect; k++) {
			int err = rd(l, s, k, &r);
			if (err) {
				return err;
			}
			if (r.type == BTRK_LOG_EMPTY) {
				break; /* erased slot: rest of the sector is free */
			}
			if (evlog_rec_valid(&r)) {
				l->first[s] = r.seq;
				break;
			}
			l->first[s] = 0; /* used but only torn records so far: keep looking */
		}
		if (l->first[s] != EVLOG_NONE && (!any || l->first[s] > best)) {
			best = l->first[s];
			l->head = s;
			any = true;
		}
	}
	if (!any) {
		return 0;
	}
	/* scan the newest sector for the first free slot and the last seq */
	uint32_t last = best ? best - 1 : 0;
	l->slot = l->per_sect;
	for (uint32_t k = 0; k < l->per_sect; k++) {
		int err = rd(l, l->head, k, &r);
		if (err) {
			return err;
		}
		if (r.type == BTRK_LOG_EMPTY) {
			l->slot = k;
			break;
		}
		if (evlog_rec_valid(&r) && r.seq > last) {
			last = r.seq;
		}
	}
	l->next_seq = last + 1;
	return 0;
}

int evlog_append(struct evlog *l, uint8_t type, const void *payload, size_t len, uint32_t *seq_out)
{
	struct btrk_log_rec r;
	int err;

	if (len > sizeof(r.payload) || type == BTRK_LOG_EMPTY) {
		return -EINVAL;
	}
	if (l->slot >= l->per_sect) {
		uint32_t ns = (l->head + 1) % l->nsect;
		err = l->ops->erase(l->ops->ctx, ns * l->ops->sector_size, l->ops->sector_size);
		if (err) {
			return err;
		}
		l->first[ns] = EVLOG_NONE;
		l->head = ns;
		l->slot = 0;
	}
	memset(&r, 0, sizeof(r));
	r.type = type;
	r.boot_id = l->boot_id;
	r.seq = l->next_seq;
	if (len) {
		memcpy(r.payload, payload, len);
	}
	evlog_rec_seal(&r);
	err = l->ops->write(l->ops->ctx, off_of(l, l->head, l->slot), &r, RS);
	l->slot++; /* consumed even on error: never re-program a slot */
	if (err) {
		return err;
	}
	if (l->first[l->head] == EVLOG_NONE || l->first[l->head] == 0) {
		l->first[l->head] = r.seq;
	}
	if (seq_out) {
		*seq_out = r.seq;
	}
	l->next_seq++;
	return 0;
}

int evlog_erase_all(struct evlog *l)
{
	uint32_t keep = l->next_seq;
	int err = l->ops->erase(l->ops->ctx, 0, l->ops->size);

	if (err) {
		return err;
	}
	for (uint32_t s = 0; s < l->nsect; s++) {
		l->first[s] = EVLOG_NONE;
	}
	l->head = 0;
	l->slot = 0;
	l->next_seq = keep;
	return evlog_append(l, BTRK_LOG_ERASED, NULL, 0, NULL);
}

/* ring order: k = 0 is the sector after head (oldest), k = nsect - 1 is head */
static uint32_t sect_at(const struct evlog *l, uint32_t k)
{
	return (l->head + 1 + k) % l->nsect;
}

uint32_t evlog_first_seq(const struct evlog *l)
{
	for (uint32_t k = 0; k < l->nsect; k++) {
		uint32_t f = l->first[sect_at(l, k)];
		if (f != EVLOG_NONE && f != 0) {
			return f;
		}
	}
	return l->next_seq;
}

uint32_t evlog_capacity(const struct evlog *l)
{
	return (l->nsect - 1) * l->per_sect; /* one sector is always being refilled */
}

void evlog_iter_start(const struct evlog *l, struct evlog_iter *it, uint32_t from_seq)
{
	memset(it, 0, sizeof(*it));
	it->from_seq = from_seq;
	/* skip whole sectors whose successor starts at or below from_seq */
	for (uint32_t k = 0; k + 1 < l->nsect; k++) {
		uint32_t f = l->first[sect_at(l, k)];
		if (f == EVLOG_NONE || f == 0) {
			continue;
		}
		uint32_t nf = EVLOG_NONE;
		for (uint32_t j = k + 1; j < l->nsect; j++) {
			uint32_t g = l->first[sect_at(l, j)];
			if (g != EVLOG_NONE && g != 0) {
				nf = g;
				break;
			}
		}
		if (nf != EVLOG_NONE && nf <= from_seq) {
			it->k = k + 1;
			continue;
		}
		break;
	}
}

int evlog_iter_next(const struct evlog *l, struct evlog_iter *it, struct btrk_log_rec *out)
{
	while (!it->done && it->k < l->nsect) {
		uint32_t s = sect_at(l, it->k);

		if (l->first[s] == EVLOG_NONE || it->slot >= l->per_sect ||
		    (s == l->head && it->slot >= l->slot)) {
			if (s == l->head) {
				it->done = true;
				break;
			}
			it->k++;
			it->slot = 0;
			continue;
		}
		int err = rd(l, s, it->slot++, out);
		if (err) {
			return err;
		}
		if (out->type == BTRK_LOG_EMPTY) {
			it->slot = l->per_sect;
			continue;
		}
		if (evlog_rec_valid(out) && out->seq >= it->from_seq) {
			return 1;
		}
	}
	it->done = true;
	return 0;
}
