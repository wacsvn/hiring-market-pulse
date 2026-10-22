import { defineConfig, devices } from '@playwright/test';

// Two app instances: one on frozen fixture marts (known numbers to assert against),
// one pointed at an empty directory to exercise the "no data yet" state.
const app = (port: number, martsDir: string) => ({
  command:
    `uv run streamlit run app/streamlit_app.py --server.port ${port} --server.headless true`,
  cwd: '..',
  env: { PULSE_MARTS_DIR: martsDir },
  url: `http://localhost:${port}/_stcore/health`,
  reuseExistingServer: !process.env.CI,
  timeout: 120_000,
});

export default defineConfig({
  testDir: './tests',
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }], ['junit', { outputFile: 'results/junit.xml' }]] : 'list',
  use: {
    baseURL: 'http://localhost:8601',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'], viewport: { width: 1400, height: 1000 } } }],
  webServer: [app(8601, 'tests/fixtures/marts'), app(8602, 'tests/fixtures/no-marts')],
});
