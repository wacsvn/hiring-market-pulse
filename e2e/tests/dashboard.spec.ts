import { expect, test } from '@playwright/test';
import { byKey, chart, openDashboard, openTab, traces, waitForIdle } from './helpers';

// Expected values come from the frozen fixture marts in tests/fixtures/marts
// (14 monthly threads of 10-15 posts; Oct 2026 is the incomplete month). If the fixtures are
// regenerated these numbers change on purpose, and these tests must be updated with them.

test.describe('overview', () => {
  test('renders without errors or Python exceptions', async ({ page }) => {
    const errors = await openDashboard(page);
    await expect(page.locator('[data-testid="stException"]')).toHaveCount(0);
    expect(errors).toEqual([]);
  });

  test('trust banner reports the last data-quality run', async ({ page }) => {
    await openDashboard(page);
    await expect(byKey(page, 'trust-banner')).toContainText(
      '51 of 52 data-quality checks passed',
    );
    await expect(byKey(page, 'trust-banner')).toContainText('1 flagged for review');
  });

  test('KPIs show the latest complete month vs a year earlier', async ({ page }) => {
    await openDashboard(page);
    await expect(page.getByText('Latest complete month: September 2026')).toBeVisible();
    const kpi = (key: string) => byKey(page, `kpi-${key}`);
    await expect(kpi('posts').getByTestId('stMetricValue')).toHaveText('10');
    await expect(kpi('remote').getByTestId('stMetricValue')).toHaveText('60%');
    await expect(kpi('remote').getByTestId('stMetricDelta')).toContainText('+0 pts');
    await expect(kpi('salary-share').getByTestId('stMetricValue')).toHaveText('20%');
    await expect(kpi('salary-share').getByTestId('stMetricDelta')).toContainText('+10 pts');
    await expect(kpi('median-salary').getByTestId('stMetricValue')).toHaveText('$180,000');
    await expect(kpi('median-salary').getByTestId('stMetricDelta')).toContainText('+10,000 USD');
  });

  test('posts-per-month chart leaves out the incomplete month', async ({ page }) => {
    await openDashboard(page);
    const [posts] = await traces(chart(page, 'chart-postings'));
    expect(posts.x).toHaveLength(13);
    expect(String(posts.x.at(-1))).toContain('2026-09-01');
  });

  test('narrowing the month range narrows the charts', async ({ page }) => {
    await openDashboard(page);
    const before = (await traces(chart(page, 'chart-work-mode')))[0].points;
    const startThumb = page.getByRole('slider', { name: 'Months shown — start' });
    await startThumb.focus();
    await startThumb.press('ArrowRight');
    await startThumb.press('ArrowRight');
    await waitForIdle(page);
    await expect
      .poll(async () => (await traces(chart(page, 'chart-work-mode')))[0].points)
      .toBe(before - 2);
  });
});

test.describe('skills & roles', () => {
  test('tech colors follow the technology, not its position', async ({ page }) => {
    await openDashboard(page);
    await openTab(page, 'Skills & roles');
    const compare = chart(page, 'chart-tech-compare');
    const colorsBefore = Object.fromEntries((await traces(compare)).map((t) => [t.name, t.color]));
    const names = Object.keys(colorsBefore);
    expect(names.length).toBe(3);

    // Remove the first selected technology; the others must keep their colors.
    const picker = page.locator('.st-key-tech-picker');
    await picker.getByRole('button', { name: `Remove ${names[0]}` }).click();
    await waitForIdle(page);
    await expect.poll(async () => (await traces(compare)).length).toBe(2);
    for (const t of await traces(compare)) {
      expect(t.color, `${t.name} was repainted`).toBe(colorsBefore[t.name]);
    }
  });

  test('movers chart and roles table render', async ({ page }) => {
    await openDashboard(page);
    await openTab(page, 'Skills & roles');
    const [bars] = await traces(chart(page, 'chart-tech-movers'));
    expect(bars.points).toBeGreaterThan(3);
    await expect(page.locator('.st-key-table-roles')).toBeVisible();
  });
});

test.describe('salaries', () => {
  test('small groups are hidden until the reader opts in', async ({ page }) => {
    await openDashboard(page);
    await openTab(page, 'Salaries');
    // Fixture data is too thin for any group to reach 20 posts with a salary.
    await expect(page.getByText('No group has enough posts with a salary yet.')).toBeVisible();
    await byKey(page, 'reliable-toggle').locator('label').click();
    await waitForIdle(page);
    const [range] = await traces(chart(page, 'chart-salary-bands'));
    expect(range.points).toBeGreaterThan(0);
  });
});

test.describe('HN vs official data', () => {
  test('benchmark compares both series on one indexed axis', async ({ page }) => {
    await openDashboard(page);
    await openTab(page, 'HN vs official data');
    const names = (await traces(chart(page, 'chart-benchmark'))).map((t) => t.name);
    expect(names).toEqual(
      expect.arrayContaining(['HN posts', 'JOLTS openings', 'Months the two moved very differently']),
    );
    await expect(byKey(page, 'lead-lag')).toContainText('Strongest month-over-month correlation');
  });
});

test.describe('data quality', () => {
  test('quarantined rows are listed with their reason', async ({ page }) => {
    await openDashboard(page);
    await openTab(page, 'Data quality');
    await expect(page.locator('.st-key-table-quarantine')).toBeVisible();
    await expect(page.getByText('Not passing: warn_hn_jolts_divergence')).toBeVisible();
  });
});

test.describe('empty state', () => {
  test('explains how to publish data instead of crashing', async ({ page }) => {
    await page.goto('http://localhost:8602/');
    await expect(byKey(page, 'empty-state')).toContainText('No data has been published yet');
    await expect(page.locator('[data-testid="stException"]')).toHaveCount(0);
  });
});
