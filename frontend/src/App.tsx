import { useCallback, useEffect, useState } from 'react'
import { BrowserRouter, Link, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import BottomNav from './components/BottomNav'
import KiteBrand from './components/KiteBrand'
import PageTransition from './components/PageTransition'
import ThemeToggle from './components/ThemeToggle'
import { api } from './api/client'
import { captureGitHubTokenFromSession, clearGitHubProviderToken } from './lib/githubToken'
import { supabase } from './lib/supabase'
import Discover from './routes/Discover'
import Login from './routes/Login'
import MyStack from './routes/MyStack'
import Onboarding from './routes/Onboarding'
import PackageDetail from './routes/PackageDetail'
import Settings from './routes/Settings'

function AppBackground() {
  return (
    <div className="kite-app-bg" aria-hidden="true">
      <div className="kite-app-bg-mid" />
    </div>
  )
}

function LoadingScreen() {
  return (
    <div className="flex min-h-screen items-center justify-center">
      <div className="kite-pulse-ring">
        <div className="kite-spinner kite-spinner-lg" />
      </div>
    </div>
  )
}

function RequireAuth({ children }: { children: React.ReactNode }) {
  const [session, setSession] = useState<boolean | null>(null)

  useEffect(() => {
    supabase.auth.getSession().then(({ data: { session } }) => {
      captureGitHubTokenFromSession(session)
      setSession(!!session)
    })
    const { data: { subscription } } = supabase.auth.onAuthStateChange((event, next) => {
      captureGitHubTokenFromSession(next)
      if (event === 'SIGNED_OUT') {
        clearGitHubProviderToken()
        setSession(false)
      } else {
        setSession(!!next)
      }
    })
    return () => subscription.unsubscribe()
  }, [])

  if (session === null) return <LoadingScreen />
  if (!session) return <Navigate to="/login" replace />
  return <>{children}</>
}

function OnboardGuard({ children }: { children: React.ReactNode }) {
  const navigate = useNavigate()
  const location = useLocation()
  const [checking, setChecking] = useState(true)

  const check = useCallback(async () => {
    try {
      const res = await api('/me/interests')
      if (res.ok) {
        const data = await res.json()
        if (!data?.tag_ids?.length && location.pathname.startsWith('/discover')) {
          navigate('/onboarding', { replace: true })
          return
        }
      }
    } catch {
      // stay on page
    } finally {
      setChecking(false)
    }
  }, [navigate, location.pathname])

  useEffect(() => {
    check()
  }, [check])

  if (checking) return <LoadingScreen />
  return <>{children}</>
}

function AppShell() {
  const location = useLocation()
  const navigate = useNavigate()

  const tabs = [
    { path: '/discover', label: 'Discover' },
    { path: '/my-stack', label: 'My Stack' },
  ]

  const navClass = (active: boolean) =>
    `kite-nav-link${active ? ' kite-nav-link-active' : ''}`

  return (
    <>
      <AppBackground />
      <header className="kite-header">
        <KiteBrand to="/discover" size="md" />
        <nav className="kite-nav kite-nav-desktop" aria-label="Main">
          {tabs.map((tab) => (
            <Link
              key={tab.path}
              to={tab.path}
              className={navClass(location.pathname.startsWith(tab.path))}
            >
              {tab.label}
            </Link>
          ))}
          <button
            type="button"
            onClick={() => navigate('/settings')}
            className={navClass(location.pathname === '/settings')}
          >
            Settings
          </button>
        </nav>
        <ThemeToggle />
      </header>
      <main className="kite-main">
        <PageTransition>
          <Routes location={location}>
            <Route path="/onboarding" element={<Onboarding />} />
            <Route path="/discover" element={<OnboardGuard><Discover /></OnboardGuard>} />
            <Route path="/my-stack" element={<MyStack />} />
            <Route path="/my-stack/:ecosystem/:packageName" element={<PackageDetail />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="*" element={<Navigate to="/discover" replace />} />
          </Routes>
        </PageTransition>
      </main>
      <BottomNav />
    </>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route
          path="/*"
          element={
            <RequireAuth>
              <AppShell />
            </RequireAuth>
          }
        />
      </Routes>
    </BrowserRouter>
  )
}
