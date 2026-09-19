import { defineConfig, devices } from '@playwright/test'
export default defineConfig({
  testDir: './tests/e2e',
  testMatch: '**/frontend.spec.ts',
  fullyParallel: false,
  workers: 1,
  timeout: 60_000,
  use: { baseURL: 'http://127.0.0.1:13000', trace: 'retain-on-failure' },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: [
    {
      command: '../.venv/bin/python tests/serve_backend.py',
      url: 'http://127.0.0.1:14300/api/health',
      timeout: 60_000,
    },
    {
      command: 'npm run preview -- --host 127.0.0.1 --port 13000 --strictPort',
      url: 'http://127.0.0.1:13000',
      env: { API_TARGET: 'http://127.0.0.1:14300' },
      timeout: 60_000,
    },
  ],
})
