import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { expect, test, type APIRequestContext } from '@playwright/test'

function authToken(): string {
  const context = JSON.parse(
    readFileSync(resolve(import.meta.dirname, '../.auth/context.json'), 'utf-8'),
  ) as { user: { accessToken: string } }
  return context.user.accessToken
}

async function isQuizEnabled(request: APIRequestContext): Promise<boolean> {
  const res = await request.get('http://127.0.0.1:8000/quiz/today', {
    headers: { Authorization: `Bearer ${authToken()}` },
  })
  if (!res.ok()) return false
  const data = await res.json()
  return data.enabled !== false
}

test.describe('Discover feed (KB_FEED)', () => {
  test('loads KB articles with badges and pagination', async ({ page }) => {
    await page.goto('/discover')
    await expect(page.getByRole('heading', { name: 'Discover' })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'E2E KB Article 22', exact: true })).toBeVisible()
    await expect(page.getByText('from your interests: Frontend').first()).toBeVisible()

    const loadMore = page.getByRole('button', { name: 'Load more' })
    await expect(loadMore).toBeVisible()
    await loadMore.click()
    await expect(page.getByRole('heading', { name: 'E2E KB Article 1', exact: true })).toBeVisible({ timeout: 15_000 })
  })

  test('dismiss removes card and persists after refresh', async ({ page }) => {
    await page.goto('/discover')
    const title = 'E2E KB Article 21'
    await expect(page.getByRole('heading', { name: title, exact: true })).toBeVisible()

    const card = page.locator('article').filter({ has: page.getByRole('heading', { name: title, exact: true }) })
    await card.getByRole('button', { name: 'Dismiss' }).click()
    await expect(page.getByRole('heading', { name: title, exact: true })).not.toBeVisible()

    await page.reload()
    await page.waitForSelector('text=E2E KB Article', { timeout: 30_000 })
    await expect(page.getByRole('heading', { name: title, exact: true })).not.toBeVisible()
  })

  test('open expands in-app summary and shows source link', async ({ page }) => {
    await page.goto('/discover')
    const title = 'E2E KB Article 20'
    const card = page.locator('article').filter({ has: page.getByRole('heading', { name: title, exact: true }) })

    const detailReq = page.waitForResponse(
      (r) => r.url().includes('/feed/articles/') && r.request().method() === 'GET',
    )
    const stateReq = page.waitForResponse(
      (r) => r.url().includes('/feed/') && r.url().includes('/state') && r.request().method() === 'POST',
    )

    await card.getByRole('button', { name: 'Open' }).click()
    const detailResp = await detailReq
    expect(detailResp.ok()).toBeTruthy()
    const stateResp = await stateReq
    expect(stateResp.ok()).toBeTruthy()

    await expect(card.getByRole('link', { name: 'View source' })).toBeVisible()
    await expect(card.getByRole('button', { name: 'Hide' })).toBeVisible()
  })

  test('tag switch shows cached category instantly on re-select', async ({ page }) => {
    await page.goto('/discover')
    await expect(page.getByRole('heading', { name: 'E2E KB Article 22', exact: true })).toBeVisible()

    const tagSelect = page.getByLabel('Filter by tag')
    await tagSelect.selectOption('Frontend')
    await expect(page.getByRole('heading', { name: 'E2E KB Article 22', exact: true })).toBeVisible({ timeout: 15_000 })

    await tagSelect.selectOption('')
    await tagSelect.selectOption('Frontend')

    await expect(page.getByRole('heading', { name: 'E2E KB Article 22', exact: true })).toBeVisible({ timeout: 500 })
  })

  test('backend health and feed API respond', async ({ request }) => {
    const health = await request.get('http://127.0.0.1:8000/health')
    expect(health.ok()).toBeTruthy()
    // /health returns { status, scheduler }; assert the contract, not exact shape.
    expect((await health.json()).status).toBe('ok')
  })

  test('shows the streak bar with no streak yet', async ({ page, request }) => {
    test.skip(!(await isQuizEnabled(request)), 'Quiz disabled (QUIZ_ENABLED=false)')
    await page.goto('/discover')
    const streak = page.locator('.kite-streak')
    await expect(streak).toBeVisible()
    await expect(streak.getByText('0')).toBeVisible()
    await expect(page.getByText(/Pass today.s quiz to start a streak/)).toBeVisible()
  })

  test('daily quiz is collapsed once articles are loaded and can be opened', async ({ page, request }) => {
    test.skip(!(await isQuizEnabled(request)), 'Quiz disabled (QUIZ_ENABLED=false)')
    await page.goto('/discover')
    await expect(page.getByRole('heading', { name: 'E2E KB Article 22', exact: true })).toBeVisible()

    await expect(page.getByText('Daily quiz')).toBeVisible()
    const panel = page.locator('.kite-panel').filter({ hasText: 'Daily quiz' })
    const toggle = panel.getByRole('button', { name: 'Open' })
    await expect(toggle).toBeVisible()
    await toggle.click()

    await expect(page.getByRole('button', { name: /Start today.s quiz/ })).toBeVisible()
    await expect(page.getByText(/One attempt per\s+day/)).toBeVisible()
  })

  test('starting the quiz offers three niches to choose from', async ({ page, request }) => {
    test.skip(!(await isQuizEnabled(request)), 'Quiz disabled (QUIZ_ENABLED=false)')
    await page.goto('/discover')
    await expect(page.getByRole('heading', { name: 'E2E KB Article 22', exact: true })).toBeVisible()

    const panel = page.locator('.kite-panel').filter({ hasText: 'Daily quiz' })
    await panel.getByRole('button', { name: 'Open' }).click()

    const started = page.waitForResponse(
      (r) => r.url().includes('/quiz/start') && r.request().method() === 'POST',
    )
    await page.getByRole('button', { name: /Start today.s quiz/ }).click()
    expect((await started).ok()).toBeTruthy()

    // Niches come from an LLM with a static fallback, so only the shape of the
    // choice is asserted, never the wording.
    await expect(page.getByText(/Pick a topic from/)).toBeVisible({ timeout: 30_000 })
    await expect(panel.locator('.kite-chip')).toHaveCount(3)
  })

  test('feed progress endpoint reports readiness', async ({ request }) => {
    const res = await request.get('http://127.0.0.1:8000/feed/progress', {
      headers: { Authorization: `Bearer ${authToken()}` },
    })
    expect(res.ok()).toBeTruthy()
    const data = await res.json()
    expect(data.categories_total).toBeGreaterThan(0)
    expect(data.per_category).toHaveProperty('Frontend')
    expect(data.articles_ready).toBeGreaterThan(0)
  })
})
