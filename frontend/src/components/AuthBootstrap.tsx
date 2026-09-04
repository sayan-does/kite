import { useEffect, useState } from 'react'
import { completeOAuthRedirect } from '../lib/authRedirect'

export default function AuthBootstrap({ children }: { children: React.ReactNode }) {
  const [ready, setReady] = useState(false)

  useEffect(() => {
    let cancelled = false
    completeOAuthRedirect().finally(() => {
      if (!cancelled) setReady(true)
    })
    return () => {
      cancelled = true
    }
  }, [])

  if (!ready) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="kite-spinner kite-spinner-lg" />
      </div>
    )
  }

  return children
}
