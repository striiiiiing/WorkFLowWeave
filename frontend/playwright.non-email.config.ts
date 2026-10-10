import { defineConfig } from '@playwright/test'
import channels from './playwright.channels.config'

export default defineConfig({
  ...channels,
  testMatch: [
    '**/channels-headless.spec.ts',
    '**/channels-non-email.spec.ts',
    '**/channel-handshake.spec.ts',
  ],
  grepInvert: /web\/email\/file/,
  outputDir: './test-results/non-email-channels',
  use: { ...channels.use, baseURL: 'http://127.0.0.1:13021' },
  webServer: [
    {
      command: '../.venv/bin/python tests/serve_agent_backend.py',
      url: 'http://127.0.0.1:14321/api/health',
      reuseExistingServer: false,
      env: { WORKFLOWWEAVE_E2E_BACKEND_PORT: '14321', PYTHONPATH: '..' },
      timeout: 60_000,
    },
    {
      command: 'npm run preview -- --host 127.0.0.1 --port 13021 --strictPort',
      url: 'http://127.0.0.1:13021',
      reuseExistingServer: false,
      env: { API_TARGET: 'http://127.0.0.1:14321' },
      timeout: 60_000,
    },
  ],
})
