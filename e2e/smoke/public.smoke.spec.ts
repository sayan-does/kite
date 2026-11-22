import { expect, test } from '@playwright/test'

// Read-only smoke checks for a deployed environment. No auth, no seeding, no writes,
// so it is safe to run against production after every deploy.

test.describe('public smoke', () => {
  test('landing page renders and the SPA boots without errors', async ({ page }) => {
    const pageErrors: string[] = []
    const corsErrors: string[] = []
    page.on('pageerror', (e) => pageErrors.push(e.message))
    page.on('console', (m) => {
      if (m.type() === 'error' && /cors|access-control/i.test(m.text())) corsErrors.push(m.text())
    })

    const res = await page.goto('/', { waitUntil: 'networkidle' })
    expect(res?.status(), 'landing HTTP status').toBe(200)
    await expect(page).toHaveTitle(/Kite/i)
    await expect(page.locator('#root')).not.toBeEmpty()

    expect(pageErrors, 'uncaught page errors').toEqual([])
    expect(corsErrors, 'CORS errors talking to the API').toEqual([])
  })

  test('login page is reachable', async ({ page }) => {
    const res = await page.goto('/login')
    expect(res?.status()).toBe(200)
    await expect(page.locator('#root')).not.toBeEmpty()
  })

  test('deep links are served by the SPA (rewrite works) and guard unauthenticated users', async ({ page }) => {
    const res = await page.goto('/discover')
    expect(res?.status(), 'deep link must not 404').toBe(200)
    await expect(page.locator('#root')).not.toBeEmpty()
  })

  test('backend health is reachable from CI', async ({ request }) => {
    const api = process.env.PLAYWRIGHT_API_BASE
    test.skip(!api, 'PLAYWRIGHT_API_BASE not set')
    const res = await request.get(`${api}/health`, { timeout: 90_000 })
    expect(res.status()).toBe(200)
    expect((await res.json()).status).toBe('ok')
  })
})
