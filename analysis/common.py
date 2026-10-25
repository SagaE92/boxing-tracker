"""Shared constants for the analysis tools (mirror firmware/src/bt_proto.h)."""

RAW_HEADER = ["host_time_s", "device_time_us", "ax_g", "ay_g", "az_g",
              "gx_dps", "gy_dps", "gz_dps", "sat"]
LABEL_HEADER = ["host_time_s", "label", "note"]
PUNCH_CSV_HEADER = ["punch_id", "t_peak_s", "t_start_s", "t_end_s", "type", "peak_g",
                    "speed_mps_est", "duration_ms", "gyro_int_x", "gyro_int_y", "gyro_int_z",
                    "saturated"]

ACCEL_G_PER_LSB = 0.000488
GYRO_DPS_PER_LSB = 0.070
ACCEL_SAT_RAW = 32100
GYRO_SAT_RAW = 28000
ACCEL_RANGE_G = 16
GYRO_RANGE_DPS = 2000
ODR_HZ = 416.0

STRIKE_TYPES = ["jab", "cross", "lead_hook", "rear_hook", "lead_uppercut", "rear_uppercut",
                "overhand", "spinning_backfist", "unknown"]
NON_STRIKE_TYPES = ["kick_or_body_movement", "clinch"]
ALL_TYPES = ["jab", "cross", "lead_hook", "rear_hook", "lead_uppercut", "rear_uppercut",
             "overhand", "spinning_backfist", "kick_or_body_movement", "clinch", "unknown"]


def hand_worn(hand: str, stance: str) -> str:
    """Physical wrist (L/R) from sensor hand (lead/rear) + stance. Orthodox = left leads."""
    lead = "L" if stance == "orthodox" else "R"
    rear = "R" if lead == "L" else "L"
    return lead if hand == "lead" else rear


def resolve_type(base: str, hand: str) -> str:
    """Map a motion class (straight/hook/uppercut/...) to the v1 taxonomy for the sensor hand."""
    if base == "straight":
        return "jab" if hand == "lead" else "cross"
    if base in ("hook", "uppercut"):
        return f"{hand}_{base}"
    return base
