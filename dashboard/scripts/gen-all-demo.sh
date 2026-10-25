#!/usr/bin/env bash
# Rebuilds the bundled demo data in public/demo.
#  * Main session: the Python pipeline's sample (analysis/samples: synthetic recording
#    from analysis/synth.py, processed by analysis/detector.py), raw CSV gzipped.
#    If it is missing, a session is synthesised with scripts/gen-demo.mjs instead.
#  * Two earlier sessions (session.json only) for the Trends view, synthesised with
#    scripts/gen-demo.mjs (deterministic seeds; sensor on the rear hand to match).
set -euo pipefail
cd "$(dirname "$0")/.."
OUT=public/demo
rm -rf "$OUT" && mkdir -p "$OUT"
node scripts/gen-demo.mjs --out "$OUT" --prefix demo-2026-10-10 --date 2026-10-10T18:00:00Z --seed 2 --intensity 1.7 --fatigue 1.5 --json-only --no-calibration --hand rear
node scripts/gen-demo.mjs --out "$OUT" --prefix demo-2026-10-17 --date 2026-10-17T18:00:00Z --seed 3 --intensity 1.9 --fatigue 1.25 --json-only --hand rear
S=../analysis/samples
if [[ -f $S/demo_session.json && -f $S/demo_raw.csv ]]; then
  cp $S/demo_session.json "$OUT/demo_session.json"
  gzip -9 -c $S/demo_raw.csv > "$OUT/demo_raw.csv.gz"
  [[ -f $S/demo_labels.csv ]] && cp $S/demo_labels.csv "$OUT/demo_labels.csv"
  MAIN='"demo_session.json", "demo_raw.csv.gz", "demo_labels.csv"'
  MAIN_ID=demo
  NOTE="Main session: analysis/samples (analysis/synth.py recording processed by analysis/detector.py). Earlier sessions: dashboard/scripts/gen-demo.mjs. All synthetic, no real recordings yet."
else
  node scripts/gen-demo.mjs --out "$OUT" --prefix demo-2026-10-24 --date 2026-10-24T18:00:00Z --seed 1 --hand rear
  MAIN='"demo-2026-10-24_session.json", "demo-2026-10-24_raw.csv.gz", "demo-2026-10-24_labels.csv"'
  MAIN_ID=demo-2026-10-24
  NOTE="All sessions synthesised by dashboard/scripts/gen-demo.mjs (analysis/samples was not available). No real recordings yet."
fi
cat > "$OUT/manifest.json" <<JSON
{
  "note": "$NOTE",
  "sessions": [
    { "id": "demo-2026-10-10", "files": ["demo-2026-10-10_session.json"] },
    { "id": "demo-2026-10-17", "files": ["demo-2026-10-17_session.json"] },
    { "id": "$MAIN_ID", "files": [$MAIN] }
  ]
}
JSON
ls -la "$OUT"
