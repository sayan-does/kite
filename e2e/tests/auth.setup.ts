import { test as setup } from '@playwright/test'
import { mkdirSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { requireEnv } from '../helpers/env'
import { createE2EUser, injectSession, seedKbArticles } from '../helpers/seed'

setup('authenticate and seed KB feed', async ({ page }) => {
  requireEnv()

  const user = await createE2EUser(true)
  const articleIds = await seedKbArticles(22)

  await injectSession(page, user)
  await page.goto('/discover')
  await page.waitForSelector('text=E2E KB Article', { timeout: 30_000 })

  const authDir = resolve(import.meta.dirname, '../.auth')
  mkdirSync(authDir, { recursive: true })
  await page.context().storageState({ path: resolve(authDir, 'user.json') })
  writeFileSync(resolve(authDir, 'context.json'), JSON.stringify({ user, articleIds }, null, 2))
})
