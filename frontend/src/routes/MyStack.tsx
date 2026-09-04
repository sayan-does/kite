import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import EmptyState from '../components/EmptyState'
import ImportStackModal from '../components/ImportStackModal'
import ProjectAccordionRow, {
  type DigestItem,
  type ProjectSummary,
} from '../components/ProjectAccordionRow'

export default function MyStack() {
  const navigate = useNavigate()
  const [projects, setProjects] = useState<ProjectSummary[]>([])
  const [listLoading, setListLoading] = useState(true)
  const [listError, setListError] = useState('')
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [cacheKey, setCacheKey] = useState(0)
  const [showImport, setShowImport] = useState(false)
  const [importSuccess, setImportSuccess] = useState<{ label: string; count: number } | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [formProject, setFormProject] = useState('')
  const [formEcosystem, setFormEcosystem] = useState('npm')
  const [formPackage, setFormPackage] = useState('')
  const [formVersion, setFormVersion] = useState('')
  const [formError, setFormError] = useState('')

  const fetchProjects = useCallback(async () => {
    setListLoading(true)
    setListError('')
    try {
      const res = await api('/stack/projects')
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.detail || 'Failed to load projects')
      }
      const data = await res.json()
      setProjects(data.projects || [])
    } catch (e) {
      setListError(e instanceof Error ? e.message : 'Failed to load projects')
      setProjects([])
    } finally {
      setListLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchProjects()
  }, [fetchProjects])

  const refreshAll = useCallback(async () => {
    setCacheKey((k) => k + 1)
    await fetchProjects()
  }, [fetchProjects])

  const toggleProject = (name: string) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(name)) next.delete(name)
      else next.add(name)
      return next
    })
  }

  const handleRenameProject = async (oldName: string, newName: string): Promise<string | null> => {
    try {
      const res = await api('/stack/projects/rename', {
        method: 'PATCH',
        body: JSON.stringify({ old_name: oldName, new_name: newName }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        return typeof err.detail === 'string' ? err.detail : 'Rename failed'
      }
      setExpanded((prev) => {
        const next = new Set(prev)
        if (next.has(oldName)) {
          next.delete(oldName)
          next.add(newName)
        }
        return next
      })
      await refreshAll()
      return null
    } catch {
      return 'Rename failed'
    }
  }

  const handleDeleteProject = async (name: string) => {
    const res = await api(`/stack/projects/by-name?project_name=${encodeURIComponent(name)}`, {
      method: 'DELETE',
    })
    if (!res.ok && res.status !== 204) {
      const err = await res.json().catch(() => ({}))
      throw new Error(typeof err.detail === 'string' ? err.detail : 'Delete failed')
    }
    setExpanded((prev) => {
      const next = new Set(prev)
      next.delete(name)
      return next
    })
    await refreshAll()
  }

  const openEditForm = (item: DigestItem) => {
    setEditingId(item.id)
    setFormProject(item.project_name)
    setFormEcosystem(item.ecosystem)
    setFormPackage(item.package_name)
    setFormVersion(item.tracked_version)
    setFormError('')
    setShowForm(true)
  }

  const submitForm = async () => {
    setFormError('')
    if (!editingId) return
    if (!formProject.trim() || !formPackage.trim() || !formVersion.trim()) {
      setFormError('Project, package name, and version are required')
      return
    }
    try {
      const res = await api(`/stack/${editingId}`, {
        method: 'PATCH',
        body: JSON.stringify({
          project_name: formProject.trim(),
          ecosystem: formEcosystem,
          package_name: formPackage,
          version: formVersion,
        }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        setFormError(err.detail || 'Failed to save dependency')
        return
      }
      setShowForm(false)
      await refreshAll()
    } catch {
      setFormError('Failed to save dependency')
    }
  }

  const handleDelete = async (item: DigestItem) => {
    if (!item.id) return
    await api(`/stack/${item.id}`, { method: 'DELETE' })
    await refreshAll()
  }

  const openDetail = (item: DigestItem) => {
    navigate(`/my-stack/${encodeURIComponent(item.ecosystem)}/${encodeURIComponent(item.package_name)}`)
  }

  return (
    <div className="kite-page-wide">
      <div className="mb-8 flex flex-wrap items-center justify-between gap-4">
        <div className="kite-page-title-accent">
          <span className="kite-page-kicker">Dependency ledger</span>
          <h2 className="kite-page-title">My Stack</h2>
          <p className="kite-page-subtitle">Projects and their dependency updates</p>
        </div>
        <button type="button" onClick={() => setShowImport(true)} className="kite-btn-primary">
          Import
        </button>
      </div>

      {importSuccess && (
        <p className="mb-4 text-sm kite-text-success">
          Imported {importSuccess.count} dependenc{importSuccess.count === 1 ? 'y' : 'ies'} from {importSuccess.label}.
        </p>
      )}

      <ImportStackModal
        open={showImport}
        onClose={() => setShowImport(false)}
        onImported={(info) => {
          setImportSuccess(info)
          refreshAll()
        }}
      />

      {showForm && (
        <div className="kite-panel mb-6">
          <h3 className="mb-3 text-sm font-semibold" style={{ color: 'var(--kite-text)' }}>
            Edit dependency
          </h3>
          <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap">
            <input
              type="text"
              placeholder="Project name"
              value={formProject}
              onChange={(e) => setFormProject(e.target.value)}
              className="kite-input w-full min-w-0 sm:min-w-[140px] sm:flex-1"
              maxLength={80}
            />
            <select
              value={formEcosystem}
              onChange={(e) => setFormEcosystem(e.target.value)}
              className="kite-select w-full sm:w-auto"
            >
              <option value="npm">npm</option>
              <option value="pip">pip</option>
              <option value="maven">maven</option>
            </select>
            <input
              type="text"
              placeholder="Package name"
              value={formPackage}
              onChange={(e) => setFormPackage(e.target.value)}
              className="kite-input w-full min-w-0 sm:min-w-[180px] sm:flex-1"
            />
            <input
              type="text"
              placeholder="Version"
              value={formVersion}
              onChange={(e) => setFormVersion(e.target.value)}
              className="kite-input w-full min-w-0 sm:min-w-[100px]"
            />
            <div className="flex gap-2">
              <button type="button" onClick={submitForm} className="kite-btn-primary flex-1 sm:flex-none">
                Save
              </button>
              <button
                type="button"
                onClick={() => setShowForm(false)}
                className="kite-btn-secondary flex-1 sm:flex-none"
              >
                Cancel
              </button>
            </div>
          </div>
          {formError && <p className="mt-2 text-sm kite-text-danger">{formError}</p>}
        </div>
      )}

      {listLoading && (
        <div className="flex justify-center py-12">
          <div className="kite-spinner kite-spinner-lg" />
        </div>
      )}

      {!listLoading && listError && (
        <EmptyState
          motif="generic"
          title="Couldn’t load projects"
          description={<p className="kite-text-danger">{listError}</p>}
          action={
            <button type="button" className="kite-btn-secondary" onClick={fetchProjects}>
              Retry
            </button>
          }
        />
      )}

      {!listLoading && !listError && projects.length === 0 && (
        <EmptyState
          motif="stack"
          title="No projects yet"
          description="Import a manifest or connect a GitHub repo to start tracking dependencies."
          action={
            <button type="button" className="kite-btn-primary" onClick={() => setShowImport(true)}>
              Import
            </button>
          }
        />
      )}

      {!listLoading && !listError && projects.length > 0 && (
        <div className="kite-stagger space-y-3">
          {projects.map((project) => (
            <ProjectAccordionRow
              key={project.project_name}
              project={project}
              expanded={expanded.has(project.project_name)}
              onToggle={() => toggleProject(project.project_name)}
              cacheKey={cacheKey}
              onOpenDetail={openDetail}
              onEdit={openEditForm}
              onDelete={handleDelete}
              onRenameProject={handleRenameProject}
              onDeleteProject={handleDeleteProject}
            />
          ))}
        </div>
      )}
    </div>
  )
}
