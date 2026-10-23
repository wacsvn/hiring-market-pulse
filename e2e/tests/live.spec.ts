import { expect, test } from '@playwright/test';

// Smoke test of the deployed dashboard. Runs only when LIVE_URL is set (see live-smoke.yml).
// Live numbers change daily, so this checks that everything renders, not specific values.
const LIVE_URL = process.env.LIVE_URL;

test.describe('live dashboard', () => {
  test.skip(!LIVE_URL, 'LIVE_URL not set');
  // Waking a sleeping app can take a few minutes on Streamlit Community Cloud.
  test.setTimeout(8 * 60_000);

  test('loads, shows a passing data-quality banner, and renders every tab', async ({ page }) => {
    // Visit the public page, as a reader would. Free Streamlit apps sleep after ~12 hours
    // without visitors and show a "wake up" button on this page (the bare app URL just stays
    // blank), so press it if it's there. This visit is also what keeps the app awake.
    await page.goto(LIVE_URL!, { timeout: 120_000 });
    const wake = page.getByRole('button', { name: /get this app back up/i });
    if (await wake.isVisible({ timeout: 15_000 }).catch(() => false)) await wake.click();

    const app = page.frameLocator('iframe[title="streamlitApp"]');
    await expect(app.locator('.st-key-kpi-posts')).toBeVisible({ timeout: 300_000 });
    await expect(app.locator('.st-key-trust-banner')).toContainText('data checks passed');
    for (const key of ['posts', 'remote', 'salary-share', 'median-salary']) {
      await expect(app.locator(`.st-key-kpi-${key} [data-testid="stMetricValue"]`)).not.toBeEmpty();
    }
    for (const tab of ['Skills & roles', 'Salaries', 'HN vs official data', 'Data quality']) {
      await app.getByRole('tab', { name: tab }).click();
      await expect(app.getByRole('tab', { name: tab })).toHaveAttribute('aria-selected', 'true');
    }
    await expect(app.locator('[data-testid="stException"]')).toHaveCount(0);
  });
});
