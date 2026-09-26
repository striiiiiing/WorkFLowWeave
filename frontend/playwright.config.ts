import { defineConfig, devices } from '@playwright/test'
const backendPort = process.env.LOGAGENT_E2E_BACKEND_PORT || '14300'
const frontendPort = process.env.LOGAGENT_E2E_FRONTEND_PORT || '13000'
const backendURL = `http://127.0.0.1:${backendPort}`
const frontendURL = `http://127.0.0.1:${frontendPort}`
export default defineConfig({
  testDir: './tests/e2e',
  testMatch: [
    '**/frontend.spec.ts',
    '**/resources.spec.ts',
    '**/monitoring.spec.ts',
    '**/agent-ui.spec.ts',
  ],
  fullyParallel: false,
  workers: 1,
  timeout: 60_000,
  use: { baseURL: frontendURL, trace: 'retain-on-failure' },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: [
    {
      command: '../.venv/bin/python tests/serve_backend.py',
      url: `${backendURL}/api/health`,
      env: { LOGAGENT_E2E_BACKEND_PORT: backendPort },
      timeout: 60_000,
    },
    {
      command: `npm run preview -- --host 127.0.0.1 --port ${frontendPort} --strictPort`,
      url: frontendURL,
      env: { API_TARGET: backendURL },
      timeout: 60_000,
    },
  ],
})
