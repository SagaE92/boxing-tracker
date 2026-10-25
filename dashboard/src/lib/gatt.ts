// Web Bluetooth live mode. Wire format from firmware/src/bt_proto.h (BTRK_PROTO_VERSION 1).
// docs/gatt-spec.md is the human-readable spec; keep this file in sync with both.
// Device name: BoxTrk. Recommended MTU 247 (18 raw samples per notification).
import type { EventType } from './taxonomy';

export const uuid16 = (alias: number) => `6e7b${alias.toString(16).padStart(4, '0')}-4b1d-4c8a-9a3e-2f5b0c1d7a00`;
export const UUID = {
  service: uuid16(0x0001), punchEvent: uuid16(0x0002), sessionCtrl: uuid16(0x0003), sessionSum: uuid16(0x0004),
  rawStream: uuid16(0x0005), config: uuid16(0x0006), status: uuid16(0x0007),
} as const;
export const ACCEL_G_PER_LSB = 488e-6;
export const GYRO_DPS_PER_LSB = 0.07;
export const TYPE_BY_CODE: EventType[] = ['unknown', 'jab', 'cross', 'lead_hook', 'rear_hook', 'lead_uppercut', 'rear_uppercut', 'overhand', 'spinning_backfist', 'kick_or_body_movement', 'clinch'];
export const OP = { SESSION_START: 0x01, SESSION_STOP: 0x02, RAW_START: 0x03, RAW_STOP: 0x04, CALIBRATE: 0x07 } as const;

export interface RawPacket {
  seq: number; n: number; flags: number; t0_us: number; period_us: number;
  samples: { t_us: number; ax: number; ay: number; az: number; gx: number; gy: number; gz: number; sat: boolean }[];
}
export function parseRawPacket(dv: DataView): RawPacket {
  if (dv.byteLength < 18) throw new Error(`raw packet too short (${dv.byteLength} B)`);
  const seq = dv.getUint16(0, true), n = dv.getUint8(2), flags = dv.getUint8(3);
  const t0_us = dv.getUint32(4, true), period_us = dv.getUint16(8, true);
  const aMask = dv.getUint32(10, true), gMask = dv.getUint32(14, true);
  if (dv.byteLength < 18 + n * 12) throw new Error(`raw packet declares ${n} samples but has ${dv.byteLength} B`);
  const samples = [];
  for (let i = 0; i < n; i++) {
    const o = 18 + i * 12;
    samples.push({
      t_us: t0_us + i * period_us,
      ax: dv.getInt16(o, true) * ACCEL_G_PER_LSB, ay: dv.getInt16(o + 2, true) * ACCEL_G_PER_LSB, az: dv.getInt16(o + 4, true) * ACCEL_G_PER_LSB,
      gx: dv.getInt16(o + 6, true) * GYRO_DPS_PER_LSB, gy: dv.getInt16(o + 8, true) * GYRO_DPS_PER_LSB, gz: dv.getInt16(o + 10, true) * GYRO_DPS_PER_LSB,
      sat: ((aMask >>> i) & 1) === 1 || ((gMask >>> i) & 1) === 1,
    });
  }
  return { seq, n, flags, t0_us, period_us, samples };
}
export interface LivePunch { index: number; t_s: number; type: EventType; saturated: boolean; target: 'head' | 'body' | null; peak_g: number; speed_mps: number; confidence: number; uncalibrated: boolean; clinch_s: number | null }
export function parsePunchEvent(dv: DataView): LivePunch {
  if (dv.byteLength < 16) throw new Error(`punch event too short (${dv.byteLength} B)`);
  const type = TYPE_BY_CODE[dv.getUint8(6)] ?? 'unknown';
  const flags = dv.getUint8(7);
  const tgt = (flags & 0x18) >> 3;
  const g = dv.getUint16(12, true);
  return {
    index: dv.getUint16(0, true), t_s: dv.getUint32(2, true) / 1000, type, saturated: (flags & 0x01) !== 0,
    target: tgt === 1 ? 'head' : tgt === 2 ? 'body' : null, peak_g: dv.getUint16(8, true) / 100, speed_mps: dv.getUint16(10, true) / 100,
    confidence: dv.getUint8(14) / 100, uncalibrated: (flags & 0x20) !== 0, clinch_s: type === 'clinch' ? g / 100 : null,
  };
}

// Minimal Web Bluetooth typings (not in lib.dom by default).
interface BtChar { value?: DataView; startNotifications(): Promise<BtChar>; addEventListener(t: string, cb: (e: Event) => void): void; writeValue(v: BufferSource): Promise<void>; writeValueWithResponse?(v: BufferSource): Promise<void> }
interface BtService { getCharacteristic(u: string): Promise<BtChar> }
interface BtServer { getPrimaryService(u: string): Promise<BtService>; disconnect(): void; connected: boolean }
interface BtDevice { name?: string; gatt?: { connect(): Promise<BtServer> }; addEventListener(t: string, cb: () => void): void }
interface Bt { requestDevice(o: unknown): Promise<BtDevice> }

export const webBluetoothAvailable = () => typeof navigator !== 'undefined' && 'bluetooth' in navigator;

export class LiveClient {
  server: BtServer | null = null;
  device: BtDevice | null = null;
  ctrl: BtChar | null = null;
  constructor(private on: { raw?: (p: RawPacket) => void; punch?: (p: LivePunch) => void; status?: (s: string) => void; error?: (e: string) => void }) {}
  async connect() {
    const bt = (navigator as unknown as { bluetooth: Bt }).bluetooth;
    this.device = await bt.requestDevice({ filters: [{ services: [UUID.service] }], optionalServices: ['battery_service'] });
    this.device.addEventListener('gattserverdisconnected', () => this.on.status?.('Disconnected'));
    this.on.status?.(`Connecting to ${this.device.name ?? 'tracker'}…`);
    this.server = (await this.device.gatt!.connect());
    const svc = await this.server.getPrimaryService(UUID.service);
    const raw = await svc.getCharacteristic(UUID.rawStream);
    raw.addEventListener('characteristicvaluechanged', (e) => { try { this.on.raw?.(parseRawPacket((e.target as unknown as BtChar).value!)); } catch (err) { this.on.error?.(String(err)); } });
    await raw.startNotifications();
    const pe = await svc.getCharacteristic(UUID.punchEvent);
    pe.addEventListener('characteristicvaluechanged', (e) => { try { this.on.punch?.(parsePunchEvent((e.target as unknown as BtChar).value!)); } catch (err) { this.on.error?.(String(err)); } });
    await pe.startNotifications();
    this.ctrl = await svc.getCharacteristic(UUID.sessionCtrl);
    await this.write(new Uint8Array([OP.RAW_START]));
    this.on.status?.(`Connected to ${this.device.name ?? 'tracker'}`);
  }
  /** Control point is write-with-response (docs/gatt-spec.md). */
  private async write(v: Uint8Array<ArrayBuffer>) {
    if (!this.ctrl) return;
    if (this.ctrl.writeValueWithResponse) await this.ctrl.writeValueWithResponse(v); else await this.ctrl.writeValue(v);
  }
  async disconnect() {
    try { await this.write(new Uint8Array([OP.RAW_STOP])); } catch { /* ignore */ }
    this.server?.disconnect();
  }
}
