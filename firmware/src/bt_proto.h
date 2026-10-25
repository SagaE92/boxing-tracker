/*
 * bt_proto.h - Wire format of the Boxing Tracker custom GATT service.
 *
 * THIS FILE MUST STAY IN SYNC WITH docs/gatt-spec.md (and tools/proto.py).
 * All multi-byte fields are little-endian. All structs are packed.
 * Portable C: no Zephyr includes, so it is also used by host unit tests.
 */
#ifndef BT_PROTO_H_
#define BT_PROTO_H_

#include <stdint.h>

#define BTRK_PROTO_VERSION 1

/* Base UUID: 6e7b0000-4b1d-4c8a-9a3e-2f5b0c1d7a00 ; 16-bit alias at bytes 2..3 */
#define BTRK_UUID_BASE_STR "6e7bXXXX-4b1d-4c8a-9a3e-2f5b0c1d7a00"
#define BTRK_UUID_SERVICE      0x0001
#define BTRK_UUID_PUNCH_EVENT  0x0002 /* notify            */
#define BTRK_UUID_SESSION_CTRL 0x0003 /* write, indicate   */
#define BTRK_UUID_SESSION_SUM  0x0004 /* read, notify      */
#define BTRK_UUID_RAW_STREAM   0x0005 /* notify            */
#define BTRK_UUID_CONFIG       0x0006 /* read, write       */
#define BTRK_UUID_STATUS       0x0007 /* read, notify      */

/* ---- Raw stream (0x0005) ------------------------------------------------ */
#define BTRK_RAW_HDR_SIZE        18
#define BTRK_RAW_SAMPLE_SIZE     12
#define BTRK_RAW_MAX_SAMPLES     18   /* 18 + 18*12 = 234 <= 244 (MTU 247) */
#define BTRK_RAW_MIN_MTU         (3 + BTRK_RAW_HDR_SIZE + BTRK_RAW_SAMPLE_SIZE)

/* raw header flags */
#define BTRK_RAW_F_FIFO_OVERRUN  0x01 /* samples were lost before this packet */
#define BTRK_RAW_F_RING_OVERRUN  0x02 /* ring buffer dropped samples          */
#define BTRK_RAW_F_TS_RESYNC     0x04 /* t0 re-anchored (gap in time base)    */

/* Scale: accel raw * 0.488 mg (+-16 g), gyro raw * 70 mdps (+-2000 dps) */
#define BTRK_ACCEL_UG_PER_LSB    488
#define BTRK_GYRO_UDPS_PER_LSB   70000
/* Saturation thresholds (|raw| >= threshold => flagged). See gatt-spec.md */
#define BTRK_ACCEL_SAT_RAW       32100 /* ~15.66 g = 98 % of 16 g   */
#define BTRK_GYRO_SAT_RAW        28000 /* 1960 dps = 98 % of 2000   */

struct __attribute__((packed)) btrk_raw_hdr {
	uint16_t seq;            /* packet sequence, wraps                     */
	uint8_t  n;              /* number of samples in this packet (1..18)   */
	uint8_t  flags;          /* BTRK_RAW_F_*                               */
	uint32_t t0_us;          /* device time of sample 0, us, wraps ~71 min */
	uint16_t period_us;      /* sample period; sample i at t0 + i*period   */
	uint32_t accel_sat_mask; /* bit i: sample i has an accel axis saturated */
	uint32_t gyro_sat_mask;  /* bit i: sample i has a gyro axis saturated  */
};

struct __attribute__((packed)) btrk_raw_sample {
	int16_t ax, ay, az;      /* accel raw, LSM6DS3TR-C axes (+-16 g)       */
	int16_t gx, gy, gz;      /* gyro raw (+-2000 dps)                      */
};

/* ---- Punch event (0x0002), 16 bytes ------------------------------------- */
/* Strike taxonomy v1 - shared with docs/session.schema.json "type" enum. */
enum btrk_punch_type {
	BTRK_PUNCH_UNKNOWN = 0,
	BTRK_PUNCH_JAB = 1,
	BTRK_PUNCH_CROSS = 2,
	BTRK_PUNCH_LEAD_HOOK = 3,
	BTRK_PUNCH_REAR_HOOK = 4,
	BTRK_PUNCH_LEAD_UPPERCUT = 5,
	BTRK_PUNCH_REAR_UPPERCUT = 6,
	BTRK_PUNCH_OVERHAND = 7,
	BTRK_PUNCH_SPINNING_BACKFIST = 8,
	BTRK_PUNCH_KICK_OR_BODY_MOVEMENT = 9, /* low confidence, wrist-only */
	BTRK_PUNCH_CLINCH = 10,  /* duration event; excluded from strike totals */
	BTRK_PUNCH_TYPE_COUNT = 11,
};

#define BTRK_PUNCH_F_ACCEL_SAT   0x01 /* peak clipped: peak_cg is a lower bound */
#define BTRK_PUNCH_F_GYRO_SAT    0x02
#define BTRK_PUNCH_F_REAR_HAND   0x04 /* sensor on rear hand (else lead hand)   */
#define BTRK_PUNCH_F_TARGET_MASK 0x18 /* bits 3..4: enum btrk_target            */
#define BTRK_PUNCH_F_TARGET_SHIFT 3
#define BTRK_PUNCH_F_UNCALIBRATED 0x20 /* no calibration yet: axes are default  */

enum btrk_target {
	BTRK_TARGET_NONE = 0, /* null in session.json */
	BTRK_TARGET_HEAD = 1,
	BTRK_TARGET_BODY = 2,
};

struct __attribute__((packed)) btrk_punch_evt {
	uint16_t index;          /* punch number within session, from 0       */
	uint32_t t_ms;           /* peak time, ms since session start         */
	uint8_t  type;           /* enum btrk_punch_type                      */
	uint8_t  flags;          /* BTRK_PUNCH_F_*                            */
	uint16_t peak_cg;        /* peak |a|-1g, 0.01 g units                 */
	uint16_t speed_cms;      /* speed estimate, cm/s (rough, see docs)    */
	uint16_t peak_gyro_dps;  /* peak |w|, dps; for CLINCH: duration in 10 ms units */
	uint8_t  confidence;     /* 0..100 -> confidence 0..1 (0 = none)      */
	uint8_t  reserved;
};

/* ---- Session control point (0x0003) ------------------------------------- */
enum btrk_ctrl_op {
	BTRK_OP_SESSION_START = 0x01, /* + u32 session_id (e.g. unix time)  */
	BTRK_OP_SESSION_STOP  = 0x02,
	BTRK_OP_RAW_START     = 0x03, /* start raw streaming                 */
	BTRK_OP_RAW_STOP      = 0x04,
	BTRK_OP_ROUND_MARK    = 0x05, /* + u8 round number (informational)   */
	BTRK_OP_POWER_OFF     = 0x06, /* enter System OFF (wake on motion)   */
	BTRK_OP_CALIBRATE     = 0x07, /* re-run guard-pose + jab calibration */
	BTRK_OP_RESPONSE      = 0x80, /* indication: 0x80, req_op, status    */
};

enum btrk_ctrl_status {
	BTRK_ST_OK = 0x00,
	BTRK_ST_UNSUPPORTED = 0x01,
	BTRK_ST_INVALID_PARAM = 0x02,
	BTRK_ST_BAD_STATE = 0x03,
};

/* ---- Session summary (0x0004), 40 bytes --------------------------------- */
#define BTRK_SESS_ACTIVE 0x01
struct __attribute__((packed)) btrk_session_summary {
	uint32_t session_id;
	uint32_t duration_ms;
	uint16_t punch_count;    /* strikes only (excludes clinch, kick_or_body_movement) */
	uint16_t by_type[BTRK_PUNCH_TYPE_COUNT]; /* indexed by btrk_punch_type */
	uint16_t max_peak_cg;
	uint16_t mean_peak_cg;
	uint16_t rate_ppm_x10;   /* punches per minute * 10                   */
	uint8_t  state;          /* BTRK_SESS_*                               */
	uint8_t  saturated_count;/* punches with clipped peak (saturates 255) */
};

/* ---- Config (0x0006), 8 bytes ------------------------------------------- */
struct __attribute__((packed)) btrk_config {
	uint8_t  version;        /* = BTRK_PROTO_VERSION (read-only)          */
	uint8_t  hand;           /* sensor hand: 0 = lead, 1 = rear           */
	uint8_t  stance;         /* 0 = orthodox, 1 = southpaw                */
	uint8_t  odr_code;       /* 0 = 416 Hz (only value in v1)             */
	uint16_t threshold_cg;   /* detector threshold on |a|-1g, 0.01 g      */
	uint16_t refractory_ms;  /* detector refractory period                */
};

/* ---- Status (0x0007), 4 bytes ------------------------------------------- */
struct __attribute__((packed)) btrk_status {
	uint8_t  power_state;    /* enum pwr_state                            */
	uint8_t  flags;          /* bit0 raw streaming, bit1 session active,
				  * bit2 calibrated, bit3 calibrating        */
	uint16_t dropped;        /* raw samples dropped since boot (sat.)     */
};

#define BTRK_STATIC_ASSERT(c, m) typedef char m[(c) ? 1 : -1]
BTRK_STATIC_ASSERT(sizeof(struct btrk_raw_hdr) == BTRK_RAW_HDR_SIZE, raw_hdr_sz);
BTRK_STATIC_ASSERT(sizeof(struct btrk_raw_sample) == BTRK_RAW_SAMPLE_SIZE, raw_s_sz);
BTRK_STATIC_ASSERT(sizeof(struct btrk_punch_evt) == 16, punch_sz);
BTRK_STATIC_ASSERT(sizeof(struct btrk_session_summary) == 40, sum_sz);
BTRK_STATIC_ASSERT(sizeof(struct btrk_config) == 8, cfg_sz);
BTRK_STATIC_ASSERT(sizeof(struct btrk_status) == 4, status_sz);
BTRK_STATIC_ASSERT(BTRK_RAW_MAX_SAMPLES <= 32, mask_bits);

#endif /* BT_PROTO_H_ */
