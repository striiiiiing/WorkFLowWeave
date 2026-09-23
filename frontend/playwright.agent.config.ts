import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './tests/e2e',
  testMatch: '**/agent.spec.ts',
  fullyParallel: false,
  workers: 1,
  timeout: 60_000,
  use: { baseURL: 'http://127.0.0.1:13001', trace: 'retain-on-failure' },
  webServer: [
    {
      command: '../.venv/bin/python tests/serve_agent_backend.py',
      url: 'http://127.0.0.1:14301/api/health',
      timeout: 60_000,
    },
    {
      command: 'npm run dev -- --host 127.0.0.1 --port 13001 --strictPort',
      url: 'http://127.0.0.1:13001',
      env: { API_TARGET: 'http://127.0.0.1:14301' },
      timeout: 60_000,
    },
  ],
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
})
