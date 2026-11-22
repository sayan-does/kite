import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { cleanupE2E } from './helpers/seed'

export default async function globalTeardown() {
  const contextPath = resolve(import.meta.dirname, '.auth/context.json')
  if (!existsSync(contextPath)) return
  const { user, articleIds } = JSON.parse(readFileSync(contextPath, 'utf8'))
  await cleanupE2E(user, articleIds)
}
