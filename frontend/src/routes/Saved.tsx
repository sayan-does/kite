import { useCallback, useEffect, useState } from 'react'

import ArticleCard, { type ArticleDetailResult } from '../components/ArticleCard'
import { api, updateFeedState } from '../api/client'

interface Citation {
  type: string
  url: string
  title: string
}

interface SavedArticle {
  id: string
  title: string
  summary: string
  one_liner?: string | null
  source?: string | null
  topic?: string | null
  url?: string | null
  citations: Citation[]
  youtube_url?: string | null
  published_at?: string | null
  reading_minutes?: number | null
  is_research?: boolean
  tier?: 'raw' | 'reviewed' | null
}

export default function Saved() {
  const [articles, setArticles] = useState<SavedArticle[]>([])
  const [state, setState] = useState<'loading' | 'ready' | 'empty' | 'error'>('loading')

  useEffect(() => {
    let cancelled = false
    api('/feed/saved')
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((data) => {
        if (cancelled) return
        const list: SavedArticle[] = data.articles || []
        setArticles(list)
        setState(list.length ? 'ready' : 'empty')
      })
      .catch(() => !cancelled && setState('error'))
    return () => {
      cancelled = true
    }
  }, [])

  const handleToggleSave = useCallback(async (id: string, saved: boolean) => {
    try {
      await updateFeedState(id, { saved })
    } catch {
      // optimistic
    }
    if (!saved) setArticles((prev) => prev.filter((a) => a.id !== id))
  }, [])

  const handleExpand = useCallback(async (id: string): Promise<ArticleDetailResult | null> => {
    try {
      const r = await api(`/feed/articles/${id}`)
      if (!r.ok) return null
      const data = await r.json()
      return { body: data.article?.body, generating: data.generating }
    } catch {
      return null
    }
  }, [])

  return (
    <div className="kite-page kite-page-enter">
      <div className="mb-6">
        <span className="kite-page-kicker">Read later</span>
        <h1 className="kite-page-title kite-page-title-accent">Saved</h1>
        <p className="kite-page-subtitle">Articles you bookmarked to come back to.</p>
      </div>

      {state === 'loading' && (
        <div className="flex justify-center py-16"><div className="kite-spinner kite-spinner-lg" /></div>
      )}

      {state === 'error' && (
        <div className="kite-empty"><div className="kite-empty-state">
          <p className="kite-empty-title">Couldn't load saved articles</p>
          <p className="kite-empty-body">Please try again in a moment.</p>
        </div></div>
      )}

      {state === 'empty' && (
        <div className="kite-empty"><div className="kite-empty-state">
          <p className="kite-empty-title">Nothing saved yet</p>
          <p className="kite-empty-body">Tap the bookmark on any article in Discover to save it for later.</p>
        </div></div>
      )}

      {state === 'ready' && (
        <div className="kite-stagger flex flex-col gap-4">
          {articles.map((a, i) => (
            <ArticleCard
              key={a.id}
              id={a.id}
              index={i}
              title={a.title}
              summary={a.summary}
              oneLiner={a.one_liner}
              source={a.source}
              topic={a.topic}
              url={a.url}
              citations={a.citations}
              youtubeUrl={a.youtube_url}
              publishedAt={a.published_at}
              readingMinutes={a.reading_minutes}
              isResearch={Boolean(a.is_research)}
              tier={a.tier ?? 'reviewed'}
              initialSaved
              onToggleSave={handleToggleSave}
              onExpand={handleExpand}
            />
          ))}
        </div>
      )}
    </div>
  )
}
