import { useEffect } from 'react'

export default function FeedSkeleton() {
  return (
    <div className="space-y-4" aria-hidden="true">
      {[0, 1, 2].map((i) => (
        <div key={i} className="kite-skeleton-card" style={{ animationDelay: `${i * 80}ms` }}>
          <div className="kite-skeleton kite-skeleton-badge" />
          <div className="kite-skeleton kite-skeleton-title" />
          <div className="kite-skeleton kite-skeleton-line" />
          <div className="kite-skeleton kite-skeleton-line short" />
        </div>
      ))}
    </div>
  )
}

interface ToastProps {
  message: string
  variant?: 'success' | 'error'
  onDismiss?: () => void
}

export function Toast({ message, variant = 'success', onDismiss }: ToastProps) {
  useEffect(() => {
    if (!onDismiss) return
    const t = window.setTimeout(onDismiss, 3000)
    return () => window.clearTimeout(t)
  }, [onDismiss, message])

  return (
    <div className={`kite-toast kite-toast-${variant}`} role="status">
      {message}
    </div>
  )
}
