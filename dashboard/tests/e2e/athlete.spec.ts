import { expect, test, type Page } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { SHOTS, fix, noHorizontalOverflow, watchConsole } from './util';

// Athlete view (default). Phone (390 px) first, then tablet and desktop.
const ADIR = path.join(SHOTS, 'athlete');
fs.mkdirSync(ADIR, { recursive: true });
const shot = (name: string) => path.join(ADIR, name);
/** Words that must never appear on athlete screens (Lab-only or banned). */
const BANNED = /saturat|clipp|confidence|sample rate|\d+\s?hz|±\s?\d+\s?g|g-range|\bcsv\b|power|force|lower bound/i;

const phone = { viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true };

async function openDemo(page: Page) {
  await page.goto('/?demo');
  await expect(page.getByRole('region', { name: 'Round by round' })).toBeVisible();
}
async function assertNoLabWords(page: Page) {
  const text = await page.locator('main').innerText();
  expect(text).not.toMatch(BANNED);
  // tooltips are hidden until hovered; check their text too
  for (const t of await page.locator('main .tip .body').allTextContents()) expect(t).not.toMatch(BANNED);
  await expect(page.getByRole('navigation', { name: 'Views' })).toHaveCount(0);
}

test.describe('athlete view · phone 390', () => {
  test.use(phone);

  test('landing: one Open session button, Bluetooth sync coming soon', async ({ page }) => {
    const c = watchConsole(page);
    await page.goto('/');
    await expect(page.getByRole('button', { name: 'Athlete' })).toHaveAttribute('aria-pressed', 'true');
    await expect(page.getByRole('button', { name: 'Open session' })).toHaveCount(1);
    await expect(page.getByRole('button', { name: /Sync from tracker/ })).toBeDisabled();
    await assertNoLabWords(page);
    await noHorizontalOverflow(page);
    await page.screenshot({ path: shot('phone-390-landing.png') });
    c.assertClean();
  });

  test('header + rounds: takeaway, best/lowest round, hand split', async ({ page }) => {
    const c = watchConsole(page);
    await openDemo(page);
    const head = page.getByRole('region', { name: 'Session summary' });
    await expect(head.locator('h1')).toHaveText('10 rounds × 3 min');
    await expect(head.locator('.take')).toHaveText(/^Strong start; your output dropped \d+% and speed \d+% in the last 3 rounds\.$/);
    await expect(head).toContainText('strikes');
    await expect(head).toContainText('per min');
    await expect(head).toContainText('best round');
    await expect(head.getByRole('button', { name: /Data quality: (good|check)/ })).toBeVisible();
    await expect(head.getByRole('img', { name: /Lead hand \d+%, rear hand \d+%/ })).toBeVisible();
    await expect(head).toContainText(/Rear hand did \d+% in rounds 8–10, up from \d+% early\./);
    const rows = page.getByRole('region', { name: 'Round by round' }).locator('li');
    await expect(rows).toHaveCount(10);
    await expect(rows.locator('.tag.best')).toHaveCount(1);
    await expect(rows.locator('.tag.weak')).toHaveCount(1);
    await expect(rows.first().locator('.mini [role=img]')).toBeVisible(); // per-round hand split
    await expect(rows.first()).toContainText('impact');
    await expect(rows.first()).toContainText('combos');
    await assertNoLabWords(page);
    await noHorizontalOverflow(page);
    await page.screenshot({ path: shot('phone-390-header-rounds.png') });
    await head.screenshot({ path: shot('phone-390-hand-balance.png') });
    c.assertClean();
  });

  test('tapping a round opens its strike timeline', async ({ page }) => {
    await openDemo(page);
    const r9 = page.getByRole('button', { name: /^R9\b/ });
    await r9.click();
    await expect(r9).toHaveAttribute('aria-expanded', 'true');
    const tl = page.getByRole('img', { name: 'Round 9 strike timeline' });
    await expect(tl).toBeVisible();
    expect(await tl.locator('line[stroke-linecap=round]').count()).toBeGreaterThan(30);
    await expect(page.getByLabel('Strikes per minute', { exact: true })).toContainText('Min 3');
    await page.locator('li.open').scrollIntoViewIfNeeded();
    await page.locator('li.open').screenshot({ path: shot('phone-390-round-timeline.png') });
    await r9.click();
    await expect(tl).toHaveCount(0);
    await assertNoLabWords(page);
  });

  test('How you finished: first 3 vs last 3, trend and plain-language notes', async ({ page }) => {
    await openDemo(page);
    const fin = page.getByRole('region', { name: 'How you finished' });
    await expect(fin).toContainText('First 3 vs last 3 rounds');
    for (const row of ['Strikes / round', 'Speed (m/s)', 'Impact', 'Combos / round', 'Kick share', 'Rear hand share']) await expect(fin.locator('td', { hasText: row })).toBeVisible();
    await expect(fin.locator('tr', { hasText: 'Strikes / round' }).locator('td').last()).toHaveText(/^−\d+%$/);
    await expect(fin.locator('.notes li').first()).toBeVisible();
    await expect(fin).toContainText(/Kicks dropped off/);
    await expect(fin).toContainText(/Lead hand faded more/);
    await expect(fin.getByRole('img', { name: /as % of the opening rounds/ })).toBeVisible();
    await fin.scrollIntoViewIfNeeded();
    await fin.screenshot({ path: shot('phone-390-finish.png') });
  });

  test('strike mix with friendly labels and top combos', async ({ page }) => {
    await openDemo(page);
    const mix = page.getByRole('region', { name: 'Strike mix' });
    const labels = await mix.locator('.ml').allInnerTexts();
    for (const l of ['Jab', 'Cross', 'Hook', 'Uppercut', 'Overhand', 'Spinning backfist', 'Kick']) expect(labels.map((x) => x.replace(/\s*i$/, '').trim())).toContain(l);
    expect(labels.join(' ')).not.toMatch(/lead_|rear_|kick_or_body/);
    await expect(mix.locator('.combos li').first()).toContainText('→');
    await mix.scrollIntoViewIfNeeded();
    await mix.screenshot({ path: shot('phone-390-strike-mix.png') });
  });

  test('session history: list, trends, switching to a 3-round session', async ({ page }) => {
    const c = watchConsole(page);
    await openDemo(page);
    const hist = page.getByRole('region', { name: 'Session history' });
    await expect(hist.locator('li')).toHaveCount(5);
    await expect(hist.getByRole('img', { name: 'Strikes per minute per session' })).toBeVisible();
    await expect(hist.getByRole('img', { name: 'Late-round output change per session' })).toBeVisible();
    await hist.scrollIntoViewIfNeeded();
    await hist.screenshot({ path: shot('phone-390-history.png') });
    // fewer than 6 rounds: comparison falls back gracefully
    await hist.locator('li button', { hasText: 'Oct 24' }).click();
    await expect(page.getByRole('region', { name: 'Session summary' }).locator('h1')).toHaveText(/^3 rounds/);
    await expect(page.getByRole('region', { name: 'How you finished' })).toContainText('First round vs last round');
    await assertNoLabWords(page);
    c.assertClean();
  });

  test('Lab toggle is remembered; data-quality badge links into Lab', async ({ page }) => {
    await openDemo(page);
    await page.getByRole('button', { name: 'Lab' }).click();
    await expect(page.getByRole('navigation', { name: 'Views' })).toBeVisible();
    await expect(page.getByText('low confidence · not in totals')).toBeVisible();
    await page.screenshot({ path: shot('phone-390-lab-toggle.png') });
    expect(await page.evaluate(() => localStorage.getItem('strikelab.view'))).toBe('lab');
    await page.goto('/?demo');
    await expect(page.getByRole('navigation', { name: 'Views' })).toBeVisible();
    await page.getByRole('button', { name: 'Athlete' }).click();
    await expect(page.getByRole('region', { name: 'Round by round' })).toBeVisible();
    await page.goto('/?demo');
    await expect(page.getByRole('region', { name: 'Round by round' })).toBeVisible();
    await page.getByRole('button', { name: /Data quality/ }).click();
    await expect(page.locator('#data-quality')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Lab' })).toHaveAttribute('aria-pressed', 'true');
  });

  test('Open session accepts the same files underneath, no file jargon', async ({ page }) => {
    const c = watchConsole(page);
    await page.goto('/');
    await page.getByLabel('Choose session files').setInputFiles([fix('single-hand_session.json'), fix('single-hand_raw.csv.gz'), fix('single-hand_labels.csv')]);
    await expect(page.getByRole('region', { name: 'Round by round' }).locator('li')).toHaveCount(2);
    await expect(page.getByRole('region', { name: 'How you finished' })).toContainText('First round vs last round');
    await assertNoLabWords(page);
    // a bad file: short plain message, details in Lab
    await page.getByLabel('Choose session files').setInputFiles([fix('garbage.csv')]);
    await expect(page.getByRole('alert')).toHaveText(/Some files couldn't be opened\. See details in Lab/);
    c.assertClean();
  });
});

for (const vp of [{ w: 375, h: 812 }, { w: 414, h: 896 }, { w: 820, h: 1180 }, { w: 1440, h: 1000 }]) {
  test(`athlete view ${vp.w}px: no horizontal overflow${vp.w >= 820 ? ' + screenshot' : ''}`, async ({ browser }) => {
    const page = await browser.newPage({ viewport: { width: vp.w, height: vp.h }, deviceScaleFactor: vp.w >= 1440 ? 1 : 2, isMobile: vp.w < 500, hasTouch: vp.w < 500 });
    const c = watchConsole(page);
    await openDemo(page);
    await page.getByRole('button', { name: /^R8\b/ }).click();
    await noHorizontalOverflow(page);
    await page.evaluate(() => window.scrollTo(0, 0));
    if (vp.w >= 820) await page.screenshot({ path: shot(`${vp.w >= 1440 ? 'desktop-1440' : 'tablet-820'}-overview.png`), fullPage: true });
    c.assertClean();
    await page.close();
  });
}
