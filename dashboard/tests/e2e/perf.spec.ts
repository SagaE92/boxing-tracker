import { expect, test } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { SHOTS, fix, tab, watchConsole } from './util';

// 1 h at 416 Hz (~1.49M samples). Records timings to screenshots/perf.json.
test('1 h session: load, render and zoom stay interactive', async ({ page }) => {
  test.setTimeout(300_000);
  const c = watchConsole(page);
  await page.goto('/?view=lab');
  const t0 = Date.now();
  await page.getByLabel('Choose session files').setInputFiles([fix('long-1h_session.json'), fix('long-1h_raw.csv.gz')]);
  await expect(page.locator('.meta h1')).toHaveText('long-1h', { timeout: 120_000 });
  await expect(page.getByText('Strikes per round')).toBeVisible();
  const loadMs = Date.now() - t0;
  const samples = await page.locator('.meta').innerText();
  const t1 = Date.now();
  await tab(page, 'Signals');
  await expect(page.getByText(/pts drawn \(1,4\d\d,\d{3} samples\)/)).toBeVisible({ timeout: 60_000 });
  const signalsMs = Date.now() - t1;
  const firstRange = await page.evaluate(() => (window as unknown as { __lastRangeMs: number }).__lastRangeMs);
  const rangeCalls = await page.evaluate(() => (window as unknown as { __rangeCalls: number }).__rangeCalls);
  // Zoom in 6 steps with the button and time each decimation + redraw.
  const zooms: number[] = [];
  for (let i = 0; i < 6; i++) {
    await page.getByRole('button', { name: 'Zoom in' }).click();
    await page.waitForTimeout(50);
    zooms.push(await page.evaluate(() => (window as unknown as { __lastRangeMs: number }).__lastRangeMs));
  }
  // Wheel zoom/pan on the plot
  const over = page.locator('.u-over').nth(1);
  await over.hover();
  const t2 = Date.now();
  for (let i = 0; i < 10; i++) await page.mouse.wheel(0, i % 2 ? 120 : -120);
  const wheelMs = Date.now() - t2;
  const mem = await page.evaluate(() => (performance as unknown as { memory?: { usedJSHeapSize: number } }).memory?.usedJSHeapSize ?? null);
  await page.screenshot({ path: path.join(SHOTS, 'perf-1h-signals.png'), fullPage: false });
  const res = { samples_hint: samples.slice(0, 80), loadMs, signalsMs, rangeCallsOnOpen: rangeCalls, firstRangeMs: firstRange, zoomMs: zooms, wheel10Ms: wheelMs, jsHeapMB: mem ? +(mem / 1048576).toFixed(1) : null };
  fs.writeFileSync(path.join(SHOTS, 'perf.json'), JSON.stringify(res, null, 2));
  console.log('PERF', JSON.stringify(res));
  expect(rangeCalls, 'decimation should run once or twice when opening Signals (guards against effect loops)').toBeLessThanOrEqual(3);
  expect(signalsMs).toBeLessThan(5000);
  expect(Math.max(...zooms)).toBeLessThan(250);
  expect(firstRange).toBeLessThan(500);
  if (mem) expect(mem / 1048576).toBeLessThan(600);
  c.assertClean();
});
