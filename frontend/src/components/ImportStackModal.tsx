import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import { getGitHubProviderToken, markPendingGitHubOAuth } from '../lib/githubToken'
import { supabase } from '../lib/supabase'

type Tab = 'upload' | 'github'

interface Repo {
  full_name: string
  private: boolean
  default_branch: string
  description: string | null
}

interface TreeEntry {
  name: string
  path: string
  type: string
  is_manifest: boolean
}

interface ImportStackModalProps {
  open: boolean
  onClose: () => void
  onImported: (info: { label: string; count: number }) => void
}

function githubHeaders(): HeadersInit {
  const token = getGitHubProviderToken()
  return token ? { 'X-GitHub-Token': token } : {}
}

export default function ImportStackModal({ open, onClose, onImported }: ImportStackModalProps) {
  const [tab, setTab] = useState<Tab>('upload')
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState('')
  const [projectName, setProjectName] = useState('')

  const [repos, setRepos] = useState<Repo[]>([])
  const [reposLoading, setReposLoading] = useState(false)
  const [selectedRepo, setSelectedRepo] = useState('')
  const [rootPath, setRootPath] = useState('')
  const [entries, setEntries] = useState<TreeEntry[]>([])
  const [treeLoading, setTreeLoading] = useState(false)
  const [selectedFile, setSelectedFile] = useState('')
  const [importing, setImporting] = useState(false)

  const hasGitHubToken = !!getGitHubProviderToken()

  const resetGithubState = () => {
    setRepos([])
    setSelectedRepo('')
    setRootPath('')
    setEntries([])
    setSelectedFile('')
  }

  useEffect(() => {
    if (!open) {
      setTab('upload')
      setError('')
      setUploading(false)
      setImporting(false)
      setProjectName('')
      resetGithubState()
    }
  }, [open])

  const derivedGithubProject = selectedRepo.includes('/')
    ? selectedRepo.split('/').pop() || selectedRepo
    : selectedRepo

  const loadRepos = useCallback(async () => {
    setReposLoading(true)
    setError('')
    try {
      const res = await api('/stack/github/repos', { headers: githubHeaders() })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        setError(err.detail || 'Could not list repositories. Reconnect GitHub and try again.')
        setRepos([])
        return
      }
      const data = await res.json()
      setRepos(data.repos || [])
    } catch {
      setError('Could not list repositories')
      setRepos([])
    } finally {
      setReposLoading(false)
    }
  }, [])

  useEffect(() => {
    if (open && tab === 'github' && hasGitHubToken && repos.length === 0 && !reposLoading) {
      loadRepos()
    }
  }, [open, tab, hasGitHubToken, repos.length, reposLoading, loadRepos])

  const loadTree = async () => {
    if (!selectedRepo) return
    setTreeLoading(true)
    setError('')
    setSelectedFile('')
    try {
      const params = new URLSearchParams({ repo: selectedRepo, path: rootPath.trim() })
      const res = await api(`/stack/github/tree?${params}`, { headers: githubHeaders() })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        setError(err.detail || 'Could not list directory')
        setEntries([])
        return
      }
      const data = await res.json()
      setEntries(data.entries || [])
      const manifests = (data.entries || []).filter((e: TreeEntry) => e.is_manifest)
      if (manifests.length === 1) setSelectedFile(manifests[0].name)
    } catch {
      setError('Could not list directory')
      setEntries([])
    } finally {
      setTreeLoading(false)
    }
  }

  const connectGitHub = () => {
    markPendingGitHubOAuth()
    supabase.auth.signInWithOAuth({
      provider: 'github',
      options: {
        scopes: 'read:user repo',
        redirectTo: `${window.location.origin}/my-stack`,
      },
    })
  }

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    const trimmed = projectName.trim()
    if (!trimmed) {
      setError('Project name is required')
      e.target.value = ''
      return
    }
    setUploading(true)
    setError('')
    try {
      const formData = new FormData()
      formData.append('file', file)
      formData.append('project_name', trimmed)
      const res = await api('/stack/upload', { method: 'POST', headers: {}, body: formData })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        setError(err.detail || 'Upload failed')
        return
      }
      const data = await res.json()
      onImported({ label: `${trimmed} · ${file.name}`, count: data.count ?? 0 })
      onClose()
    } catch {
      setError('Upload failed')
    } finally {
      setUploading(false)
      e.target.value = ''
    }
  }

  const handleImport = async () => {
    if (!selectedRepo || !selectedFile) return
    setImporting(true)
    setError('')
    try {
      const res = await api('/stack/github/import', {
        method: 'POST',
        headers: githubHeaders(),
        body: JSON.stringify({
          repo: selectedRepo,
          path: rootPath.trim(),
          filename: selectedFile,
        }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        setError(typeof err.detail === 'string' ? err.detail : 'Import failed')
        return
      }
      const data = await res.json()
      const project = data.project_name || derivedGithubProject
      onImported({
        label: `${project} · ${selectedRepo}/${data.path || selectedFile}`,
        count: data.count ?? 0,
      })
      onClose()
    } catch {
      setError('Import failed')
    } finally {
      setImporting(false)
    }
  }

  if (!open) return null

  const manifests = entries.filter((e) => e.is_manifest)
  const dirs = entries.filter((e) => e.type === 'dir')

  return (
    <div
      className="kite-modal-backdrop"
      role="dialog"
      aria-modal="true"
      aria-labelledby="import-stack-title"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div className="kite-panel kite-modal-panel">
        <div className="mb-4 flex items-start justify-between gap-3">
          <div>
            <h3 id="import-stack-title" className="text-base font-semibold" style={{ color: 'var(--kite-text)' }}>
              Import dependencies
            </h3>
            <p className="mt-1 text-sm kite-text-muted">Upload a manifest or pull one from a GitHub repo.</p>
          </div>
          <button type="button" onClick={onClose} className="kite-btn-secondary text-xs px-2 py-1" aria-label="Close">
            Close
          </button>
        </div>

        <div className="mb-4 flex gap-2" role="tablist">
          <button
            type="button"
            role="tab"
            aria-selected={tab === 'upload'}
            className={tab === 'upload' ? 'kite-btn-primary text-xs' : 'kite-btn-secondary text-xs'}
            onClick={() => {
              setTab('upload')
              setError('')
            }}
          >
            Upload
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={tab === 'github'}
            className={tab === 'github' ? 'kite-btn-primary text-xs' : 'kite-btn-secondary text-xs'}
            onClick={() => {
              setTab('github')
              setError('')
            }}
          >
            GitHub
          </button>
        </div>

        {error && <p className="mb-3 text-sm kite-text-danger">{error}</p>}

        {tab === 'upload' && (
          <div className="space-y-4">
            <div>
              <label className="mb-1 block text-xs font-medium kite-text-muted" htmlFor="upload-project">
                Project name
              </label>
              <input
                id="upload-project"
                type="text"
                className="kite-input w-full"
                placeholder="e.g. my-api"
                value={projectName}
                onChange={(e) => setProjectName(e.target.value)}
                maxLength={80}
              />
            </div>
            <p className="text-sm kite-text-secondary">
              Supported: package.json, requirements.txt, pyproject.toml, pom.xml
            </p>
            <label className={`kite-btn-primary inline-flex ${!projectName.trim() || uploading ? 'opacity-60' : 'cursor-pointer'}`}>
              {uploading ? 'Uploading…' : 'Choose file'}
              <input
                type="file"
                accept=".json,.txt,.toml,.xml,package.json,requirements.txt,pyproject.toml,pom.xml"
                className="hidden"
                onChange={handleUpload}
                disabled={uploading || !projectName.trim()}
              />
            </label>
          </div>
        )}

        {tab === 'github' && (
          <div className="space-y-4">
            {!hasGitHubToken ? (
              <div>
                <p className="mb-3 text-sm kite-text-secondary">
                  Connect GitHub to list your repos and import a dependency file.
                </p>
                <button type="button" onClick={connectGitHub} className="kite-btn-primary">
                  Connect GitHub
                </button>
              </div>
            ) : (
              <>
                <div>
                  <label className="mb-1 block text-xs font-medium kite-text-muted" htmlFor="gh-repo">
                    Repository
                  </label>
                  <select
                    id="gh-repo"
                    className="kite-select w-full"
                    value={selectedRepo}
                    onChange={(e) => {
                      setSelectedRepo(e.target.value)
                      setEntries([])
                      setSelectedFile('')
                    }}
                    disabled={reposLoading}
                  >
                    <option value="">{reposLoading ? 'Loading repos…' : 'Select a repo'}</option>
                    {repos.map((r) => (
                      <option key={r.full_name} value={r.full_name}>
                        {r.full_name}
                        {r.private ? ' (private)' : ''}
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    className="mt-2 text-xs kite-text-muted underline"
                    onClick={loadRepos}
                    disabled={reposLoading}
                  >
                    Refresh repos
                  </button>
                </div>

                <div>
                  <label className="mb-1 block text-xs font-medium kite-text-muted" htmlFor="gh-path">
                    Root path
                  </label>
                  <div className="flex flex-wrap gap-2">
                    <input
                      id="gh-path"
                      type="text"
                      className="kite-input min-w-[160px] flex-1"
                      placeholder="e.g. backend (empty = repo root)"
                      value={rootPath}
                      onChange={(e) => setRootPath(e.target.value)}
                    />
                    <button
                      type="button"
                      className="kite-btn-secondary"
                      onClick={loadTree}
                      disabled={!selectedRepo || treeLoading}
                    >
                      {treeLoading ? 'Listing…' : 'List files'}
                    </button>
                  </div>
                </div>

                {dirs.length > 0 && (
                  <div>
                    <p className="mb-1 text-xs kite-text-muted">Folders</p>
                    <div className="flex flex-wrap gap-2">
                      {dirs.map((d) => (
                        <button
                          key={d.path}
                          type="button"
                          className="kite-btn-secondary text-xs"
                          onClick={() => setRootPath(d.path)}
                        >
                          {d.name}/
                        </button>
                      ))}
                    </div>
                  </div>
                )}

                {manifests.length > 0 && (
                  <div>
                    <label className="mb-1 block text-xs font-medium kite-text-muted" htmlFor="gh-file">
                      Manifest file
                    </label>
                    <select
                      id="gh-file"
                      className="kite-select w-full"
                      value={selectedFile}
                      onChange={(e) => setSelectedFile(e.target.value)}
                    >
                      <option value="">Select a file</option>
                      {manifests.map((m) => (
                        <option key={m.path} value={m.name}>
                          {m.name}
                        </option>
                      ))}
                    </select>
                  </div>
                )}

                {entries.length > 0 && manifests.length === 0 && (
                  <p className="text-sm kite-text-muted">
                    No supported manifests in this folder. Try another root path (e.g. backend).
                  </p>
                )}

                {selectedRepo && (
                  <p className="text-sm kite-text-secondary">
                    Project: <span style={{ color: 'var(--kite-text)' }}>{derivedGithubProject}</span>
                    <span className="kite-text-muted"> (from repo name)</span>
                  </p>
                )}

                <button
                  type="button"
                  className="kite-btn-primary"
                  onClick={handleImport}
                  disabled={!selectedRepo || !selectedFile || importing}
                >
                  {importing ? 'Importing…' : 'Import'}
                </button>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
