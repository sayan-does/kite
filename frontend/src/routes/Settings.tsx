import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Toast } from '../components/FeedSkeleton'
import { api } from '../api/client'
import { clearGitHubProviderToken } from '../lib/githubToken'
import { supabase } from '../lib/supabase'

interface Tag {
  id: number
  name: string
  category: string
}

interface ChannelSettings {
  in_app: boolean
  email: boolean
}

type NotifSettings = Record<string, ChannelSettings>
type SectionState = 'loading' | 'loaded' | 'error'

const MAX_INTERESTS = 3

export default function Settings() {
  const navigate = useNavigate()
  const [tags, setTags] = useState<Tag[]>([])
  const [selectedTagIds, setSelectedTagIds] = useState<number[]>([])
  const [citationPrefs, setCitationPrefs] = useState<Record<string, boolean>>({})
  const [notifSettings, setNotifSettings] = useState<NotifSettings>({})
  const [sectionStates, setSectionStates] = useState<Record<string, SectionState>>({
    interests: 'loading',
    citations: 'loading',
    notifications: 'loading',
  })
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle')
  const [saveError, setSaveError] = useState('')
  const [deleteStatus, setDeleteStatus] = useState<'idle' | 'deleting' | 'error'>('idle')
  const [deleteError, setDeleteError] = useState('')
  const [dirty, setDirty] = useState(false)
  const initialRef = useRef<string | null>(null)
  const initialTagIdsRef = useRef<number[]>([])

  const serialize = useCallback(() => {
    return JSON.stringify({ selectedTagIds, citationPrefs, notifSettings })
  }, [selectedTagIds, citationPrefs, notifSettings])

  useEffect(() => {
    const safeJson = (r: Response) => (r.ok ? r.json() : Promise.resolve(null))

    Promise.all([
      api('/interest-tags').then(safeJson),
      api('/me/interests').then(safeJson),
      api('/me/citation-prefs').then(safeJson),
      api('/me/notification-settings').then(safeJson),
    ])
      .then(([tagsData, interestsData, citationData, notifData]) => {
        setTags(tagsData?.tags || [])
        const loadedTagIds = interestsData?.tag_ids || []
        setSelectedTagIds(loadedTagIds)
        initialTagIdsRef.current = loadedTagIds
        setCitationPrefs(citationData?.prefs || {})
        setNotifSettings(notifData?.settings || {})
        setSectionStates({ interests: 'loaded', citations: 'loaded', notifications: 'loaded' })
      })
      .catch(() => {
        setSectionStates({ interests: 'error', citations: 'error', notifications: 'error' })
      })
  }, [])

  useEffect(() => {
    if (initialRef.current === null) {
      initialRef.current = serialize()
      return
    }
    setDirty(serialize() !== initialRef.current)
  }, [serialize])

  const toggleTag = (id: number) => {
    setSelectedTagIds((prev) => {
      if (prev.includes(id)) return prev.filter((x) => x !== id)
      if (prev.length >= MAX_INTERESTS) return prev
      return [...prev, id]
    })
  }

  const toggleCitation = (type: string) => {
    setCitationPrefs((prev) => ({ ...prev, [type]: !prev[type] }))
  }

  const saveAll = useCallback(async () => {
    if (selectedTagIds.length === 0) {
      setSaveError('Select at least one category before saving.')
      setSaveStatus('error')
      return
    }
    setSaveError('')
    setSaveStatus('saving')
    try {
      const res1 = await api('/me/interests', {
        method: 'PUT',
        body: JSON.stringify({ tag_ids: selectedTagIds }),
      })
      if (!res1.ok) throw new Error('Failed to save interests')
      const res2 = await api('/me/citation-prefs', {
        method: 'PUT',
        body: JSON.stringify({ prefs: citationPrefs }),
      })
      if (!res2.ok) throw new Error('Failed to save citation preferences')
      const res3 = await api('/me/notification-settings', {
        method: 'PUT',
        body: JSON.stringify(notifSettings),
      })
      if (!res3.ok) throw new Error('Failed to save notification settings')

      const interestsChanged =
        JSON.stringify(selectedTagIds.sort()) !== JSON.stringify(initialTagIdsRef.current.slice().sort())
      if (interestsChanged) {
        navigate('/discover')
        return
      }

      setSaveStatus('saved')
      initialRef.current = serialize()
      setDirty(false)
      setTimeout(() => setSaveStatus('idle'), 3000)
    } catch {
      setSaveStatus('error')
    }
  }, [selectedTagIds, citationPrefs, notifSettings, serialize, navigate])

  const handleDelete = useCallback(async () => {
    const ok = window.confirm(
      'Are you sure? This will permanently delete all your data, including tracked dependencies, interests, and preferences. Your account will also be removed.',
    )
    if (!ok) return
    setDeleteStatus('deleting')
    setDeleteError('')
    try {
      const res = await api('/me', { method: 'DELETE' })
      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail || 'Deletion failed')
      }
      clearGitHubProviderToken()
      await supabase.auth.signOut()
      navigate('/login', { replace: true })
    } catch (e) {
      setDeleteStatus('error')
      setDeleteError(e instanceof Error ? e.message : 'Deletion failed. Please try again.')
    }
  }, [navigate])

  const SectionLoading = () => (
    <div className="flex items-center justify-center py-8">
      <div className="kite-spinner" />
    </div>
  )

  const SectionError = ({ message }: { message: string }) => (
    <div className="kite-panel kite-text-danger text-center text-sm">{message}</div>
  )

  return (
    <div className="kite-page">
      <div className="kite-page-title-accent">
        <span className="kite-page-kicker">Preferences</span>
        <h2 className="kite-page-title">Settings</h2>
        <p className="kite-page-subtitle">Interests, citations, and notifications</p>
      </div>

      <section className="kite-section-enter mt-8" style={{ animationDelay: '40ms' }}>
        <h3 className="kite-section-title">Interest Tags</h3>
        <p className="text-sm kite-text-muted">
          This is the only place to change your categories after onboarding. Pick up to{' '}
          {MAX_INTERESTS}.
        </p>
        {sectionStates.interests === 'loading' && <SectionLoading />}
        {sectionStates.interests === 'error' && <SectionError message="Failed to load interests." />}
        {sectionStates.interests === 'loaded' && (
          <>
            <div className="mt-3 grid grid-cols-2 gap-2">
              {tags.length === 0 ? (
                <p className="col-span-2 text-sm kite-text-muted">No interest tags available.</p>
              ) : (
                tags.map((tag) => {
                  const isSelected = selectedTagIds.includes(tag.id)
                  const atCap = !isSelected && selectedTagIds.length >= MAX_INTERESTS
                  return (
                    <button
                      key={tag.id}
                      type="button"
                      onClick={() => toggleTag(tag.id)}
                      disabled={atCap}
                      aria-pressed={isSelected}
                      className={`kite-chip ${isSelected ? 'kite-chip-active' : ''}`}
                    >
                      {tag.name}
                    </button>
                  )
                })
              )}
            </div>
            <p className="mt-3 text-sm kite-text-muted" aria-live="polite">
              {selectedTagIds.length >= MAX_INTERESTS
                ? `${MAX_INTERESTS} of ${MAX_INTERESTS} selected — deselect one to swap.`
                : `${selectedTagIds.length} of ${MAX_INTERESTS} selected.`}
            </p>
          </>
        )}
      </section>

      <section className="kite-section-enter mt-8" style={{ animationDelay: '90ms' }}>
        <h3 className="kite-section-title">Citation Sources</h3>
        <p className="text-sm kite-text-muted">Toggle which citation types to show in your feed.</p>
        {sectionStates.citations === 'loading' && <SectionLoading />}
        {sectionStates.citations === 'error' && <SectionError message="Failed to load citation preferences." />}
        {sectionStates.citations === 'loaded' && (
          <div className="mt-3 space-y-2">
            {Object.entries(citationPrefs).map(([type, enabled]) => (
              <label key={type} className="kite-panel flex cursor-pointer items-center justify-between">
                <span className="text-sm font-medium capitalize" style={{ color: 'var(--kite-text)' }}>
                  {type.replace('_', ' ')}
                </span>
                <input
                  type="checkbox"
                  checked={enabled}
                  onChange={() => toggleCitation(type)}
                  className="h-5 w-5 rounded accent-[var(--kite-primary)]"
                />
              </label>
            ))}
          </div>
        )}
      </section>

      <section className="kite-section-enter mt-8" style={{ animationDelay: '140ms' }}>
        <h3 className="kite-section-title">Notification Settings</h3>
        <p className="text-sm kite-text-muted">Choose which updates trigger notifications.</p>
        {sectionStates.notifications === 'loading' && <SectionLoading />}
        {sectionStates.notifications === 'error' && <SectionError message="Failed to load notification settings." />}
        {sectionStates.notifications === 'loaded' && (
          <div className="mt-3 space-y-3">
            {Object.entries(notifSettings).map(([category, channels]) => (
              <div key={category} className="kite-panel">
                <span className="text-sm font-medium capitalize" style={{ color: 'var(--kite-text)' }}>
                  {category}
                </span>
                <div className="mt-2 flex gap-4">
                  <label className="flex items-center gap-2 text-sm kite-text-secondary">
                    <input
                      type="checkbox"
                      checked={channels.in_app}
                      onChange={() =>
                        setNotifSettings((prev) => ({
                          ...prev,
                          [category]: { ...prev[category], in_app: !prev[category].in_app },
                        }))
                      }
                      className="h-4 w-4 rounded accent-[var(--kite-primary)]"
                    />
                    In-app
                  </label>
                  <label className="flex items-center gap-2 text-sm kite-text-secondary">
                    <input
                      type="checkbox"
                      checked={channels.email}
                      onChange={() =>
                        setNotifSettings((prev) => ({
                          ...prev,
                          [category]: { ...prev[category], email: !prev[category].email },
                        }))
                      }
                      className="h-4 w-4 rounded accent-[var(--kite-primary)]"
                    />
                    Email
                  </label>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {saveStatus === 'saved' && (
        <Toast
          message="Settings saved"
          variant="success"
          onDismiss={() => setSaveStatus('idle')}
        />
      )}
      {saveStatus === 'error' && (
        <Toast
          message={saveError || 'Failed to save settings. Please try again.'}
          variant="error"
          onDismiss={() => setSaveStatus('idle')}
        />
      )}

      <button
        type="button"
        onClick={saveAll}
        disabled={saveStatus === 'saving' || !dirty}
        className="kite-btn-primary mt-6 w-full py-3"
      >
        {saveStatus === 'saving' ? 'Saving…' : 'Save Settings'}
      </button>

      <section className="kite-danger-zone">
        <h3 className="kite-section-title kite-text-danger">Danger Zone</h3>
        <p className="mt-1 text-sm kite-text-muted">
          Permanently delete all your data and account. This action cannot be undone.
        </p>
        {deleteStatus === 'error' && (
          <p className="mt-2 text-sm kite-text-danger">{deleteError}</p>
        )}
        <button
          type="button"
          onClick={handleDelete}
          disabled={deleteStatus === 'deleting'}
          className="kite-btn-danger mt-4"
        >
          {deleteStatus === 'deleting' ? 'Deleting…' : 'Delete my data'}
        </button>
      </section>
    </div>
  )
}
