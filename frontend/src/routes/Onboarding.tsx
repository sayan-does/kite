import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'

interface Tag {
  id: number
  name: string
  category: string
}

const MAX_INTERESTS = 3

export default function Onboarding() {
  const navigate = useNavigate()
  const [step, setStep] = useState(1)
  const [tags, setTags] = useState<Tag[]>([])
  const [tagsLoading, setTagsLoading] = useState(true)
  const [tagsError, setTagsError] = useState('')
  const [selected, setSelected] = useState<number[]>([])
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState('')
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState('')
  const [uploadedCount, setUploadedCount] = useState<number | null>(null)
  const [projectName, setProjectName] = useState('')

  useEffect(() => {
    setTagsLoading(true)
    setTagsError('')
    api('/interest-tags')
      .then((r) => {
        if (!r.ok) throw new Error('Failed to load interests')
        return r.json()
      })
      .then((data) => setTags(data.tags || []))
      .catch(() => setTagsError('Could not load interests. Please refresh.'))
      .finally(() => setTagsLoading(false))
  }, [])

  const toggle = (id: number) => {
    setSaveError('')
    setSelected((prev) => {
      if (prev.includes(id)) return prev.filter((x) => x !== id)
      if (prev.length >= MAX_INTERESTS) return prev
      return [...prev, id]
    })
  }

  const saveTags = async () => {
    if (selected.length === 0) {
      setSaveError('Please select at least one interest to continue.')
      return
    }
    setSaving(true)
    setSaveError('')
    try {
      const res = await api('/me/interests', {
        method: 'PUT',
        body: JSON.stringify({ tag_ids: selected }),
      })
      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail || 'Failed to save interests')
      }
      setStep(2)
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : 'Failed to save interests.')
    } finally {
      setSaving(false)
    }
  }

  const handleUpload = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    const trimmed = projectName.trim()
    if (!trimmed) {
      setUploadError('Enter a project name before uploading.')
      e.target.value = ''
      return
    }
    setUploading(true)
    setUploadError('')
    setUploadedCount(null)
    try {
      const formData = new FormData()
      formData.append('file', file)
      formData.append('project_name', trimmed)
      const res = await api('/stack/upload', { method: 'POST', headers: {}, body: formData })
      if (!res.ok) {
        const err = await res.json()
        setUploadError(err.detail || 'Upload failed')
        return
      }
      const data = await res.json()
      setUploadedCount(data.count ?? 0)
      setTimeout(() => navigate('/discover'), 1500)
    } catch {
      setUploadError('Upload failed. Try again or skip.')
    } finally {
      setUploading(false)
    }
  }, [navigate, projectName])

  const skip = () => navigate('/discover')

  if (tagsLoading) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <div className="kite-spinner kite-spinner-lg" />
      </div>
    )
  }

  if (tagsError) {
    return (
      <div className="kite-page text-center">
        <p className="kite-text-danger">{tagsError}</p>
        <button type="button" onClick={() => window.location.reload()} className="kite-btn-primary mt-4">
          Retry
        </button>
      </div>
    )
  }

  if (step === 1) {
    return (
      <div className="kite-page">
        <div className="mb-2 flex gap-2">
          <span className="kite-badge-interest">Step 1 of 2</span>
        </div>
        <h2 className="kite-page-title">What do you want to stay on top of?</h2>
        <p className="kite-page-subtitle">
          Pick up to {MAX_INTERESTS} categories to personalize your discovery feed. You can change
          them later in Settings.
        </p>
        {tags.length === 0 ? (
          <p className="mt-6 text-sm kite-text-muted">No interest tags available.</p>
        ) : (
          <>
            <div className="mt-6 grid grid-cols-2 gap-3">
              {tags.map((tag, i) => {
                const isSelected = selected.includes(tag.id)
                const atCap = !isSelected && selected.length >= MAX_INTERESTS
                return (
                  <button
                    key={tag.id}
                    type="button"
                    onClick={() => toggle(tag.id)}
                    disabled={atCap}
                    aria-pressed={isSelected}
                    className={`kite-chip kite-feed-item ${isSelected ? 'kite-chip-active' : ''}`}
                    style={{ animationDelay: `${i * 40}ms` }}
                  >
                    {tag.name}
                  </button>
                )
              })}
            </div>
            <p className="mt-4 text-sm kite-text-muted" aria-live="polite">
              {selected.length >= MAX_INTERESTS
                ? `${MAX_INTERESTS} of ${MAX_INTERESTS} selected — deselect one to swap.`
                : `${selected.length} of ${MAX_INTERESTS} selected.`}
            </p>
          </>
        )}
        {saveError && <p className="mt-4 text-sm kite-text-danger">{saveError}</p>}
        <button type="button" onClick={saveTags} disabled={saving} className="kite-btn-primary mt-8 w-full py-3">
          {saving ? 'Saving…' : 'Continue'}
        </button>
      </div>
    )
  }

  return (
    <div className="kite-page">
      <div className="mb-2 flex gap-2">
        <span className="kite-badge-stack">Step 2 of 2</span>
      </div>
      <h2 className="kite-page-title">
        Import your stack
        <span className="group relative ml-2 inline-block align-middle">
          <button
            type="button"
            className="kite-icon-btn h-5 w-5 rounded-full text-xs"
            aria-label="More information about dependency tracking"
          >
            ?
          </button>
          <span className="pointer-events-none absolute bottom-full left-1/2 mb-2 w-64 -translate-x-1/2 scale-95 rounded-lg border border-[var(--kite-border)] bg-[var(--kite-surface-1)] p-3 text-xs text-[var(--kite-text)] opacity-0 shadow-lg transition-opacity group-hover:opacity-100 z-50">
            Track package.json, requirements.txt, Cargo.toml, etc. Get alerts for breaking changes and security vulnerabilities.
            <br />
            <span className="mt-1 block text-[var(--kite-text-muted)]">
              Supported: package.json · requirements.txt · pyproject.toml · pom.xml · Cargo.toml
            </span>
          </span>
        </span>
      </h2>
      <p className="kite-page-subtitle">
        Upload your manifest files to track dependencies and get instant alerts.
      </p>

      <div className="mt-8 space-y-4">
        <div>
          <label className="mb-1 block text-xs font-medium kite-text-muted" htmlFor="onboarding-project">
            Project name
          </label>
          <input
            id="onboarding-project"
            type="text"
            className="kite-input w-full"
            placeholder="e.g. my-api"
            value={projectName}
            onChange={(e) => setProjectName(e.target.value)}
            maxLength={80}
          />
        </div>
        <label className="kite-empty flex cursor-pointer flex-col items-center transition hover:border-[var(--kite-primary)]">
          <span className="text-sm font-medium kite-text-secondary">
            {uploading ? 'Uploading…' : 'Click to select a manifest file'}
          </span>
          <input
            type="file"
            accept=".json,.txt,.toml,.xml,package.json,requirements.txt,pyproject.toml,pom.xml"
            className="hidden"
            onChange={handleUpload}
            disabled={uploading || !projectName.trim()}
          />
        </label>
        {uploadError && <p className="mt-2 text-sm kite-text-danger">{uploadError}</p>}
        {uploadedCount !== null && (
          <p className="mt-2 text-sm kite-text-success">
            Imported {uploadedCount} dependenc{uploadedCount === 1 ? 'y' : 'ies'}. Redirecting…
          </p>
        )}
      </div>

      <button type="button" onClick={skip} disabled={uploading} className="kite-btn-secondary mt-4 w-full py-3">
        Skip — I'll add dependencies later
      </button>
    </div>
  )
}
