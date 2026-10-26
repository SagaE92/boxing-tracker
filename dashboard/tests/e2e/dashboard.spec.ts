import { expect, test } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { SHOTS, fix, loadDemo, noHorizontalOverflow, tab, watchConsole } from './util';

test.describe('demo session', () => {
  test('loads with zero console errors and renders every view', async ({ page }) => {
    const c = watchConsole(page);
    await loadDemo(page);
    await expect(page.getByText('demo · synthetic recording')).toBeVisible();
    await expect(page.getByText('Sensors:')).toBeVisible(); // two-sensor default demo
    await expect(page.getByText(/clock: lead \+0\.3\d\d s/)).toBeVisible();
    await expect(page.getByText('Stance:')).toBeVisible();
    await expect(page.locator('.stat').first()).toContainText('Strikes');
    await expect(page.getByText('low confidence · not in totals')).toBeVisible();
    await page.screenshot({ path: path.join(SHOTS, 'desktop-overview.png'), fullPage: true });
    for (const [t, marker, file] of [
      ['Signals', 'Raw signals', 'desktop-signals.png'], ['Strikes', 'Export CSV', 'desktop-strikes.png'], ['Trends', 'Compare sessions', 'desktop-trends.png'],
      ['Accuracy', 'Confusion matrix', 'desktop-accuracy.png'], ['Live', 'Live (Web Bluetooth)', 'desktop-live.png'], ['Why this is different', 'Built to be checked, not trusted', 'desktop-about.png'],
    ] as const) {
      await tab(page, t);
      await expect(page.getByText(marker, { exact: false }).first()).toBeVisible();
      await page.waitForTimeout(300);
      await page.screenshot({ path: path.join(SHOTS, file), fullPage: true });
    }
    c.assertClean();
  });

  test('default demo is the 10 x 3 min two-sensor session; others selectable', async ({ page }) => {
    await loadDemo(page);
    const sel = page.getByRole('combobox', { name: 'Active session' });
    await expect(sel.locator('option')).toHaveCount(5);
    await expect(sel.locator('option:checked')).toHaveText(/demo-10x3 · 10 rounds/);
    const rounds = page.locator('section.card', { has: page.locator('th', { hasText: 'Max peak g' }) }).locator('tbody tr');
    await expect(rounds).toHaveCount(10);
    // partial raw is explained in Lab only
    await expect(page.locator('.warns summary')).toContainText('loader note');
    await sel.selectOption({ label: 'demo-6x2 · 6 rounds (no raw)' });
    await expect(rounds).toHaveCount(6);
    await expect(page.getByText('Peak g, first → last round')).toBeVisible();
    await sel.selectOption({ label: 'demo · 3 rounds (no raw)' });
    await expect(rounds).toHaveCount(3);
  });

  test('clicking a strike opens its window and zooms the signals', async ({ page }) => {
    const c = watchConsole(page);
    await loadDemo(page);
    await tab(page, 'Strikes');
    await page.locator('tbody tr').nth(5).click();
    await expect(page.getByRole('region', { name: 'Strike detail' })).toBeVisible();
    await expect(page.getByRole('region', { name: 'Strike detail' }).locator('canvas')).toHaveCount(2);
    await page.screenshot({ path: path.join(SHOTS, 'desktop-strike-detail.png'), fullPage: true });
    await tab(page, 'Signals');
    await expect(page.getByText(/showing \d+:\d\d\.\d\d–/)).toBeVisible();
    // filters: min confidence slider reduces the list
    await tab(page, 'Strikes');
    const before = await page.locator('h2:has-text("Events") .sub').innerText();
    await page.getByLabel('Minimum confidence').fill('0.8');
    await expect(page.locator('h2:has-text("Events") .sub')).not.toHaveText(before);
    c.assertClean();
  });

  test('accuracy view surfaces hook recall and reacts to tolerance', async ({ page }) => {
    await loadDemo(page);
    await tab(page, 'Accuracy');
    const hook = page.getByRole('region', { name: 'Hook recall' });
    await expect(hook).toContainText('%');
    await expect(hook).toContainText('Omcirk et al. 2021');
    await expect(page.locator('.stat', { hasText: 'Detection recall' }).locator('.val')).toContainText('%');
    await expect(page.getByRole('note').first()).toContainText('Synthetic data');
    await page.getByLabel('Matching tolerance in ms').fill('50');
    await expect(page.getByText('±50 ms', { exact: true })).toBeVisible();
    await expect(page.getByText(/within ±50 ms/)).toBeVisible();
    expect(await page.locator('table.cm tr.hookrow').count()).toBeGreaterThanOrEqual(1);
  });

  test('exports summary PNG, summary CSV and events CSV', async ({ page }) => {
    await loadDemo(page);
    const dl = async (name: RegExp) => {
      const [d] = await Promise.all([page.waitForEvent('download'), page.getByRole('button', { name }).click()]);
      const p = await d.path();
      return { name: d.suggestedFilename(), buf: fs.readFileSync(p!) };
    };
    const png = await dl(/Summary PNG/);
    expect(png.name).toBe('demo-10x3_summary.png');
    expect(png.buf.subarray(1, 4).toString()).toBe('PNG');
    expect(png.buf.length).toBeGreaterThan(20_000);
    fs.writeFileSync(path.join(SHOTS, 'export-summary.png'), png.buf);
    const sum = await dl(/Summary CSV/);
    expect(sum.buf.toString()).toMatch(/^metric,value\nsession_id,demo-10x3\nstrikes,\d+/);
    expect(sum.buf.toString()).toContain('max_peak_g_clipped');
    expect(sum.buf.toString()).toContain('mean_peak_g_unclipped');
    // compatibility aliases for the pre-review-1 names
    const clipped = sum.buf.toString().match(/\nclipped_strikes,(\d+)/)![1];
    expect(sum.buf.toString()).toContain(`\nsaturated_strikes,${clipped}`);
    expect(sum.buf.toString()).toMatch(/\nmax_peak_g_is_lower_bound,(true|false)/);
    const evs = await dl(/All events CSV/);
    const lines = evs.buf.toString().trim().split('\n');
    expect(lines[0]).toContain(',peak_g,clipped,peak_g_text,peak_g_is_lower_bound,');
    expect(lines[0].endsWith(',device_id')).toBe(true);
    expect(lines.some((l) => /,true,>=[\d.]+,true,/.test(l))).toBe(true);
    expect(lines.some((l) => l.endsWith(',boxtrk-lead-7c1e'))).toBe(true);
    expect(lines.length).toBeGreaterThan(100);
    expect(evs.buf.toString()).not.toContain('kick_or_body_movement'); // excluded by default
  });

  test('trends compare multiple sessions', async ({ page }) => {
    await loadDemo(page);
    await tab(page, 'Trends');
    await expect(page.getByRole('region', { name: 'Personal bests' })).toBeVisible();
    await expect(page.getByText('Peak-g trend')).toBeVisible();
    await expect(page.locator('.mixrow')).toHaveCount(5);
    await expect(page.getByRole('combobox', { name: 'Session A' })).toBeVisible();
    // "power" must never be used as a metric label (only peak g / estimated speed)
    for (const t of await page.locator('h1, h2, h3, .lab, th').allInnerTexts()) expect(t).not.toMatch(/power|force/i);
  });
});

test.describe('loading files', () => {
  test('file picker groups raw + session + labels', async ({ page }) => {
    const c = watchConsole(page);
    await page.goto('/?view=lab');
    await page.getByLabel('Choose session files').setInputFiles([fix('single-hand_session.json'), fix('single-hand_raw.csv.gz'), fix('single-hand_labels.csv')]);
    await expect(page.locator('.meta h1')).toHaveText('single-hand');
    await expect(page.locator('.meta .badge', { hasText: 'video labels' })).toBeVisible();
    await page.screenshot({ path: path.join(SHOTS, 'single-hand-overview.png'), fullPage: true });
    await tab(page, 'Accuracy');
    await expect(page.getByText('Confusion matrix')).toBeVisible();
    c.assertClean();
  });

  test('simulated drag-and-drop loads files', async ({ page }) => {
    const c = watchConsole(page);
    await page.goto('/?view=lab');
    const files = ['heavy-sat_session.json', 'heavy-sat_raw.csv.gz'].map((n) => ({ name: n, b64: fs.readFileSync(fix(n)).toString('base64') }));
    await page.evaluate(async (fs) => {
      const dt = new DataTransfer();
      for (const f of fs) {
        const bin = Uint8Array.from(atob(f.b64), (ch) => ch.charCodeAt(0));
        dt.items.add(new File([bin], f.name));
      }
      window.dispatchEvent(new DragEvent('dragenter', { dataTransfer: dt }));
      window.dispatchEvent(new DragEvent('drop', { dataTransfer: dt, cancelable: true }));
    }, files);
    await expect(page.locator('.meta h1')).toHaveText('heavy-sat');
    await expect(page.getByText(/of samples are saturated/)).toBeVisible();
    // one severity scheme: card, panel and banner agree
    const lvl = (await page.locator('.dq-banner .alert', { hasText: 'clipped' }).getAttribute('class'))!.includes('bad') ? 'bad' : 'warn';
    await expect(page.locator('.stat', { has: page.locator('.lab', { hasText: /^Clipped strikes/ }) })).toHaveClass(new RegExp(lvl));
    await expect(page.locator('section[aria-label="Data quality"] .item b').first()).toHaveClass(new RegExp(lvl));
    await expect(page.locator('.stat', { hasText: 'Max peak' })).toContainText('≥');
    await page.screenshot({ path: path.join(SHOTS, 'heavy-saturation.png'), fullPage: true });
    c.assertClean();
  });

  test('friendly errors for empty, malformed, unknown and wrong-version files', async ({ page }) => {
    await page.goto('/?view=lab');
    await page.getByLabel('Choose session files').setInputFiles([fix('empty_raw.csv'), fix('malformed_raw.csv'), fix('garbage.csv'), fix('future_session.json'), fix('broken_session.json')]);
    const alert = page.getByRole('alert');
    await expect(alert).toContainText('file is empty');
    await expect(alert).toContainText('missing column');
    await expect(alert).toContainText('unrecognised file');
    await expect(alert).toContainText('schema_version "2.0.0" is not supported');
    await expect(alert).toContainText('missing required field "stance"');
    await expect(alert).toContainText('punches.0.type must be one of');
    await page.screenshot({ path: path.join(SHOTS, 'errors.png') });
  });

  test('missing labels: accuracy view explains what to do', async ({ page }) => {
    await page.goto('/?view=lab');
    await page.getByLabel('Choose session files').setInputFiles([fix('heavy-sat_session.json')]);
    await tab(page, 'Accuracy');
    await expect(page.getByText('No labels loaded')).toBeVisible();
    await tab(page, 'Signals');
    await expect(page.getByText('No raw data')).toBeVisible();
  });

  test('zero strikes renders cleanly', async ({ page }) => {
    const c = watchConsole(page);
    await page.goto('/?view=lab');
    await page.getByLabel('Choose session files').setInputFiles([fix('idle_session.json'), fix('idle_raw.csv.gz')]);
    await expect(page.locator('.stat', { hasText: 'Strikes' }).first()).toContainText('0');
    await tab(page, 'Signals');
    await expect(page.getByText('Raw signals')).toBeVisible();
    await tab(page, 'Strikes');
    await expect(page.getByText('No events match the filters.')).toBeVisible();
    c.assertClean();
  });
});

for (const vp of [{ w: 375, h: 812 }, { w: 390, h: 844 }, { w: 414, h: 896 }, { w: 820, h: 1180 }]) {
  test(`responsive ${vp.w}px: no horizontal overflow on any view`, async ({ browser }) => {
    const page = await browser.newPage({ viewport: { width: vp.w, height: vp.h }, deviceScaleFactor: 2, isMobile: vp.w < 500, hasTouch: vp.w < 500 });
    const c = watchConsole(page);
    await loadDemo(page);
    await noHorizontalOverflow(page);
    const name = vp.w < 500 ? `phone-${vp.w}` : `tablet-${vp.w}`;
    await page.screenshot({ path: path.join(SHOTS, `${name}-overview.png`), fullPage: vp.w >= 500 });
    for (const t of ['Signals', 'Strikes', 'Trends', 'Accuracy', 'Live', 'Why this is different']) {
      await tab(page, t);
      await page.waitForTimeout(250);
      await noHorizontalOverflow(page);
      if (vp.w === 390 || vp.w === 820) await page.screenshot({ path: path.join(SHOTS, `${name}-${t.split(' ')[0].toLowerCase()}.png`), fullPage: vp.w >= 500 });
    }
    c.assertClean();
    await page.close();
  });
}
