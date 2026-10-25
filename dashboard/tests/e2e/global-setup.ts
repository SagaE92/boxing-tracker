import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

export const FIX = path.resolve('tests/e2e/.fixtures');

function gen(prefix: string, extra: string[]) {
  if (fs.existsSync(path.join(FIX, `${prefix}_session.json`))) return;
  execFileSync('node', ['scripts/gen-demo.mjs', '--out', FIX, '--prefix', prefix, ...extra], { stdio: 'inherit' });
}

export default function setup() {
  fs.mkdirSync(FIX, { recursive: true });
  // ~1 h at 416 Hz ≈ 1.49M samples (12 × 4.5 min rounds, 30 s rests)
  gen('long-1h', ['--rounds', '12', '--round-s', '270', '--rest-s', '30', '--seed', '7', '--gaps', '6']);
  gen('heavy-sat', ['--profile', 'heavy-sat', '--rounds', '2', '--round-s', '60', '--rest-s', '20', '--seed', '8', '--no-labels']);
  gen('idle', ['--profile', 'idle', '--rounds', '1', '--round-s', '60', '--seed', '9', '--no-labels', '--gaps', '0']);
  gen('single-hand', ['--profile', 'single-hand', '--rounds', '2', '--round-s', '90', '--rest-s', '30', '--seed', '10']);
  fs.writeFileSync(path.join(FIX, 'empty_raw.csv'), '');
  fs.writeFileSync(path.join(FIX, 'malformed_raw.csv'), 'host_time_s,device_time_us,ax_g\n1,2,3\n4,5,6\n');
  fs.writeFileSync(path.join(FIX, 'garbage.csv'), 'foo,bar\n1,2\n');
  const demo = JSON.parse(fs.readFileSync('public/demo/demo_session.json', 'utf8'));
  fs.writeFileSync(path.join(FIX, 'future_session.json'), JSON.stringify({ ...demo, schema_version: '2.0.0' }));
  const broken = JSON.parse(JSON.stringify(demo));
  delete broken.session.stance; broken.punches[0].type = 'haymaker';
  fs.writeFileSync(path.join(FIX, 'broken_session.json'), JSON.stringify(broken));
}
