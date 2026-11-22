import { expect, test } from '@playwright/test'

test.describe('Settings', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/settings')
    await expect(page.getByRole('heading', { name: 'Settings', exact: true })).toBeVisible()
  })

  test('loads interests, citations, and notification sections', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'Interest Tags' })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Citation Sources' })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Notification Settings' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Frontend', exact: true })).toBeVisible()
  })

  test('saves citation preference changes', async ({ page }) => {
    const blogRow = page.locator('label').filter({ hasText: 'blog' })
    const checkbox = blogRow.locator('input[type="checkbox"]')
    const wasChecked = await checkbox.isChecked()
    await checkbox.click()

    await page.getByRole('button', { name: 'Save Settings' }).click()
    await expect(page.getByText('Settings saved')).toBeVisible({ timeout: 10_000 })

    await page.reload()
    await expect(page.getByRole('heading', { name: 'Settings', exact: true })).toBeVisible()
    await expect(blogRow.locator('input[type="checkbox"]')).toBeChecked({ checked: !wasChecked })

    await checkbox.click()
    await page.getByRole('button', { name: 'Save Settings' }).click()
    await expect(page.getByText('Settings saved')).toBeVisible({ timeout: 10_000 })
  })

  test('caps interest selection at three', async ({ page }) => {
    // The seeded user already follows Frontend, so two more fills the cap.
    await expect(page.getByText(/of 3 selected/)).toBeVisible()

    for (const name of ['Backend', 'AI/ML']) {
      const chip = page.getByRole('button', { name, exact: true })
      if ((await chip.getAttribute('aria-pressed')) === 'false') await chip.click()
    }

    await expect(page.getByText('3 of 3 selected — deselect one to swap.')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Security', exact: true })).toBeDisabled()

    // Restore the seeded selection so later specs are unaffected.
    for (const name of ['Backend', 'AI/ML']) {
      await page.getByRole('button', { name, exact: true }).click()
    }
    await page.getByRole('button', { name: 'Save Settings' }).click()
    await expect(page.getByText('Settings saved')).toBeVisible({ timeout: 10_000 })
  })

  test('navigates from bottom nav', async ({ page }) => {
    await page.getByRole('navigation', { name: 'Main navigation' }).getByRole('link', { name: 'Stack' }).click()
    await expect(page).toHaveURL(/\/my-stack/)
    await page.getByRole('navigation', { name: 'Main navigation' }).getByRole('link', { name: 'Settings' }).click()
    await expect(page).toHaveURL(/\/settings/)
  })
})
