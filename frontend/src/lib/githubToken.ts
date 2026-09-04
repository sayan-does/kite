const STORAGE_KEY = 'kite_github_provider_token'
const PENDING_KEY = 'kite_pending_github_oauth'

export function markPendingGitHubOAuth(): void {
  window.sessionStorage.setItem(PENDING_KEY, '1')
}

export function saveGitHubProviderToken(token: string | null | undefined): void {
  if (token) {
    window.localStorage.setItem(STORAGE_KEY, token)
  }
}

export function clearGitHubProviderToken(): void {
  window.localStorage.removeItem(STORAGE_KEY)
}

export function getGitHubProviderToken(): string | null {
  return window.localStorage.getItem(STORAGE_KEY)
}

/**
 * Capture GitHub provider_token after a GitHub OAuth redirect.
 * Only stores when we marked a pending GitHub OAuth (avoids saving Google tokens).
 */
export function captureGitHubTokenFromSession(session: {
  provider_token?: string | null
  user?: { app_metadata?: { provider?: string } } | null
} | null): void {
  if (!session?.provider_token) return

  const pending = window.sessionStorage.getItem(PENDING_KEY) === '1'
  const providerIsGitHub = session.user?.app_metadata?.provider === 'github'

  if (pending || providerIsGitHub) {
    saveGitHubProviderToken(session.provider_token)
    window.sessionStorage.removeItem(PENDING_KEY)
  }
}
