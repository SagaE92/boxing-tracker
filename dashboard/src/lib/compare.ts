// Competitor facts for the About page. Every row links its sources. Figures from a
// vendor's own site or app store are marked as vendor claims. Source: the sourced
// comparison canvas (Oct 2026) compiled for this project; see docs/why.md.
export interface Src { label: string; href: string }
export interface Row {
  product: string; placement: string; battery: string; kicks: string; data: string; subscription: string; evidence: string; sources: Src[];
}
export const STUDY_2021 = 'https://pmc.ncbi.nlm.nih.gov/articles/PMC8123076/';
export const STUDY_2023 = 'https://pmc.ncbi.nlm.nih.gov/articles/PMC10599804/';
export const ROWS: Row[] = [
  {
    product: 'Corner (V2)', placement: 'Top of wrist, under wraps or in a wristband; 25×35×8 mm, 10 g (vendor claim)',
    battery: '8 h (vendor claim); 4 h in an earlier review', kicks: 'No (wrist only)', data: 'CSV export listed among app features (vendor claim)',
    subscription: 'Not needed for tracking; Premium for classes (vendor claim)',
    evidence: '2021: hooks 54–65% recognised, count error 3.1%. 2023: "Power G" r = 0.58 vs peak velocity; "speed" r = 0.03.',
    sources: [{ label: 'Corner shop', href: 'https://trainwithcorner.com/shop/p/corner-boxing-trackers' }, { label: 'App Store notes', href: 'https://apps.apple.com/us/app/corner/id1401197238' }, { label: 'FightQuality review', href: 'https://fightquality.com/home/equipment/corner-trackers/' }, { label: '2021 study', href: STUDY_2021 }, { label: '2023 study', href: STUDY_2023 }],
  },
  {
    product: 'Hykso (legacy)', placement: 'Top of wrist under 2+ wrap turns', battery: '10 h, 1 h recharge (vendor claim)',
    kicks: 'No; its FAQ says it filters out hand motion during kicks', data: 'Free Hykso app (vendor claim)', subscription: 'None for the app (vendor claim)',
    evidence: '2021: straights 95–96%, hooks 50–52%. 2023: peak velocity r = 0.61, MAPE 21% (best of those tested).',
    sources: [{ label: 'Science page', href: 'https://shop.hykso.com/pages/the-science-behind-hykso' }, { label: 'FAQ', href: 'https://shop.hykso.com/pages/faq' }, { label: '2021 study', href: STUDY_2021 }, { label: '2023 study', href: STUDY_2023 }],
  },
  {
    product: 'FightCamp trackers', placement: 'In FightCamp Quick Wraps; ankle wraps for kicks', battery: '8 h, 2 h recharge (vendor claim)',
    kicks: 'Yes, with 4 trackers + ankle wraps, kickboxing classes on Console only (vendor help centre)', data: 'In-app metrics and reports',
    subscription: 'WORK membership, $14.99/mo, required for tracking (vendor claim)', evidence: 'No independent study found for current hardware.',
    sources: [{ label: 'Packages', href: 'https://joinfightcamp.com/shop/work-packages' }, { label: 'Kick tracking', href: 'https://fightcamp.zendesk.com/hc/en-us/articles/30452375440027-FightCamp-Kicktracking' }],
  },
  {
    product: 'StrikeTec', placement: 'Wrist, under wraps; 26.5×25.5×10 mm, 10 g (vendor claim)', battery: '10–12 h training (vendor claim)',
    kicks: 'No', data: 'Cloud history (vendor claim)', subscription: '"Upgrade membership", price not stated',
    evidence: '2023: about half of punches missing in shadowboxing, speed MAPE 46%.',
    sources: [{ label: 'Product page', href: 'https://striketec.com/product/striketec-smart-glove-boxing-sensors/' }, { label: '2023 study', href: STUDY_2023 }],
  },
  {
    product: 'Everlast PIQ Robot', placement: 'Wrist (flexor side); 44×38 mm, 9.8 g', battery: '8 h', kicks: 'No',
    data: 'No export reported; no live view', subscription: 'None', evidence: '2021: count error 12.7%. Discontinued.',
    sources: [{ label: 'Wareable review', href: 'https://www.wareable.com/sport/piq-robot-boxing-review-430' }, { label: '2021 study', href: STUDY_2021 }],
  },
];
export const OURS: Row = {
  product: 'This project (prototype)', placement: 'Inside the hand wrap; XIAO nRF52840 Sense for now, custom board next',
  battery: 'Target: 1 week per charge (10 × 1 h sessions + standby). An estimate until measured.',
  kicks: 'Wrist-only "kick_or_body_movement" events, labelled low-confidence and kept out of strike totals; clinch logged as time',
  data: 'Raw 6-axis CSV at 416 Hz with per-sample saturation flags; session JSON with a public schema; CSV/PNG export',
  subscription: 'None. Open source, offline dashboard, no account',
  evidence: 'No real-world numbers yet. The Accuracy tab reports per-class recall and a confusion matrix against labelled video for every labelled session.',
  sources: [{ label: 'Repo', href: 'https://github.com/SagaE92/boxing-tracker' }],
};
