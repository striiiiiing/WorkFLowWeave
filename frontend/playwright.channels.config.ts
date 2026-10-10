import { defineConfig, devices } from '@playwright/test'

const backendURL = 'http://127.0.0.1:14300'
const frontendURL = 'http://127.0.0.1:13000'

export default defineConfig({
  testDir: './tests/e2e',
  testMatch: '**/channels-headless.spec.ts',
  fullyParallel: false,
  workers: 1,
  timeout: 60_000,
  expect: { timeout: 12_000 },
  outputDir: './test-results/headless-channels',
  use: {
    baseURL: frontendURL,
    launchOptions: { headless: true },
    trace: 'retain-on-failure',
    screenshot: 'off',
  },
  webServer: [
    {
      command: '../.venv/bin/python tests/serve_agent_backend.py',
      url: `${backendURL}/api/health`,
      reuseExistingServer: true,
      env: { WORKFLOWWEAVE_E2E_BACKEND_PORT: '14300', PYTHONPATH: '..' },
      timeout: 60_000,
    },
    {
      command: 'npm run preview -- --host 127.0.0.1 --port 13000 --strictPort',
      url: frontendURL,
      reuseExistingServer: true,
      env: { API_TARGET: backendURL },
      timeout: 60_000,
    },
  ],
  projects: [{ name: 'chromium-headless', use: { ...devices['Desktop Chrome'] } }],
})
