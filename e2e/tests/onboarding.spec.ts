import { expect, test } from '@playwright/test'
import { requireEnv } from '../helpers/env'
import { cleanupE2E, createE2EUser, injectSession } from '../helpers/seed'

test.describe('Onboarding wizard', () => {
  let user: Awaited<ReturnType<typeof createE2EUser>>

  test.beforeAll(async () => {
    requireEnv()
    user = await createE2EUser(false)
  })

  test.afterAll(async () => {
    await cleanupE2E(user, [])
  })

  test('interest selection then skip stack import reaches discover', async ({ page }) => {
    await injectSession(page, user)
    await page.goto('/onboarding')

    await expect(page.getByRole('heading', { name: 'What do you want to stay on top of?' })).toBeVisible()
    await page.getByRole('button', { name: 'Frontend', exact: true }).click()
    await page.getByRole('button', { name: 'Continue' }).click()

    await expect(page.getByRole('heading', { name: 'Import your stack' })).toBeVisible()
    await page.getByRole('button', { name: /Skip/i }).click()

    await expect(page).toHaveURL(/\/discover/)
    await expect(page.getByRole('heading', { name: 'Discover' })).toBeVisible()
  })

  test('offers exactly the seven supported categories', async ({ page }) => {
    await injectSession(page, user)
    await page.goto('/onboarding')

    for (const name of ['Frontend', 'Backend', 'AI/ML', 'DevOps', 'Security', 'Automation', 'Programming Languages']) {
      await expect(page.getByRole('button', { name, exact: true })).toBeVisible()
    }
    for (const name of ['Databases', 'Mobile', 'Cloud Infra', 'Developer Tools']) {
      await expect(page.getByRole('button', { name, exact: true })).toHaveCount(0)
    }
  })

  test('cannot select a fourth category', async ({ page }) => {
    await injectSession(page, user)
    await page.goto('/onboarding')

    await expect(page.getByText('0 of 3 selected.')).toBeVisible()

    for (const name of ['Frontend', 'Backend', 'AI/ML']) {
      await page.getByRole('button', { name, exact: true }).click()
    }
    await expect(page.getByText('3 of 3 selected — deselect one to swap.')).toBeVisible()

    const fourth = page.getByRole('button', { name: 'DevOps', exact: true })
    await expect(fourth).toBeDisabled()

    // Deselecting frees the slot, so a swap is still possible.
    await page.getByRole('button', { name: 'Frontend', exact: true }).click()
    await expect(fourth).toBeEnabled()
    await fourth.click()
    await expect(page.getByText('3 of 3 selected — deselect one to swap.')).toBeVisible()
  })
})
