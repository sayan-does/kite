import { randomUUID } from 'node:crypto'
import { createClient } from '@supabase/supabase-js'
import { env } from './env'

export type E2EUser = {
  id: string
  email: string
  password: string
  accessToken: string
  session: {
    access_token: string
    refresh_token: string
    expires_in: number
    token_type: string
    user: Record<string, unknown>
  }
}

const adminHeaders = () => ({
  apikey: env.serviceRoleKey,
  Authorization: `Bearer ${env.serviceRoleKey}`,
  'Content-Type': 'application/json',
})

export async function createE2EUser(withInterests = true): Promise<E2EUser> {
  const email = `e2e-${randomUUID().slice(0, 8)}@example.com`
  const password = randomUUID()
  const url = `${env.supabaseUrl}/auth/v1/admin/users`

  const createResp = await fetch(url, {
    method: 'POST',
    headers: adminHeaders(),
    body: JSON.stringify({ email, password, email_confirm: true }),
  })
  if (!createResp.ok) {
    throw new Error(`create user failed: ${createResp.status} ${await createResp.text()}`)
  }
  const { id } = await createResp.json() as { id: string }

  const signInResp = await fetch(`${env.supabaseUrl}/auth/v1/token?grant_type=password`, {
    method: 'POST',
    headers: {
      apikey: env.supabaseAnonKey,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ email, password }),
  })
  if (!signInResp.ok) {
    throw new Error(`sign in failed: ${signInResp.status} ${await signInResp.text()}`)
  }
  const signInBody = await signInResp.json() as {
    access_token: string
    refresh_token: string
    expires_in: number
    token_type: string
    user: Record<string, unknown>
  }

  await fetch(`${env.apiBase}/auth/callback`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ access_token: signInBody.access_token }),
  })

  if (withInterests) {
    await fetch(`${env.apiBase}/me/interests`, {
      method: 'PUT',
      headers: {
        Authorization: `Bearer ${signInBody.access_token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ tag_ids: [1] }),
    })
  }

  return {
    id,
    email,
    password,
    accessToken: signInBody.access_token,
    session: signInBody,
  }
}

// The feed ranks by score, and kb_articles is shared with real collected
// content, so seeds need a score that outranks it to stay deterministic.
const E2E_SEED_SCORE = 100_000

export async function seedKbArticles(count = 3): Promise<string[]> {
  const db = createClient(env.supabaseUrl, env.serviceRoleKey)
  const ids: string[] = []
  for (let i = 0; i < count; i++) {
    const { data, error } = await db.from('kb_articles').insert({
      topic: 'Frontend',
      topic_kind: 'interest',
      tag_id: 1,
      score: E2E_SEED_SCORE,
      title: `E2E KB Article ${i + 1}`,
      one_liner: `One liner for article ${i + 1}`,
      summary: `Summary for article ${i + 1}`,
      body: `Body text for article ${i + 1}`,
      source_type: 'blog',
      citations: [{ type: 'blog', url: 'https://example.com', title: 'Example' }],
      url: `https://example.com/e2e-${randomUUID()}`,
    }).select('id').single()
    if (error) throw error
    ids.push(data.id)
  }
  return ids
}

export async function seedTrackedDependency(
  accessToken: string,
  opts: {
    project_name: string
    ecosystem: string
    package_name: string
    version: string
  },
) {
  const res = await fetch(`${env.apiBase}/stack`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${accessToken}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(opts),
  })
  if (!res.ok && res.status !== 409) {
    throw new Error(`seedTrackedDependency failed: ${res.status} ${await res.text()}`)
  }
}

export async function seedDependencyUpdate(
  packageName: string,
  version: string,
  summary: string,
) {
  const db = createClient(env.supabaseUrl, env.serviceRoleKey)
  const { error } = await db.from('dependency_updates').upsert({
    ecosystem: 'npm',
    package_name: packageName,
    version,
    update_type: 'release',
    summary,
    citations: [{ type: 'blog', url: 'https://example.com', title: 'Release notes' }],
  }, { onConflict: 'ecosystem, package_name, version, update_type' })
  if (error) throw error

  const { error: cacheError } = await db.from('package_registry_cache').upsert({
    ecosystem: 'npm',
    package_name: packageName,
    latest_version: version,
    last_checked_at: new Date().toISOString(),
  }, { onConflict: 'ecosystem, package_name' })
  if (cacheError) throw cacheError

  const { error: timelineError } = await db.from('package_version_timeline').upsert({
    ecosystem: 'npm',
    package_name: packageName,
    version,
    published_at: new Date().toISOString(),
    summary,
    is_security: false,
    is_breaking: false,
    citations: [{ type: 'blog', url: 'https://example.com', title: 'Release notes' }],
  }, { onConflict: 'ecosystem, package_name, version' })
  if (timelineError) throw timelineError
}

export async function injectSession(page: import('@playwright/test').Page, user: E2EUser) {
  const supabaseUrl = process.env.VITE_SUPABASE_URL ?? process.env.SUPABASE_URL!
  const projectRef = new URL(supabaseUrl).hostname.split('.')[0]
  const storageKey = `sb-${projectRef}-auth-token`
  const expiresAt = Math.floor(Date.now() / 1000) + user.session.expires_in
  await page.goto('/login')
  await page.evaluate(
    ({ key, session, expiresAt }) => {
      localStorage.setItem(key, JSON.stringify({ ...session, expires_at: expiresAt }))
    },
    { key: storageKey, session: user.session, expiresAt },
  )
}

export async function cleanupE2E(user: E2EUser, articleIds: string[]) {
  const db = createClient(env.supabaseUrl, env.serviceRoleKey)
  if (articleIds.length) {
    await db.from('user_article_state').delete().in('kb_article_id', articleIds)
    await db.from('kb_articles').delete().in('id', articleIds)
  }
  await db.from('user_interests').delete().eq('user_id', user.id)
  await db.from('user_article_state').delete().eq('user_id', user.id)
  await db.from('tracked_dependencies').delete().eq('user_id', user.id)
  await db.from('notification_settings').delete().eq('user_id', user.id)
  await db.from('citation_prefs').delete().eq('user_id', user.id)
  // quiz_questions cascades from quiz_sessions.
  await db.from('quiz_sessions').delete().eq('user_id', user.id)
  await db.from('user_streaks').delete().eq('user_id', user.id)
  await db.from('feed_build_jobs').delete().eq('user_id', user.id)
  await fetch(`${env.supabaseUrl}/auth/v1/admin/users/${user.id}`, {
    method: 'DELETE',
    headers: adminHeaders(),
  })
}
