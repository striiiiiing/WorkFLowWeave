import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './tests/e2e',
  testMatch: '**/channel-onboarding.spec.ts',
  workers: 1,
  timeout: 90_000,
  expect: { timeout: 10_000 },
  use: {
    actionTimeout: 10_000,
    baseURL: process.env.CHANNEL_ONBOARDING_URL || 'http://127.0.0.1:3002',
    trace: 'retain-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
})
