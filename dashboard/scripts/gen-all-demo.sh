#!/usr/bin/env bash
# Rebuilds the bundled demo data in public/demo.
#  * Main session: the Python pipeline's sample (analysis/samples: synthetic recording
#    from analysis/synth.py, processed by analysis/detector.py), raw CSV gzipped.
#    If it is missing, a session is synthesised with scripts/gen-demo.mjs instead.
#  * Default session: 6 x 2 min with fatigue, synthesised with the analysis/synth.py
#    primitives and processed by analysis/detector.py (scripts/gen_rounds_demo.py).
#  * The analysis/samples session (3 x 3 min) is kept as session.json + labels only
#    (its raw CSV is dropped to keep the bundle small).
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
  [[ -f $S/demo_labels.csv ]] && cp $S/demo_labels.csv "$OUT/demo_labels.csv"
  MAIN='"demo_session.json", "demo_labels.csv"'
  MAIN_ID=demo
  NOTE="Default session demo-6x2: analysis/synth.py primitives with fatigue (dashboard/scripts/gen_rounds_demo.py) processed by analysis/detector.py. demo: analysis/samples (same pipeline, 3 rounds). Earlier sessions: dashboard/scripts/gen-demo.mjs. All synthetic, no real recordings yet."
else
  node scripts/gen-demo.mjs --out "$OUT" --prefix demo-2026-10-24 --date 2026-10-24T18:00:00Z --seed 1 --hand rear
  MAIN='"demo-2026-10-24_session.json", "demo-2026-10-24_raw.csv.gz", "demo-2026-10-24_labels.csv"'
  MAIN_ID=demo-2026-10-24
  NOTE="All sessions synthesised by dashboard/scripts/gen-demo.mjs (analysis/samples was not available). No real recordings yet."
fi
PY=${PYTHON:-$( [[ -x ../.venv/bin/python ]] && echo ../.venv/bin/python || echo python3 )}
SIX=""
if "$PY" -c 'import numpy, jsonschema' 2>/dev/null; then
  TMP=$(mktemp -d)
  "$PY" scripts/gen_rounds_demo.py --out "$TMP/demo-6x2" --id demo-6x2 --rounds 6 --round-s 120 --rest-s 60 --seed 11 --date 2026-10-25T18:00:00+00:00
  cp "$TMP/demo-6x2_session.json" "$TMP/demo-6x2_labels.csv" "$OUT/"
  gzip -9 -c "$TMP/demo-6x2_raw.csv" > "$OUT/demo-6x2_raw.csv.gz"
  rm -rf "$TMP"
  SIX=',
    { "id": "demo-6x2", "files": ["demo-6x2_session.json", "demo-6x2_raw.csv.gz", "demo-6x2_labels.csv"] }'
else
  echo "numpy/jsonschema not available: skipping the 6-round demo (needs analysis/ tooling)" >&2
fi
cat > "$OUT/manifest.json" <<JSON
{
  "note": "$NOTE",
  "sessions": [
    { "id": "demo-2026-10-10", "files": ["demo-2026-10-10_session.json"] },
    { "id": "demo-2026-10-17", "files": ["demo-2026-10-17_session.json"] },
    { "id": "$MAIN_ID", "files": [$MAIN] }$SIX
  ]
}
JSON
ls -la "$OUT"
