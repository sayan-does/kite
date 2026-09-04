import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import EmptyState from '../components/EmptyState'
import { api } from '../api/client'

interface Citation {
  type: string
  url: string
  title: string
}

interface TimelineItem {
  version: string
  published_at: string | null
  summary: string | null
  is_security: boolean
  is_breaking: boolean
  citations: Citation[]
}

interface PackageDetailData {
  ecosystem: string
  package_name: string
  tracked_version: string
  latest_version: string | null
  status: string
  version_gap: { kind: string; tracked: string; latest: string } | null
  summary: string | null
  timeline: TimelineItem[]
}

const badgeLabels: Record<string, string> = {
  up_to_date: 'Up to date',
  update_available: 'Update available',
  security: 'Security alert',
  breaking: 'Breaking change',
  buzz: 'Buzz',
}

const statusClass: Record<string, string> = {
  up_to_date: 'kite-status-up_to_date',
  update_available: 'kite-status-release',
  security: 'kite-status-security',
  breaking: 'kite-status-breaking',
  buzz: 'kite-status-buzz',
}

function formatDate(value: string | null): string {
  if (!value) return 'Unknown date'
  try {
    return new Date(value).toLocaleDateString(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    })
  } catch {
    return value
  }
}

export default function PackageDetail() {
  const { ecosystem = '', packageName = '' } = useParams()
  const decodedEco = decodeURIComponent(ecosystem)
  const decodedPkg = decodeURIComponent(packageName)
  const [data, setData] = useState<PackageDetailData | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [showAll, setShowAll] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await api(
        `/stack/packages/${encodeURIComponent(decodedEco)}/${encodeURIComponent(decodedPkg)}`,
      )
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        setError(err.detail || 'Failed to load package')
        setData(null)
        return
      }
      setData(await res.json())
    } catch {
      setError('Failed to load package')
      setData(null)
    } finally {
      setLoading(false)
    }
  }, [decodedEco, decodedPkg])

  useEffect(() => {
    load()
  }, [load])

  const visibleTimeline = useMemo(() => {
    if (!data) return []
    if (showAll) return data.timeline
    return data.timeline.filter((t) => t.is_security || t.is_breaking)
  }, [data, showAll])

  const trackedOutsideWindow =
    !!data &&
    !data.timeline.some((t) => t.version === data.tracked_version)

  if (loading) {
    return (
      <div className="kite-page-wide">
        <div className="kite-pulse-ring mx-auto mt-16">
          <div className="kite-spinner kite-spinner-lg" />
        </div>
      </div>
    )
  }

  if (error || !data) {
    return (
      <div className="kite-page-wide">
        <Link to="/my-stack" className="kite-nav-link text-sm">
          ← Back to My Stack
        </Link>
        <p className="mt-6 text-sm kite-text-danger">{error || 'Package not found'}</p>
      </div>
    )
  }

  const gapLabel =
    data.version_gap?.kind && data.version_gap.kind !== 'none' && data.version_gap.kind !== 'unknown'
      ? data.version_gap.kind
      : data.version_gap?.kind === 'unknown'
        ? 'unknown'
        : ''

  return (
    <div className="kite-page-wide">
      <Link to="/my-stack" className="kite-nav-link text-sm">
        ← Back to My Stack
      </Link>

      <div className="mt-6 mb-8">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-xs uppercase kite-text-muted">{data.ecosystem}</span>
          <h2 className="kite-page-title" style={{ marginBottom: 0 }}>
            {data.package_name}
          </h2>
          <span
            className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-semibold ${statusClass[data.status] || 'kite-status-buzz'}`}
          >
            {badgeLabels[data.status] || data.status}
          </span>
        </div>
        <p className="mt-2 text-sm kite-text-muted">
          {data.tracked_version}
          {data.latest_version && data.latest_version !== data.tracked_version && (
            <>
              <span className="mx-1.5">→</span>
              {data.latest_version}
            </>
          )}
          {gapLabel && <span className="ml-2 font-mono uppercase">{gapLabel}</span>}
        </p>
        {data.status !== 'up_to_date' && data.summary && (
          <div className="mt-4 max-w-2xl">
            <h3 className="text-sm font-semibold" style={{ color: 'var(--kite-text)' }}>
              What's new
            </h3>
            <p className="mt-1 line-clamp-2 text-sm kite-text-secondary">{data.summary}</p>
          </div>
        )}
      </div>

      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h3 className="text-sm font-semibold" style={{ color: 'var(--kite-text)' }}>
          Release timeline (90 days)
        </h3>
        <label className="flex cursor-pointer items-center gap-2 text-xs kite-text-muted">
          <input
            type="checkbox"
            checked={showAll}
            onChange={(e) => setShowAll(e.target.checked)}
          />
          Show all releases in window
        </label>
      </div>

      {trackedOutsideWindow && (
        <div className="kite-panel mb-3 px-4 py-3">
          <p className="text-xs font-semibold" style={{ color: 'var(--kite-text)' }}>
            Tracked: {data.tracked_version}
          </p>
          <p className="mt-1 text-xs kite-text-muted">
            Outside the 90-day window — shown for gap context.
          </p>
        </div>
      )}

      <div className="kite-stagger space-y-3">
        {visibleTimeline.length === 0 && (
          <EmptyState
            motif="stack"
            title={showAll ? 'No releases in this window' : 'No critical releases'}
            description={
              showAll
                ? 'No releases recorded in the last 90 days.'
                : 'No security or breaking changes in the last 90 days. Turn on “Show all releases” to see routine versions.'
            }
          />
        )}
        {visibleTimeline.map((item) => (
          <div key={item.version} className="kite-card-static px-5 py-4">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-sm font-semibold" style={{ color: 'var(--kite-text)' }}>
                {item.version}
              </span>
              <span className="text-xs kite-text-muted">{formatDate(item.published_at)}</span>
              {item.is_security && (
                <span className="inline-block rounded-full px-2 py-0.5 text-xs font-semibold kite-status-security">
                  Security
                </span>
              )}
              {item.is_breaking && (
                <span className="inline-block rounded-full px-2 py-0.5 text-xs font-semibold kite-status-breaking">
                  Breaking
                </span>
              )}
              {item.version === data.tracked_version && (
                <span className="text-xs kite-text-muted">Tracked</span>
              )}
            </div>
            <p className="mt-2 text-xs kite-text-secondary">
              {item.summary || 'No release notes'}
            </p>
            {item.citations?.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-3">
                {item.citations.map((c) => (
                  <a
                    key={`${c.url}-${c.title}`}
                    href={c.url}
                    target="_blank"
                    rel="noreferrer"
                    className="kite-nav-link text-xs"
                  >
                    {c.title || c.url}
                  </a>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
