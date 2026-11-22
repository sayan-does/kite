import { defineConfig, devices } from '@playwright/test'

const baseURL = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:5173'
// When PLAYWRIGHT_BASE_URL is set we are testing an already-deployed environment
// (Vercel preview/production + Render API), so no local servers are started.
const useRemote = !!process.env.PLAYWRIGHT_BASE_URL
const isCI = !!process.env.CI

export default defineConfig({
  testDir: './tests',
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  // One retry even locally: specs run against a live Supabase + a cold backend,
  // so first-load DB warmup can race a 5s assertion (e.g. Settings sections).
  retries: 1,
  workers: 1,
  reporter: isCI
    ? [['list'], ['html', { open: 'never' }], ['junit', { outputFile: 'test-results/junit.xml' }]]
    : [['list'], ['html', { open: 'never' }]],
  timeout: 60_000,
  globalTeardown: './global-teardown.ts',
  use: {
    baseURL,
    // Vercel Deployment Protection bypass for CI preview URLs (optional).
    extraHTTPHeaders: process.env.VERCEL_PROTECTION_BYPASS
      ? { 'x-vercel-protection-bypass': process.env.VERCEL_PROTECTION_BYPASS }
      : undefined,
    trace: 'on-first-retry',
    video: 'retain-on-failure',
    screenshot: 'only-on-failure',
    // Deterministic interactions: Kite's CSS disables transforms/animations
    // under reduced motion, so clicks never race a mid-flight transition.
    reducedMotion: 'reduce',
  },
  projects: [
    { name: 'setup', testMatch: /auth\.setup\.ts/, use: { storageState: { cookies: [], origins: [] } } },
    {
      name: 'chromium',
      testIgnore: [/auth\.setup\.ts/, /onboarding\.spec\.ts/],
      use: { ...devices['Desktop Chrome'], storageState: '.auth/user.json', viewport: { width: 390, height: 844 } },
      dependencies: ['setup'],
    },
    {
      name: 'onboarding',
      testMatch: /onboarding\.spec\.ts/,
      use: { ...devices['Desktop Chrome'], storageState: { cookies: [], origins: [] } },
    },
  ],
  webServer: useRemote ? undefined : [
    {
      command: 'cd ../backend && .venv\\Scripts\\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000',
      url: 'http://127.0.0.1:8000/health',
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      env: {
        ...process.env,
        KB_FEED: 'true',
      },
    },
    {
      command: 'npm run dev -- --host 127.0.0.1 --port 5173',
      cwd: '../frontend',
      url: 'http://127.0.0.1:5173',
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
  ],
})
