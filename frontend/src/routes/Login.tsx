import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import KiteBrand from '../components/KiteBrand'
import ThemeToggle from '../components/ThemeToggle'
import { api } from '../api/client'
import { completeOAuthRedirect, getOAuthError, oauthRedirectUrl } from '../lib/authRedirect'
import { captureGitHubTokenFromSession, markPendingGitHubOAuth } from '../lib/githubToken'
import { supabase } from '../lib/supabase'
import { useTheme } from '../lib/theme'

async function resolvePostLoginPath(): Promise<string> {
  try {
    const res = await api('/me/interests')
    if (!res.ok) return '/onboarding'
    const data = await res.json()
    return (data.tag_ids?.length ?? 0) > 0 ? '/discover' : '/onboarding'
  } catch {
    return '/discover'
  }
}

export default function Login() {
  const navigate = useNavigate()
  const { theme } = useTheme()
  const [authError, setAuthError] = useState<string | null>(() => getOAuthError())
  const [finishing, setFinishing] = useState(
    () => new URLSearchParams(window.location.search).has('code') || !!getOAuthError(),
  )

  useEffect(() => {
    let cancelled = false
    if (!finishing) return

    completeOAuthRedirect().then(({ ok, error }) => {
      if (cancelled) return
      if (error) {
        setAuthError(error)
        setFinishing(false)
        return
      }
      if (ok) {
        resolvePostLoginPath().then((path) => navigate(path, { replace: true }))
      } else {
        setFinishing(false)
      }
    })

    return () => {
      cancelled = true
    }
  }, [finishing, navigate])

  useEffect(() => {
    if (finishing) return
    supabase.auth.getSession().then(async ({ data: { session } }) => {
      if (session) {
        const path = await resolvePostLoginPath()
        navigate(path, { replace: true })
      }
    })
  }, [finishing, navigate])

  useEffect(() => {
    const { data: { subscription } } = supabase.auth.onAuthStateChange(async (event, session) => {
      if (session) {
        captureGitHubTokenFromSession(session)
      }
      if (event === 'SIGNED_IN' && session) {
        await api('/auth/callback', {
          method: 'POST',
          body: JSON.stringify({ access_token: session.access_token }),
        }).catch(() => {})
        const path = await resolvePostLoginPath()
        navigate(path, { replace: true })
      }
    })
    return () => subscription.unsubscribe()
  }, [navigate])

  const oauthRedirect = oauthRedirectUrl('/login')

  const signInWithGitHub = async () => {
    setAuthError(null)
    markPendingGitHubOAuth()
    const { error } = await supabase.auth.signInWithOAuth({
      provider: 'github',
      options: { scopes: 'read:user repo', redirectTo: oauthRedirect },
    })
    if (error) setAuthError(error.message)
  }
  const signInWithGoogle = async () => {
    setAuthError(null)
    const { error } = await supabase.auth.signInWithOAuth({
      provider: 'google',
      options: { redirectTo: oauthRedirect },
    })
    if (error) setAuthError(error.message)
  }

  if (finishing) {
    return (
      <div className="flex min-h-[100dvh] items-center justify-center">
        <div className="kite-spinner kite-spinner-lg" />
      </div>
    )
  }

  return (
    <>
      <div className="kite-app-bg" aria-hidden="true">
        <div className="kite-app-bg-mid" />
      </div>
      <div className="relative flex min-h-[100dvh] flex-col items-center justify-center px-4 pb-[env(safe-area-inset-bottom,0px)] pt-[env(safe-area-inset-top,0px)]">
        <div className="absolute right-[max(1rem,env(safe-area-inset-right))] top-[max(1rem,env(safe-area-inset-top))]">
          <ThemeToggle />
        </div>
        <div className="kite-login-card">
          <div className="flex justify-center">
            <KiteBrand size="lg" />
          </div>
          <p className="mb-8 mt-2 text-center text-sm kite-text-secondary">
            Stay current on tech. Watch your stack.
          </p>
          {authError ? (
            <p className="mb-4 rounded-lg border border-red-300/40 bg-red-500/10 px-3 py-2 text-center text-sm text-red-700 dark:text-red-300">
              {authError}
            </p>
          ) : null}
          <div className="flex flex-col gap-3">
            <button type="button" onClick={signInWithGitHub} className="kite-btn-secondary w-full py-3">
              <svg className="h-5 w-5" fill="currentColor" viewBox="0 0 24 24">
                <path d="M12 0C5.37 0 0 5.37 0 12c0 5.3 3.438 9.8 8.205 11.387.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.73.083-.73 1.205.085 1.838 1.236 1.838 1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 2.22 0 1.606-.015 2.896-.015 3.286 0 .315.21.69.825.57C20.565 21.795 24 17.295 24 12 24 5.37 18.63 0 12 0z" />
              </svg>
              Continue with GitHub
            </button>
            <button type="button" onClick={signInWithGoogle} className="kite-btn-secondary w-full py-3">
              <svg className="h-5 w-5" viewBox="0 0 24 24">
                <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z" />
                <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" />
                <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" />
                <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" />
              </svg>
              Continue with Google
            </button>
          </div>
          <p className="mt-6 text-center text-xs kite-text-muted">
            {theme === 'dark' ? 'Dark mode' : 'Light mode'} · OAuth only
          </p>
        </div>
      </div>
    </>
  )
}
