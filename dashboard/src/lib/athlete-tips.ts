// Plain-language tooltips for the athlete view. Lab wording (tips.ts) stays technical.
// Never use "power" or "force" here; no sensor-limit, sample-rate or classifier-score talk.
export const ATIPS = {
  strikes: 'Punches plus kicks your wrist sensors picked up. Clinch time is not counted.',
  pace: 'Strikes per minute of round time. Rest periods are not counted.',
  speed: 'Estimated hand speed, averaged over your punches. Best for comparing your own rounds and sessions.',
  impact: 'Impact = how sharply your wrist accelerates into a punch (average peak wrist acceleration, in g). Higher means snappier. Compare it between your own rounds and sessions.',
  combos: 'A combo is 2 or more punches, each thrown within 0.6 s of the one before. A kick or clinch ends the combo.',
  kicks: 'Kicks are picked up from the body motion your wrist sensors feel, so the kick count is an estimate.',
  hands: 'Lead and rear hand, from which wrist sensor saw the punch and your stance (orthodox: left hand leads).',
  best: 'Best round = most strikes. Lowest round = fewest strikes.',
  finish: 'Your opening rounds compared with your closing rounds, per round on average.',
} as const;
