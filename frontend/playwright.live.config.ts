import { defineConfig, devices } from '@playwright/test'

// Deliberately starts no servers: this checks the user's existing application chain.
export default defineConfig({
  testDir: './tests/e2e',
  testMatch: '**/live.spec.ts',
  workers: 1,
  timeout: 60_000,
  use: {
    ...devices['Desktop Chrome'],
    baseURL: process.env.WORKFLOWWEAVE_FRONTEND_URL || 'http://127.0.0.1:3000',
    trace: 'retain-on-failure',
  },
})
