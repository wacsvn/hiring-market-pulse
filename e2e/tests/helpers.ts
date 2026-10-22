import { expect, type Locator, type Page } from '@playwright/test';

/** Open the app and wait until Streamlit has finished its first full render. */
export async function openDashboard(page: Page, path = '/'): Promise<string[]> {
  const consoleErrors: string[] = [];
  page.on('console', (m) => {
    if (m.type() === 'error') consoleErrors.push(m.text());
  });
  page.on('pageerror', (e) => consoleErrors.push(e.message));
  await page.goto(path);
  await expect(page.getByRole('heading', { name: 'Hiring Market Pulse' })).toBeVisible();
  await waitForIdle(page);
  return consoleErrors;
}

/** Streamlit shows a "running" status widget while the script reruns. */
export async function waitForIdle(page: Page): Promise<void> {
  await expect(page.locator('[data-testid="stStatusWidget"]')).toHaveCount(0, { timeout: 30_000 });
}

/** Containers created with st.container(key=...) get the class st-key-<key>. */
export const byKey = (page: Page, key: string): Locator => page.locator(`.st-key-${key}`);

/** A Plotly chart by its Streamlit key. */
export const chart = (page: Page, key: string): Locator =>
  page.locator(`.st-key-${key} .js-plotly-plot`).first();

export type Trace = { name: string; points: number; x: unknown[]; color: unknown };

/**
 * Read the traces Plotly actually rendered, from the chart's DOM node. Point counts come
 * from `calcdata` (Plotly's computed points): numeric arrays reach the browser
 * base64-encoded, so the raw `data` arrays can't be counted directly.
 */
export async function traces(plot: Locator): Promise<Trace[]> {
  await expect(plot).toBeVisible();
  return plot.evaluate((el: any) =>
    (el._fullData ?? []).map((t: any, i: number) => ({
      name: t.name,
      points: (el.calcdata?.[i] ?? []).filter((p: any) => p.x !== undefined || p.s !== undefined)
        .length,
      x: Array.isArray(t.x) ? t.x : [],
      color: t.line?.color ?? t.marker?.color,
    })),
  );
}

export async function openTab(page: Page, name: string): Promise<void> {
  await page.getByRole('tab', { name }).click();
  await expect(page.getByRole('tab', { name })).toHaveAttribute('aria-selected', 'true');
  await waitForIdle(page);
}
