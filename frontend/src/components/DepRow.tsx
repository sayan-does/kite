interface Update {
  version: string | null
  update_type: string | null
  summary: string | null
  published_at: string | null
}

interface VersionGap {
  kind: string
  tracked: string
  latest: string
}

interface DepRowProps {
  ecosystem: string
  packageName: string
  trackedVersion: string
  latestVersion: string | null
  status: string
  versionGap: VersionGap | null
  update: Update | null
  onOpen: () => void
  onEdit: () => void
  onDelete: () => void
}

const statusClass: Record<string, string> = {
  up_to_date: 'kite-status-up_to_date',
  update_available: 'kite-status-release',
  release: 'kite-status-release',
  security: 'kite-status-security',
  breaking: 'kite-status-breaking',
  buzz: 'kite-status-buzz',
}

const badgeLabels: Record<string, string> = {
  up_to_date: 'Up to date',
  update_available: 'Update available',
  release: 'Update available',
  security: 'Security alert',
  breaking: 'Breaking change',
  buzz: 'Buzz',
}

const gapLabels: Record<string, string> = {
  major: 'major',
  minor: 'minor',
  patch: 'patch',
  unknown: 'unknown',
  none: '',
}

export default function DepRow({
  ecosystem,
  packageName,
  trackedVersion,
  latestVersion,
  status,
  versionGap,
  update,
  onOpen,
  onEdit,
  onDelete,
}: DepRowProps) {
  const badgeLabel = badgeLabels[status] || status
  const latest = latestVersion || update?.version
  const gapKind = versionGap?.kind
  const gapLabel = gapKind && gapLabels[gapKind] ? gapLabels[gapKind] : ''

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onOpen()
        }
      }}
      className="kite-card-static flex cursor-pointer items-center justify-between px-5 py-4"
    >
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-xs uppercase kite-text-muted">{ecosystem}</span>
          <h3 className="truncate text-sm font-semibold" style={{ color: 'var(--kite-text)' }}>
            {packageName}
          </h3>
          <span
            className={`inline-block px-2 py-0.5 text-[0.6875rem] font-semibold uppercase tracking-wide ${statusClass[status] || 'kite-status-buzz'}`}
            style={{ borderRadius: 'var(--kite-radius)' }}
          >
            {badgeLabel}
          </span>
        </div>
        <p className="mt-1 text-xs kite-text-muted">
          {trackedVersion}
          {latest && latest !== trackedVersion && (
            <>
              <span className="mx-1.5">→</span>
              {latest}
            </>
          )}
          {gapLabel && (
            <span className="ml-2 font-mono uppercase opacity-80">{gapLabel}</span>
          )}
          {status === 'up_to_date' && !latest && (
            <span className="ml-1">· tracked {trackedVersion}</span>
          )}
        </p>
        {update?.summary && (
          <p className="mt-1 line-clamp-2 text-xs kite-text-secondary">{update.summary}</p>
        )}
      </div>
      <div className="ml-4 flex shrink-0 gap-1" onClick={(e) => e.stopPropagation()}>
        <button type="button" onClick={onEdit} className="kite-nav-link text-xs">
          Edit
        </button>
        <button type="button" onClick={onDelete} className="kite-nav-link text-xs kite-text-danger">
          Remove
        </button>
      </div>
    </div>
  )
}
