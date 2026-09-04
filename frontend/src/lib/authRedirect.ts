import { supabase } from './supabase'

export function getOAuthError(): string | null {
  const hash = new URLSearchParams(window.location.hash.replace(/^#/, ''))
  const query = new URLSearchParams(window.location.search)
  return (
    hash.get('error_description') ||
    hash.get('error') ||
    query.get('error_description') ||
    query.get('error')
  )
}

function clearOAuthParams(): void {
  const url = new URL(window.location.href)
  url.hash = ''
  for (const key of ['code', 'error', 'error_description', 'state']) {
    url.searchParams.delete(key)
  }
  window.history.replaceState({}, document.title, `${url.pathname}${url.search}`)
}

/** Finish PKCE OAuth when Supabase redirects back with ?code=... */
export async function completeOAuthRedirect(): Promise<{ ok: boolean; error: string | null }> {
  const oauthError = getOAuthError()
  if (oauthError) {
    clearOAuthParams()
    return { ok: false, error: oauthError }
  }

  const code = new URLSearchParams(window.location.search).get('code')
  if (code) {
    const { error } = await supabase.auth.exchangeCodeForSession(code)
    clearOAuthParams()
    if (error) {
      return { ok: false, error: error.message }
    }
  }

  const { data: { session } } = await supabase.auth.getSession()
  return { ok: !!session, error: null }
}

export function oauthRedirectUrl(path = '/login'): string {
  return `${window.location.origin}${path}`
}
