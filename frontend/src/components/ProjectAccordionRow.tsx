import { useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'
import DepRow from './DepRow'

export interface DigestItem {
  id: string | null
  project_name: string
  ecosystem: string
  package_name: string
  tracked_version: string
  latest_version: string | null
  status: string
  version_gap: {
    kind: string
    tracked: string
    latest: string
  } | null
  update: {
    version: string | null
    update_type: string | null
    summary: string | null
    citations: { type: string; url: string; title: string }[]
    published_at: string | null
  } | null
}

export interface ProjectSummary {
  project_name: string
  dep_count: number
  counts: {
    security: number
    breaking: number
    update_available: number
    up_to_date: number
  }
}

type StatusFilter = 'security' | 'breaking' | 'update_available' | 'up_to_date'

const STATUS_ORDER: Record<string, number> = {
  security: 0,
  breaking: 1,
  update_available: 2,
  up_to_date: 3,
}

const FILTERS: { key: StatusFilter; label: string }[] = [
  { key: 'security', label: 'Security' },
  { key: 'breaking', label: 'Breaking' },
  { key: 'update_available', label: 'Updates' },
  { key: 'up_to_date', label: 'Up to date' },
]

const CHIP_META: { key: StatusFilter; label: string }[] = [
  { key: 'security', label: 'Security' },
  { key: 'breaking', label: 'Breaking' },
  { key: 'update_available', label: 'Updates' },
  { key: 'up_to_date', label: 'Up to date' },
]

function normalizeItem(raw: DigestItem): DigestItem {
  const status =
    raw.status ||
    (raw.update?.update_type === 'security'
      ? 'security'
      : raw.update?.update_type === 'breaking'
        ? 'breaking'
        : raw.update?.update_type === 'release' || (raw.latest_version && raw.latest_version !== raw.tracked_version)
          ? 'update_available'
          : 'up_to_date')
  return {
    ...raw,
    id: raw.id ?? null,
    project_name: raw.project_name || 'Uncategorized',
    status,
    latest_version: raw.latest_version ?? raw.update?.version ?? null,
    version_gap: raw.version_gap ?? null,
  }
}

interface ProjectAccordionRowProps {
  project: ProjectSummary
  expanded: boolean
  onToggle: () => void
  cacheKey: number
  onOpenDetail: (item: DigestItem) => void
  onEdit: (item: DigestItem) => void
  onDelete: (item: DigestItem) => void
  onRenameProject: (oldName: string, newName: string) => Promise<string | null>
  onDeleteProject: (name: string) => Promise<void>
}

export default function ProjectAccordionRow({
  project,
  expanded,
  onToggle,
  cacheKey,
  onOpenDetail,
  onEdit,
  onDelete,
  onRenameProject,
  onDeleteProject,
}: ProjectAccordionRowProps) {
  const [items, setItems] = useState<DigestItem[] | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [activeFilters, setActiveFilters] = useState<Set<StatusFilter>>(new Set())
  const [loadedForKey, setLoadedForKey] = useState<number | null>(null)
  const [renaming, setRenaming] = useState(false)
  const [renameValue, setRenameValue] = useState(project.project_name)
  const [renameError, setRenameError] = useState('')
  const [renameBusy, setRenameBusy] = useState(false)
  const [deleteBusy, setDeleteBusy] = useState(false)

  useEffect(() => {
    if (!expanded) return
    if (loadedForKey === cacheKey) return

    let cancelled = false
    setLoading(true)
    setError('')
    api(`/stack/projects/${encodeURIComponent(project.project_name)}/digest`)
      .then(async (res) => {
        if (!res.ok) {
          const err = await res.json().catch(() => ({}))
          throw new Error(err.detail || 'Failed to load dependencies')
        }
        return res.json()
      })
      .then((data) => {
        if (cancelled) return
        setItems(((data.items || []) as DigestItem[]).map(normalizeItem))
        setLoadedForKey(cacheKey)
      })
      .catch((e: Error) => {
        if (cancelled) return
        setError(e.message || 'Failed to load dependencies')
        setItems([])
        setLoadedForKey(cacheKey)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [expanded, project.project_name, cacheKey, loadedForKey])

  const visibleItems = useMemo(() => {
    if (!items) return []
    const filtered =
      activeFilters.size === 0
        ? items
        : items.filter((item) => activeFilters.has(item.status as StatusFilter))
    return [...filtered].sort((a, b) => {
      const ao = STATUS_ORDER[a.status] ?? 9
      const bo = STATUS_ORDER[b.status] ?? 9
      if (ao !== bo) return ao - bo
      return a.package_name.localeCompare(b.package_name)
    })
  }, [items, activeFilters])

  const filterCounts = useMemo(() => {
    const c: Record<StatusFilter, number> = {
      security: 0,
      breaking: 0,
      update_available: 0,
      up_to_date: 0,
    }
    for (const item of items || []) {
      const key = item.status as StatusFilter
      if (key in c) c[key] += 1
    }
    return c
  }, [items])

  const toggleFilter = (key: StatusFilter) => {
    setActiveFilters((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  const startRename = (e: React.MouseEvent) => {
    e.stopPropagation()
    setRenameValue(project.project_name)
    setRenameError('')
    setRenaming(true)
  }

  const cancelRename = (e?: React.MouseEvent) => {
    e?.stopPropagation()
    setRenaming(false)
    setRenameError('')
    setRenameValue(project.project_name)
  }

  const submitRename = async (e: React.MouseEvent | React.FormEvent) => {
    e.preventDefault()
    e.stopPropagation()
    const next = renameValue.trim()
    if (!next) {
      setRenameError('Project name is required')
      return
    }
    setRenameBusy(true)
    setRenameError('')
    const err = await onRenameProject(project.project_name, next)
    setRenameBusy(false)
    if (err) {
      setRenameError(err)
      return
    }
    setRenaming(false)
  }

  const confirmDelete = async (e: React.MouseEvent) => {
    e.stopPropagation()
    const ok = window.confirm(
      `Delete project “${project.project_name}” and all ${project.dep_count} tracked dependenc${project.dep_count === 1 ? 'y' : 'ies'}? This cannot be undone.`,
    )
    if (!ok) return
    setDeleteBusy(true)
    try {
      await onDeleteProject(project.project_name)
    } finally {
      setDeleteBusy(false)
    }
  }

  return (
    <div className="kite-panel overflow-hidden">
      <div className="flex w-full flex-wrap items-center justify-between gap-3 px-4 py-3">
        {renaming ? (
          <form className="flex min-w-0 flex-1 flex-wrap items-center gap-2" onSubmit={submitRename}>
            <span className="text-sm kite-text-muted" aria-hidden="true">
              {expanded ? '▾' : '▸'}
            </span>
            <input
              type="text"
              className="kite-input min-w-[120px] flex-1 text-sm"
              value={renameValue}
              onChange={(e) => setRenameValue(e.target.value)}
              maxLength={80}
              autoFocus
              aria-label="New project name"
              onKeyDown={(e) => {
                if (e.key === 'Escape') cancelRename()
              }}
            />
            <button type="submit" className="kite-btn-primary text-xs" disabled={renameBusy}>
              {renameBusy ? 'Saving…' : 'Save'}
            </button>
            <button type="button" className="kite-btn-secondary text-xs" onClick={cancelRename} disabled={renameBusy}>
              Cancel
            </button>
          </form>
        ) : (
          <div className="flex min-w-0 flex-1 items-center gap-1.5">
            <button
              type="button"
              className="flex min-h-11 min-w-0 flex-1 items-center gap-2 text-left"
              onClick={onToggle}
              aria-expanded={expanded}
            >
              <span className="text-sm kite-text-muted" aria-hidden="true">
                {expanded ? '▾' : '▸'}
              </span>
              <span className="truncate text-sm font-semibold" style={{ color: 'var(--kite-text)' }}>
                {project.project_name}
              </span>
              <span className="text-xs kite-text-muted">{project.dep_count}</span>
            </button>
            <button
              type="button"
              className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-md kite-text-muted transition hover:bg-[color-mix(in_srgb,var(--kite-text)_8%,transparent)] hover:kite-text-secondary"
              onClick={startRename}
              disabled={deleteBusy}
              aria-label={`Rename ${project.project_name}`}
              title="Rename project"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <path
                  d="M12 20h9M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"
                  stroke="currentColor"
                  strokeWidth="1.75"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </button>
          </div>
        )}
        <div className="flex flex-wrap items-center gap-1.5">
          {!renaming && (
            <div className="flex flex-wrap gap-1.5" aria-label={`${project.project_name} status summary`}>
              {CHIP_META.map((chip) => {
                const n = project.counts[chip.key] || 0
                if (n === 0) return null
                return (
                  <span key={chip.key} className="kite-btn-secondary pointer-events-none text-xs px-2 py-0.5">
                    {chip.label} {n}
                  </span>
                )
              })}
            </div>
          )}
          {!renaming && (
            <button
              type="button"
              className="kite-btn-secondary text-xs kite-text-danger"
              onClick={confirmDelete}
              disabled={deleteBusy}
            >
              {deleteBusy ? 'Deleting…' : 'Delete'}
            </button>
          )}
        </div>
      </div>
      {renameError && (
        <p className="px-4 pb-2 text-sm kite-text-danger">{renameError}</p>
      )}

      {expanded && (
        <div
          className="kite-accordion-body border-t px-4 py-4"
          style={{ borderColor: 'var(--kite-border)' }}
        >
          {loading && (
            <div className="flex justify-center py-6">
              <div className="kite-spinner" />
            </div>
          )}
          {error && <p className="mb-3 text-sm kite-text-danger">{error}</p>}
          {!loading && !error && items && (
            <>
              <div className="mb-4 flex flex-wrap gap-2" role="group" aria-label={`Filter ${project.project_name}`}>
                {FILTERS.map((f) => {
                  const active = activeFilters.has(f.key)
                  return (
                    <button
                      key={f.key}
                      type="button"
                      onClick={() => toggleFilter(f.key)}
                      className={active ? 'kite-btn-primary text-xs' : 'kite-btn-secondary text-xs'}
                      aria-pressed={active}
                    >
                      {f.label}
                      <span className="ml-1.5 opacity-80">{filterCounts[f.key]}</span>
                    </button>
                  )
                })}
              </div>
              {visibleItems.length === 0 ? (
                <p className="text-sm kite-text-muted">No dependencies match the selected filters.</p>
              ) : (
                <div className="space-y-3">
                  {visibleItems.map((item) => (
                    <DepRow
                      key={item.id || `${item.ecosystem}:${item.package_name}`}
                      ecosystem={item.ecosystem}
                      packageName={item.package_name}
                      trackedVersion={item.tracked_version}
                      latestVersion={item.latest_version}
                      status={item.status}
                      versionGap={item.version_gap}
                      update={item.update}
                      onOpen={() => onOpenDetail(item)}
                      onEdit={() => onEdit(item)}
                      onDelete={() => onDelete(item)}
                    />
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  )
}
