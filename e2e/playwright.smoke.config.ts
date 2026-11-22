import { defineConfig, devices } from '@playwright/test'

// Read-only smoke config for deployed environments (no local servers, no auth/seed project).
// Usage: PLAYWRIGHT_BASE_URL=https://... PLAYWRIGHT_API_BASE=https://... npx playwright test -c playwright.smoke.config.ts
const baseURL = process.env.PLAYWRIGHT_BASE_URL
if (!baseURL) throw new Error('PLAYWRIGHT_BASE_URL is required for smoke tests')

export default defineConfig({
  testDir: './smoke',
  retries: 2, // cold starts on free-tier hosting
  workers: 1,
  timeout: 90_000,
  reporter: process.env.CI
    ? [['list'], ['html', { open: 'never' }], ['junit', { outputFile: 'test-results/smoke-junit.xml' }]]
    : [['list']],
  use: {
    baseURL,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    extraHTTPHeaders: process.env.VERCEL_PROTECTION_BYPASS
      ? { 'x-vercel-protection-bypass': process.env.VERCEL_PROTECTION_BYPASS }
      : undefined,
  },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'] } },
    { name: 'mobile', use: { ...devices['Pixel 7'] } },
  ],
})
