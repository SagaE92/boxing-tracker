# Why this tracker is different

A small, open tracker for boxing and kickboxing, plus a public offline dashboard
(StrikeLab, `dashboard/`). This page says what we do differently, and what independent
research says about the trackers on sale today. Competitor facts come from the sourced
comparison compiled for this project in October 2026 (links below). Anything taken from
a maker's own site or app is marked **vendor claim**.

## What we do differently

1. **Open algorithm, tunable.** The detector (`analysis/detector.py`) is open source.
   Threshold, refractory period and window are written into every `session.json` and
   drawn on the dashboard charts, so you can see why each strike counted.
2. **Your raw data, no lock-in.** Full 416 Hz 6-axis data as CSV with a per-sample
   saturation flag; sessions use a public, versioned JSON schema
   (`docs/session.schema.json`). No subscription, no account, no cloud.
3. **Accuracy you can check.** Label a session from phone video and the dashboard's
   Accuracy view reports detection precision/recall, per-class recall and a confusion
   matrix, with an adjustable matching tolerance. Hook recall is the headline number,
   because hooks are what consumer trackers miss most.
4. **Honest units.** We report peak acceleration in g and an *estimated* speed. We
   never call anything "power" or "force": no consumer tracker has a validated force
   measurement, and a wrist IMU alone cannot measure one.
5. **Saturation and data quality up front.** The prototype IMU (LSM6DS3TR-C) clips at
   ±16 g. Clipped strikes are shown as "≥ x g" (a lower bound), and the share of
   saturated samples, BLE gaps / dropped samples, sample-rate jitter, missing
   calibration and the confidence distribution are shown on every session.
6. **Built for kickboxing.** Lead/rear hooks and uppercuts, overhand and spinning
   backfist. `kick_or_body_movement` and `clinch` are separate, low-confidence
   categories that never inflate strike totals. A sensor in a hand wrap cannot measure
   kicks; it only sees the body motion that comes with them, and we say so.
7. **Size and battery first.** Designed to sit inside hand wraps. Target: about one week
   per charge (10 × 1 h sessions plus standby) from a 40–60 mAh cell; this is an
   estimate from datasheet currents (`docs/components.md`, `docs/power.md`) until
   measured. The custom board plans an LSM6DSV320X (±16 g plus a high-g channel up to
   ±320 g) so hard shots stop clipping.
8. **Public, offline dashboard.** Static site (GitHub Pages), works offline, nothing
   uploaded. Live view over Web Bluetooth works in Chrome/Edge on desktop and Android;
   iOS Safari has no Web Bluetooth.

## What independent studies found

* **Hooks are the hard case.** In a 2021 shadowboxing study against video (21
  subjects), Corner and Hykso recognised about 83–96% of straight punches but only
  about 50–65% of hooks (Corner: lead hook 64.8%, rear hook 53.8%; Hykso: 52.1% and
  49.7%). Recognition fell for later punches in a combination.
  [Omcirk et al. 2021](https://pmc.ncbi.nlm.nih.gov/articles/PMC8123076/)
* **No validated force.** Against a force plate and 500 fps motion capture (20
  subjects), no tracker metric was strongly correlated with real velocity or force,
  and the authors advise against using any of them for force. Hykso peak velocity:
  r = 0.61, MAPE 21%; Corner "Power G": r = 0.58; Corner "speed": r = 0.03;
  StrikeTec speed: MAPE 46%.
  [Omcirk et al. 2023](https://pmc.ncbi.nlm.nih.gov/articles/PMC10599804/)
* **Kicks and clinch.** Of the established brands, only FightCamp tracks kicks, and
  only with four trackers (wrists + ankles) and its Console.
  [FightCamp help centre](https://fightcamp.zendesk.com/hc/en-us/articles/30452375440027-FightCamp-Kicktracking).
  We found no consumer tracker that tracks clinch work.

Study figures come from different protocols and athletes than ours; treat them as
context, not a head-to-head result. Our own numbers so far come from synthetic data and
only show that the pipeline works; real accuracy will be published per class once real
sessions are labelled from video.

## Comparison

| Product | Placement / size | Battery | Kicks | Data access | Subscription | Independent evidence |
|---|---|---|---|---|---|---|
| Corner (V2) | Top of wrist, under wraps or in a wristband; 25×35×8 mm, 10 g (vendor claim) | 8 h (vendor claim); 4 h in an earlier review | No (wrist only) | CSV export listed among app features (vendor claim) | Not needed for tracking; Premium for classes (vendor claim) | 2021: hooks 54–65% recognised, count error 3.1%. 2023: "Power G" r = 0.58 vs peak velocity; "speed" r = 0.03 |
| Hykso (legacy) | Top of wrist under 2+ wrap turns | 10 h, 1 h recharge (vendor claim) | No; FAQ says it filters out hand motion during kicks | Free app (vendor claim) | None for the app (vendor claim) | 2021: straights 95–96%, hooks 50–52%. 2023: peak velocity r = 0.61, MAPE 21% |
| FightCamp trackers | In FightCamp Quick Wraps; ankle wraps for kicks | 8 h, 2 h recharge (vendor claim) | Yes, with 4 trackers + ankle wraps, kickboxing classes on Console only | In-app metrics and reports | WORK membership $14.99/mo required for tracking (vendor claim) | None found for current hardware |
| StrikeTec | Wrist, under wraps; 26.5×25.5×10 mm, 10 g (vendor claim) | 10–12 h training (vendor claim) | No | Cloud history (vendor claim) | "Upgrade membership", price not stated | 2023: about half of punches missing in shadowboxing; speed MAPE 46% |
| Everlast PIQ Robot | Wrist (flexor side); 44×38 mm, 9.8 g | 8 h | No | No export reported; no live view | None | 2021: count error 12.7%. Discontinued |
| **This project (prototype)** | Inside the hand wrap; XIAO nRF52840 Sense now, custom board next | Target ~1 week (10 × 1 h + standby), estimate until measured | `kick_or_body_movement` events (low confidence, not counted as strikes); clinch logged as time | Raw 416 Hz CSV + saturation flags; public session schema; CSV/PNG export | None; open source | Not yet measured on real data; per-class confusion matrix for every labelled session |

Products and prices change; follow the links for current details. No affiliation with
any brand listed.

## Sources

* Omcirk et al. 2021, punch recognition by type: https://pmc.ncbi.nlm.nih.gov/articles/PMC8123076/
* Omcirk et al. 2023, validity of commercial punch trackers: https://pmc.ncbi.nlm.nih.gov/articles/PMC10599804/
* Corner trackers, specs and pricing: https://trainwithcorner.com/shop/p/corner-boxing-trackers
* Corner app release notes: https://apps.apple.com/us/app/corner/id1401197238
* Corner review (battery, combos): https://fightquality.com/home/equipment/corner-trackers/
* The science behind Hykso: https://shop.hykso.com/pages/the-science-behind-hykso
* Hykso FAQ (placement, kicks): https://shop.hykso.com/pages/faq
* FightCamp WORK packages: https://joinfightcamp.com/shop/work-packages
* FightCamp kick tracking: https://fightcamp.zendesk.com/hc/en-us/articles/30452375440027-FightCamp-Kicktracking
* StrikeTec sensor kit: https://striketec.com/product/striketec-smart-glove-boxing-sensors/
* PIQ Robot review: https://www.wareable.com/sport/piq-robot-boxing-review-430
* LSM6DSV320X: https://www.st.com/en/mems-and-sensors/lsm6dsv320x.html
