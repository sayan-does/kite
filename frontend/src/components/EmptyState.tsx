import type { ReactNode } from 'react'

type Motif = 'discover' | 'stack' | 'generic'

interface EmptyStateProps {
  motif?: Motif
  title: string
  description?: ReactNode
  action?: ReactNode
  className?: string
}

export default function EmptyState({
  motif = 'generic',
  title,
  description,
  action,
  className = '',
}: EmptyStateProps) {
  return (
    <div className={`kite-empty ${className}`.trim()}>
      <div className="kite-empty-state">
        <div className="kite-empty-motif" aria-hidden="true">
          {motif === 'discover' && <DiscoverMotif />}
          {motif === 'stack' && <StackMotif />}
          {motif === 'generic' && <GenericMotif />}
        </div>
        <p className="kite-empty-title">{title}</p>
        {description && <div className="kite-empty-body">{description}</div>}
        {action}
      </div>
    </div>
  )
}

function DiscoverMotif() {
  return (
    <svg width="36" height="36" viewBox="0 0 36 36" fill="none">
      <path
        d="M18 6c-4.5 0-8 2.2-8 6.5 0 5.2 5.2 10.2 7.2 12.1a1.2 1.2 0 0 0 1.6 0c2-1.9 7.2-6.9 7.2-12.1C26 8.2 22.5 6 18 6Z"
        stroke="currentColor"
        strokeWidth="1.75"
        strokeLinejoin="round"
      />
      <circle cx="18" cy="12.5" r="2.5" fill="currentColor" opacity="0.85" />
      <path
        d="M10 28h16"
        stroke="currentColor"
        strokeWidth="1.75"
        strokeLinecap="round"
        opacity="0.45"
      />
    </svg>
  )
}

function StackMotif() {
  return (
    <svg width="36" height="36" viewBox="0 0 36 36" fill="none">
      <rect x="7" y="8" width="22" height="6" rx="2" stroke="currentColor" strokeWidth="1.75" />
      <rect x="9" y="15" width="18" height="6" rx="2" stroke="currentColor" strokeWidth="1.75" opacity="0.75" />
      <rect x="11" y="22" width="14" height="6" rx="2" stroke="currentColor" strokeWidth="1.75" opacity="0.5" />
    </svg>
  )
}

function GenericMotif() {
  return (
    <svg width="36" height="36" viewBox="0 0 36 36" fill="none">
      <path
        d="M10 22c2-6 6-10 8-10s6 4 8 10"
        stroke="currentColor"
        strokeWidth="1.75"
        strokeLinecap="round"
      />
      <path
        d="M12 14l6-6 6 6"
        stroke="currentColor"
        strokeWidth="1.75"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx="18" cy="26" r="1.75" fill="currentColor" />
    </svg>
  )
}
