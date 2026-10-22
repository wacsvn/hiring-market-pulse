import { expect, test } from '@playwright/test';

// Smoke test of the deployed dashboard. Runs only when LIVE_URL is set (see live-smoke.yml).
// Live numbers change daily, so this checks that everything renders, not specific values.
const LIVE_URL = process.env.LIVE_URL;

test.describe('live dashboard', () => {
  test.skip(!LIVE_URL, 'LIVE_URL not set');

  test('loads, shows a passing data-quality banner, and renders every tab', async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', (e) => errors.push(e.message));
    // Streamlit Cloud serves the bare app at /~/+/ (the root wraps it in an iframe).
    await page.goto(`${LIVE_URL!.replace(/\/$/, '')}/~/+/`, { timeout: 120_000 });
    const wake = page.getByRole('button', { name: /get this app back up/i });
    if (await wake.isVisible().catch(() => false)) await wake.click(); // app slept
    await expect(page.getByText(/Latest complete month/)).toBeVisible({ timeout: 180_000 });

    await expect(page.locator('.st-key-trust-banner')).toContainText('data-quality checks passed');
    for (const key of ['posts', 'remote', 'salary-share', 'median-salary']) {
      await expect(page.locator(`.st-key-kpi-${key} [data-testid="stMetricValue"]`)).not.toBeEmpty();
    }
    for (const tab of ['Skills & roles', 'Salaries', 'HN vs official data', 'Data quality']) {
      await page.getByRole('tab', { name: tab }).click();
      await expect(page.getByRole('tab', { name: tab })).toHaveAttribute('aria-selected', 'true');
    }
    await expect(page.locator('[data-testid="stException"]')).toHaveCount(0);
    expect(errors).toEqual([]);
  });
});
