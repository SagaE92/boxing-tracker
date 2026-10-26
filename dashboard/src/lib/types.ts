import type { EventType } from './taxonomy';

export type Hand = 'L' | 'R' | null;
export interface StrikeEvent {
  id: number;
  t_peak_s: number;
  t_start_s: number;
  t_end_s: number;
  type: EventType;
  confidence: number;
  target: 'head' | 'body' | null;
  hand: Hand;
  peak_g: number;
  speed_mps_est: number | null;
  duration_ms: number;
  gyro_int_dps_s: [number, number, number];
  saturated: boolean;
  round_index: number | null;
  /** schema 1.1: which sensor detected the event (two-sensor sessions) */
  device_id?: string | null;
}
export interface DeviceInfo {
  device_id: string; hand: 'lead' | 'rear' | null; wrist: Hand; firmware_version?: string | null;
  sample_rate_hz?: number | null; calibrated?: boolean | null;
  clock?: { source: string; offset_s: number; skew_ppm: number; residual_ms?: number | null; sync_points?: number | null; start_offset_s?: number | null } | null;
}
export interface Round { index: number; t_start_s: number; t_end_s: number; kind: 'round' | 'rest' }
export interface SessionJson {
  schema_version: string;
  generator: { name: string; version: string };
  session: {
    id: string; start_time_iso: string; duration_s: number; sample_rate_hz: number;
    accel_range_g: number; gyro_range_dps: number; hand_worn: Hand;
    hand: 'lead' | 'rear' | null; stance: 'orthodox' | 'southpaw' | null;
    sensor_mount?: string | null;
    /** schema 1.1: one entry per sensor (one inside each wrap) */
    devices?: DeviceInfo[] | null;
    calibration?: { guard_gravity_g: number[]; forward_axis: number[]; t_start_s: number; t_end_s: number } | null;
  };
  detector_params: { threshold_g: number; refractory_ms: number; window_ms: number };
  rounds: Round[];
  punches: StrikeEvent[];
  summary: {
    punch_count: number; punches_per_min: number; punches_per_round: number[];
    mean_peak_g: number | null; max_peak_g: number | null;
    mean_speed_mps_est: number | null; max_speed_mps_est: number | null;
    by_type: Record<string, number>; by_hand: Record<string, number>;
    saturated_sample_fraction: number;
    by_target?: Record<string, number>; non_punch_count?: number; clinch_time_s?: number;
  };
}

/** Columnar raw data. t is seconds from first sample on the device clock. */
export interface RawData {
  n: number;
  t: Float64Array;
  ax: Float32Array; ay: Float32Array; az: Float32Array;
  gx: Float32Array; gy: Float32Array; gz: Float32Array;
  amag: Float32Array; // |a| - 1 g
  sat: Uint8Array;
  hostT0: number; // first host_time_s (labels are aligned against this)
  satCount: number;
}
export interface LabelRow { t: number; rawLabel: string; type: EventType | null; hand: Hand; note: string }

export interface LoadedSession {
  key: string;
  name: string;
  files: string[];
  json?: SessionJson;
  raw?: RawData;
  labels?: LabelRow[];
  labelHostTimes?: number[]; // unaligned, kept so we can re-align if raw arrives later
  errors: string[];
  warnings: string[];
  demo?: boolean;
}
