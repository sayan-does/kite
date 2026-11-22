import { expect, test } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { seedDependencyUpdate, seedTrackedDependency, type E2EUser } from '../helpers/seed'

function loadE2EUser(): E2EUser {
  const contextPath = resolve(import.meta.dirname, '../.auth/context.json')
  const { user } = JSON.parse(readFileSync(contextPath, 'utf8')) as { user: E2EUser }
  return user
}

function projectToggle(page: import('@playwright/test').Page, name = 'demo') {
  return page.getByRole('button', { name: new RegExp(`^${name} `) })
}

test.describe('My Stack', () => {
  test.beforeAll(async () => {
    await seedDependencyUpdate('react', '19.0.0', 'React 19 release with compiler improvements.')
  })

  test.beforeEach(async ({ page }) => {
    await page.goto('/my-stack')
    await expect(page.getByRole('heading', { name: 'My Stack' })).toBeVisible()
  })

  test('expands project and shows update badge', async ({ page }) => {
    const user = loadE2EUser()
    await seedTrackedDependency(user.accessToken, {
      project_name: 'demo',
      ecosystem: 'npm',
      package_name: 'react',
      version: '18.0.0',
    })
    await page.reload()

    await expect(projectToggle(page)).toBeVisible()
    await expect(page.getByRole('button', { name: 'Add manually' })).toHaveCount(0)

    await projectToggle(page).click()
    await expect(page.getByRole('heading', { name: 'react', exact: true })).toBeVisible()
    await expect(page.getByText('Update available')).toBeVisible()
    await expect(page.getByText('React 19 release')).toBeVisible()
    await expect(page.getByText('18.0.0')).toBeVisible()
    await expect(page.getByText('19.0.0')).toBeVisible()
    await expect(page.getByText('major', { exact: true })).toBeVisible()
  })

  test('filters inside expanded project and opens package detail', async ({ page }) => {
    const user = loadE2EUser()
    await seedTrackedDependency(user.accessToken, {
      project_name: 'demo',
      ecosystem: 'npm',
      package_name: 'react',
      version: '18.0.0',
    })
    await page.reload()

    await projectToggle(page).click()
    await expect(page.getByRole('heading', { name: 'react', exact: true })).toBeVisible()

    await page.getByRole('button', { name: /Updates/ }).click()
    await expect(page.getByRole('heading', { name: 'react', exact: true })).toBeVisible()

    await page.getByRole('button', { name: /Up to date/ }).click()
    await expect(page.getByRole('heading', { name: 'react', exact: true })).toBeVisible()

    await page.getByRole('heading', { name: 'react', exact: true }).click()
    await expect(page).toHaveURL(/\/my-stack\/npm\/react/)
    await expect(page.getByRole('heading', { name: 'react', exact: true })).toBeVisible()
    await expect(page.getByRole('heading', { name: "What's new" })).toBeVisible()
    await expect(page.getByText('React 19 release with compiler improvements.')).toBeVisible()
    await expect(page.getByText('Release timeline (90 days)')).toBeVisible()
    await expect(page.getByText('Show all releases in window')).toBeVisible()

    await page.getByLabel('Show all releases in window').check()
    await expect(page.getByText('19.0.0', { exact: true })).toBeVisible()
  })

  test('removes dependency from expanded project', async ({ page }) => {
    const user = loadE2EUser()
    await seedTrackedDependency(user.accessToken, {
      project_name: 'demo',
      ecosystem: 'npm',
      package_name: 'left-pad',
      version: '1.0.0',
    })
    await page.reload()

    await projectToggle(page).click()
    const row = page.locator('.kite-card-static').filter({ hasText: 'left-pad' })
    await expect(row).toBeVisible()
    await row.getByRole('button', { name: 'Remove' }).click()
    await expect(page.getByRole('heading', { name: 'left-pad', exact: true })).not.toBeVisible()
  })

  test('navigates from bottom nav', async ({ page }) => {
    await page.getByRole('navigation', { name: 'Main navigation' }).getByRole('link', { name: 'Discover' }).click()
    await expect(page).toHaveURL(/\/discover/)
  })
})
