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

#define BTRK_PROTO_VERSION 1   /* Config.version byte (unchanged for v1 centrals) */
#define BTRK_PROTO_MINOR   1   /* v1.1: two sensors (role, time sync, event log)  */

/* Base UUID: 6e7b0000-4b1d-4c8a-9a3e-2f5b0c1d7a00 ; 16-bit alias at bytes 2..3 */
#define BTRK_UUID_BASE_STR "6e7bXXXX-4b1d-4c8a-9a3e-2f5b0c1d7a00"
#define BTRK_UUID_SERVICE      0x0001
#define BTRK_UUID_PUNCH_EVENT  0x0002 /* notify            */
#define BTRK_UUID_SESSION_CTRL 0x0003 /* write, indicate   */
#define BTRK_UUID_SESSION_SUM  0x0004 /* read, notify      */
#define BTRK_UUID_RAW_STREAM   0x0005 /* notify            */
#define BTRK_UUID_CONFIG       0x0006 /* read, write       */
#define BTRK_UUID_STATUS       0x0007 /* read, notify      */
#define BTRK_UUID_TIME_SYNC    0x0008 /* read, write (v1.1) */
#define BTRK_UUID_ROLE         0x0009 /* read, write (v1.1) */
#define BTRK_UUID_EVENT_LOG    0x000A /* read, write, notify (v1.1) */

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
	BTRK_OP_FORGET        = 0x08, /* v1.1: clear role + wrist + all bonds (role rules) */
	BTRK_OP_RESPONSE      = 0x80, /* indication: 0x80, req_op, status    */
};

enum btrk_ctrl_status {
	BTRK_ST_OK = 0x00,
	BTRK_ST_UNSUPPORTED = 0x01,
	BTRK_ST_INVALID_PARAM = 0x02,
	BTRK_ST_BAD_STATE = 0x03,
	BTRK_ST_NOT_PERMITTED = 0x04, /* v1.1: role locked (not bonded, window closed) */
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

/* ---- v1.1: two sensors ------------------------------------------------- */
/* Hand role (0x0009) and advertising. Role 0 = unset (never assigned).   */
enum btrk_role { BTRK_ROLE_UNSET = 0, BTRK_ROLE_LEAD = 1, BTRK_ROLE_REAR = 2 };
enum btrk_wrist { BTRK_WRIST_UNKNOWN = 0, BTRK_WRIST_LEFT = 1, BTRK_WRIST_RIGHT = 2 };

#define BTRK_ROLE_F_WINDOW_OPEN 0x01 /* pairing window after boot is open      */
#define BTRK_ROLE_F_BONDED_LINK 0x02 /* this link is encrypted with a bond     */
#define BTRK_ROLE_F_PERSISTED   0x04 /* role came from / was saved to settings */

struct __attribute__((packed)) btrk_role_chr {
	uint8_t role;            /* enum btrk_role (write: 0..2)                */
	uint8_t wrist;           /* enum btrk_wrist (write: 0..2)               */
	uint8_t flags;           /* BTRK_ROLE_F_* (read-only)                   */
	uint8_t window_s;        /* seconds left in the pairing window (r/o)    */
};

/* Manufacturer-specific advertising data (company 0xFFFF = "no company", for
 * prototypes). ADV = flags (3) + 128-bit service UUID (18) + this (2+8) = 31 B. */
#define BTRK_ADV_COMPANY_ID     0xFFFF
#define BTRK_ADV_PROTO          0x11 /* (major << 4) | minor                   */
#define BTRK_ADV_F_SESSION      0x01 /* session active                         */
#define BTRK_ADV_F_LOG_PENDING  0x02 /* event log has records not yet ACKed    */
#define BTRK_ADV_F_WINDOW_OPEN  0x04 /* pairing window open (role writable)     */
struct __attribute__((packed)) btrk_adv_mfg {
	uint16_t company;        /* BTRK_ADV_COMPANY_ID                         */
	uint8_t  proto;          /* BTRK_ADV_PROTO                              */
	uint8_t  role;           /* enum btrk_role                              */
	uint8_t  wrist;          /* enum btrk_wrist                             */
	uint8_t  flags;          /* BTRK_ADV_F_*                                */
	uint16_t dev_suffix;     /* low 16 bits of the FICR device id           */
};

/* Time sync (0x0008). Read: device clock now. Write: an anchor computed by the
 * central from its best round trip, stored in the event log. */
#define BTRK_TS_F_SESSION       0x01
struct __attribute__((packed)) btrk_time_sync {
	uint32_t device_time_us; /* same 32-bit us counter as raw t0_us / events */
	uint16_t boot_id;        /* increments every boot (settings)            */
	uint8_t  flags;          /* BTRK_TS_F_*                                 */
	uint8_t  reserved;
};
struct __attribute__((packed)) btrk_time_anchor {
	uint64_t host_unix_us;   /* host clock at the exchange midpoint         */
	uint32_t device_time_us; /* device clock read in that exchange          */
	uint16_t rtt_100us;      /* round-trip time of that exchange, 0.1 ms    */
};

/* Event log (0x000A): 32-byte records in a ring on the QSPI NOR. */
#define BTRK_LOG_REC_SIZE  32
enum btrk_log_type {
	BTRK_LOG_SESSION_START = 0x01,
	BTRK_LOG_EVENT         = 0x02,
	BTRK_LOG_ANCHOR        = 0x03,
	BTRK_LOG_SESSION_STOP  = 0x04,
	BTRK_LOG_ROUND_MARK    = 0x05,
	BTRK_LOG_BOOT          = 0x06,
	BTRK_LOG_ERASED        = 0x07, /* first record after an ERASE            */
	BTRK_LOG_END           = 0xFE, /* transfer only: end of a READ           */
	BTRK_LOG_EMPTY         = 0xFF, /* erased flash                           */
};
struct __attribute__((packed)) btrk_log_rec {
	uint8_t  type;           /* enum btrk_log_type                          */
	uint8_t  flags;          /* reserved, 0                                 */
	uint16_t boot_id;
	uint32_t seq;            /* global record sequence number               */
	uint8_t  payload[22];
	uint16_t crc;            /* CRC-16/CCITT-FALSE over bytes 0..29         */
};
struct __attribute__((packed)) btrk_log_session_start {
	uint32_t session_id;     /* from SESSION_START (host unix time)         */
	uint32_t dev_t0_us;      /* device time at start                        */
	uint8_t  role, wrist, stance, odr_code;
	uint16_t threshold_cg, refractory_ms;
	uint8_t  fw_major, fw_minor, fw_patch, reserved;
	uint8_t  pad[2];
};
struct __attribute__((packed)) btrk_log_event {
	uint32_t dev_t_peak_us;  /* device clock at the peak (time-sync base)   */
	uint8_t  type;           /* enum btrk_punch_type                        */
	uint8_t  flags;          /* BTRK_PUNCH_F_*                              */
	uint16_t peak_cg;        /* as btrk_punch_evt                           */
	uint16_t speed_cms;
	uint16_t peak_gyro_dps;
	uint8_t  confidence;
	uint8_t  pre_2ms;        /* (t_peak - t_start) / 2 ms, saturating       */
	uint8_t  post_2ms;       /* (t_end - t_peak) / 2 ms, saturating         */
	int16_t  gyro_int_ddeg[3]; /* gyro integral over +-150 ms, 0.1 deg, SENSOR frame */
	uint8_t  reserved;
};
struct __attribute__((packed)) btrk_log_anchor {
	struct btrk_time_anchor a;
	uint8_t pad[8];
};
struct __attribute__((packed)) btrk_log_session_stop {
	uint32_t session_id;
	uint32_t duration_ms;
	uint32_t dev_t_us;
	uint16_t punch_count;
	uint8_t  pad[8];
};
struct __attribute__((packed)) btrk_log_round {
	uint32_t dev_t_us;
	uint8_t  round;
	uint8_t  pad[17];
};
struct __attribute__((packed)) btrk_log_boot {
	uint32_t reset_cause;    /* hwinfo reset cause bits                      */
	uint8_t  role, wrist;
	uint8_t  pad[16];
};
/* 0x000A read: log info */
struct __attribute__((packed)) btrk_log_info {
	uint32_t first_seq;      /* oldest record still stored                  */
	uint32_t next_seq;       /* seq of the next record to be written        */
	uint32_t capacity;       /* records the ring holds                      */
	uint16_t boot_id;
	uint8_t  rec_size;       /* BTRK_LOG_REC_SIZE                           */
	uint8_t  flags;          /* bit0: a READ is in progress                 */
};
/* 0x000A write: control */
enum btrk_log_op {
	BTRK_LOG_OP_READ  = 0x01, /* + u32 from_seq, u32 max_records (0 = all) */
	BTRK_LOG_OP_ABORT = 0x02,
	BTRK_LOG_OP_ERASE = 0x03, /* + u32 magic 0x45524153 ("ERAS")           */
	BTRK_LOG_OP_ACK   = 0x04, /* + u32 seq: host has everything below seq   */
};
#define BTRK_LOG_ERASE_MAGIC 0x45524153u

#define BTRK_STATIC_ASSERT(c, m) typedef char m[(c) ? 1 : -1]
BTRK_STATIC_ASSERT(sizeof(struct btrk_raw_hdr) == BTRK_RAW_HDR_SIZE, raw_hdr_sz);
BTRK_STATIC_ASSERT(sizeof(struct btrk_raw_sample) == BTRK_RAW_SAMPLE_SIZE, raw_s_sz);
BTRK_STATIC_ASSERT(sizeof(struct btrk_punch_evt) == 16, punch_sz);
BTRK_STATIC_ASSERT(sizeof(struct btrk_session_summary) == 40, sum_sz);
BTRK_STATIC_ASSERT(sizeof(struct btrk_config) == 8, cfg_sz);
BTRK_STATIC_ASSERT(sizeof(struct btrk_status) == 4, status_sz);
BTRK_STATIC_ASSERT(BTRK_RAW_MAX_SAMPLES <= 32, mask_bits);
BTRK_STATIC_ASSERT(sizeof(struct btrk_role_chr) == 4, role_sz);
BTRK_STATIC_ASSERT(sizeof(struct btrk_adv_mfg) == 8, adv_sz);
BTRK_STATIC_ASSERT(sizeof(struct btrk_time_sync) == 8, ts_sz);
BTRK_STATIC_ASSERT(sizeof(struct btrk_time_anchor) == 14, anchor_sz);
BTRK_STATIC_ASSERT(sizeof(struct btrk_log_rec) == BTRK_LOG_REC_SIZE, rec_sz);
BTRK_STATIC_ASSERT(sizeof(struct btrk_log_session_start) == 22, lss_sz);
BTRK_STATIC_ASSERT(sizeof(struct btrk_log_event) == 22, lev_sz);
BTRK_STATIC_ASSERT(sizeof(struct btrk_log_anchor) == 22, lan_sz);
BTRK_STATIC_ASSERT(sizeof(struct btrk_log_session_stop) == 22, lst_sz);
BTRK_STATIC_ASSERT(sizeof(struct btrk_log_round) == 22, lrd_sz);
BTRK_STATIC_ASSERT(sizeof(struct btrk_log_boot) == 22, lbt_sz);
BTRK_STATIC_ASSERT(sizeof(struct btrk_log_info) == 16, linfo_sz);

#endif /* BT_PROTO_H_ */
