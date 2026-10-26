// Before/after screenshots for review-1. Usage: node scripts/review-shots.mjs before|after (needs `vite preview` on :4173)
import { chromium } from '@playwright/test';
const tag = process.argv[2] ?? 'after';
const out = (n) => `screenshots/review-1/${n}-${tag}.png`;
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1440, height: 1000 } });
await p.goto('http://localhost:4173/?demo');
await p.waitForSelector('.stat');
await p.waitForTimeout(800);
await p.locator('.stats, .stat-grid').first().screenshot({ path: out('1-peak-cards') });
await p.getByText('Strikes per round').first().scrollIntoViewIfNeeded().catch(() => {});
const tbl = p.locator('section.card', { has: p.locator('th', { hasText: 'Max peak g' }) }).first();
if (await tbl.count()) await tbl.screenshot({ path: out('1-round-table') });
await p.click('nav >> text=Strikes');
await p.locator('label.check', { hasText: 'Clipped only' }).click();
await p.waitForTimeout(300);
await p.locator('table').first().screenshot({ path: out('1-strike-table-clipped') });
await p.click('nav >> text=Overview');
const dq = p.locator('section.card', { hasText: 'Data quality' }).last();
await dq.scrollIntoViewIfNeeded(); await dq.screenshot({ path: out('2-data-quality') });
await p.locator('header').first().screenshot({ path: out('3-header-demo-select') });
await p.click('nav >> text=Trends'); await p.waitForTimeout(500);
await p.screenshot({ path: out('3-trends'), fullPage: false });
await p.click('nav >> text=Overview'); await p.waitForTimeout(300);
await p.screenshot({ path: out('3-overview-default-demo'), fullPage: true });
// same session as the "before" shots (the 3-round analysis/samples demo was the default then)
const opt = p.locator('select[aria-label="Active session"] option', { hasText: 'demo · 3 rounds' });
if (await opt.count()) {
  await p.selectOption('select[aria-label="Active session"]', { label: (await opt.textContent()).trim() });
  await p.waitForTimeout(500);
  await p.locator('.stats').first().screenshot({ path: out('1-peak-cards-same-session') });
  const t3 = p.locator('section.card', { has: p.locator('th', { hasText: 'Max peak g' }) }).first();
  await t3.screenshot({ path: out('1-round-table-same-session') });
  const dq3 = p.locator('section.card', { hasText: 'Data quality' }).last();
  await dq3.scrollIntoViewIfNeeded(); await dq3.screenshot({ path: out('2-data-quality-same-session') });
  const ban = p.locator('.dq-banner');
  if (await ban.count()) await ban.screenshot({ path: out('2-warning-banner-same-session') });
}
await b.close();
console.log('ok', tag);
