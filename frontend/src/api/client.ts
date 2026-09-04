import { supabase } from '../lib/supabase'

const envUrl = import.meta.env.VITE_API_BASE_URL
const baseUrl = envUrl || ''

let cachedToken: string | null = null
let tokenExpiresAt = 0
let authListenerRegistered = false

function registerAuthListener() {
  if (authListenerRegistered) return
  authListenerRegistered = true
  supabase.auth.onAuthStateChange((_event, session) => {
    if (session?.access_token) {
      cachedToken = session.access_token
      tokenExpiresAt = session.expires_at ? session.expires_at * 1000 : Date.now() + 3600_000
    } else {
      cachedToken = null
      tokenExpiresAt = 0
    }
  })
}

async function getAccessToken(): Promise<string | null> {
  registerAuthListener()
  const now = Date.now()
  if (cachedToken && tokenExpiresAt > now + 30_000) {
    return cachedToken
  }
  const { data: { session } } = await supabase.auth.getSession()
  if (session?.access_token) {
    cachedToken = session.access_token
    tokenExpiresAt = session.expires_at ? session.expires_at * 1000 : now + 3600_000
    return cachedToken
  }
  cachedToken = null
  tokenExpiresAt = 0
  return null
}

export async function api(path: string, options: RequestInit = {}): Promise<Response> {
  const token = await getAccessToken()
  const headers: Record<string, string> = {
    ...(options.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
    ...(options.headers as Record<string, string> || {}),
  }
  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }
  return fetch(`${baseUrl}${path}`, { ...options, headers })
}

export async function updateFeedState(
  articleId: string,
  state: { seen?: boolean; read?: boolean; dismissed?: boolean },
): Promise<Response> {
  return api(`/feed/${articleId}/state`, {
    method: 'POST',
    body: JSON.stringify(state),
  })
}
