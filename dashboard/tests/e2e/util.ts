import { expect, type Page } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';

export const FIX = path.resolve('tests/e2e/.fixtures');
export const SHOTS = path.resolve('screenshots');
fs.mkdirSync(SHOTS, { recursive: true });

/** Collect console errors/warnings and page errors; assert none at the end. */
export function watchConsole(page: Page) {
  const errors: string[] = [];
  page.on('console', (m) => { if (m.type() === 'error' || m.type() === 'warning') errors.push(`${m.type()}: ${m.text()}`); });
  page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`));
  return { errors, assertClean: () => expect(errors, errors.join('\n')).toEqual([]) };
}
export async function loadDemo(page: Page) {
  await page.goto('/?demo');
  await expect(page.getByText('Strikes per round')).toBeVisible();
}
export async function tab(page: Page, name: string) {
  await page.getByRole('navigation', { name: 'Views' }).getByRole('button', { name, exact: true }).click();
}
export async function noHorizontalOverflow(page: Page) {
  const [sw, w] = await page.evaluate(() => [document.documentElement.scrollWidth, window.innerWidth]);
  expect(sw, `page is ${sw}px wide in a ${w}px viewport`).toBeLessThanOrEqual(w + 1);
}
export function fix(name: string) { return path.join(FIX, name); }
