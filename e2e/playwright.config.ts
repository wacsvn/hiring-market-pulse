import { defineConfig, devices } from '@playwright/test';

// Three app instances: frozen fixture marts (known numbers to assert against), an empty
// directory ("no data yet"), and an unreachable URL (published data can't be fetched).
const app = (port: number, env: Record<string, string>) => ({
  command:
    `uv run streamlit run app/streamlit_app.py --server.port ${port} --server.headless true`,
  cwd: '..',
  env,
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
  webServer: [
    app(8601, { PULSE_MARTS_DIR: 'tests/fixtures/marts' }),
    app(8602, { PULSE_MARTS_DIR: 'tests/fixtures/no-marts' }),
    app(8603, { PULSE_MARTS_URL: 'http://127.0.0.1:9/nothing-here' }), // port 9: refused
  ],
});
