# Why this is better than commercial trackers

## Key advantages for a kickboxer

1. **Size & placement first**  
   Designed to live *inside* hand wraps. Target custom board ~25×20 mm or smaller. Most commercial units (Corner ~25×35×8 mm / 10 g) are larger and harder to hide under wraps.

2. **Honest metrics**  
   - Peak G reported with saturation/clipping flags (never silent clipping).  
   - Estimated speed from integrated, orientation-aware acceleration.  
   - Never claims validated “force” or “power” (no consumer tracker has published proper force validation).  
   - Confidence score per strike.

3. **Open algorithm & data**  
   - Detection rules and features are published.  
   - Raw 400+ Hz 6-axis data available (dev mode).  
   - You can improve the classifier yourself. Commercial apps are closed.

4. **Kickboxer-aware**  
   - Strike taxonomy includes jabs, crosses, hooks, uppercuts, overhand, spinning backfist, body variants.  
   - Low-confidence `kick_or_body_movement` and `clinch` duration tags (wrist sensor cannot measure kicks directly — ankle sensor is future work).  
   - Fatigue trends, type mix, round-by-round analysis.

5. **Power for real use**  
   - On-device detection + flash logging → phone only needs to sync later.  
   - Deep sleep + IMU wake-on-motion.  
   - Target: ~10 sessions / week on a tiny 40–60 mAh cell.

6. **Transparency on accuracy**  
   Published studies show commercial trackers detect straight punches well (~83–96 %) but hooks poorly (~50–65 %). We prioritize gyro features for hooks/uppercuts and show confusion matrices against labelled video.

## Competitors (summary)
- **Corner**: Good size/weight, but closed, limited high-g headroom, no open data.
- **Hykso / StrikeTec**: Focus on bag or specific sports; less ideal under wraps; closed apps.
- **FightCamp**: Kick tracking requires multiple sensors + console.
- **Whoop / general wearables**: Not punch-specific, no high-g, no classification.

This project trades polished closed-app polish for openness, size priority, and measurable honesty.
