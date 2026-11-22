import { expect, test } from '@playwright/test'

const API = 'http://127.0.0.1:8000'

test.describe('Phase-2 integrations (events + MCP + RSS)', () => {
  test('events API returns events with calendar links', async ({ request }) => {
    const resp = await request.get(`${API}/events?limit=5`)
    expect(resp.ok()).toBeTruthy()
    const body = await resp.json()
    expect(Array.isArray(body.events)).toBeTruthy()
    for (const ev of body.events) {
      expect(ev).toHaveProperty('google_calendar_url')
      expect(ev.google_calendar_url).toContain('calendar.google.com')
    }
  })

  test('events .ics export downloads a calendar', async ({ request }) => {
    const resp = await request.get(`${API}/events.ics`)
    expect(resp.ok()).toBeTruthy()
    expect(resp.headers()['content-type']).toContain('text/calendar')
    expect(await resp.text()).toContain('BEGIN:VCALENDAR')
  })

  test('MCP discovery lists tools; POST requires a token', async ({ request }) => {
    const disco = await request.get(`${API}/mcp`)
    expect(disco.ok()).toBeTruthy()
    expect((await disco.json()).tools).toContain('get_feed')

    const unauth = await request.post(`${API}/mcp`, {
      data: { jsonrpc: '2.0', id: 1, method: 'tools/list' },
    })
    expect(unauth.status()).toBe(401)
  })

  test('Events page renders', async ({ page }) => {
    await page.goto('/events')
    await expect(page.getByRole('heading', { name: 'Tech Events' })).toBeVisible()
    await expect(page.getByRole('link', { name: /Download .ics/ })).toBeVisible()
  })

  test('Settings exposes integrations', async ({ page }) => {
    await page.goto('/settings')
    await expect(page.getByRole('heading', { name: /Integrations/ })).toBeVisible()
  })
})
