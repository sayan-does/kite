import { useCallback, useEffect, useRef, useState } from 'react'
import { api, updateFeedState } from '../api/client'
import ArticleCard from '../components/ArticleCard'
import EmptyState from '../components/EmptyState'
import FeedProgress, { type FeedProgressData } from '../components/FeedProgress'
import FeedSkeleton from '../components/FeedSkeleton'
import QuizCard, { type QuizSession } from '../components/QuizCard'
import StreakBar from '../components/StreakBar'
import { CACHE_KEY_ALL, cacheKey, isCacheStale } from '../hooks/useFeedCache'

interface Citation {
  type: string
  url: string
  title: string
}

interface Article {
  id: string
  tag_id: number
  title: string
  summary: string
  one_liner?: string | null
  source?: string | null
  topic?: string | null
  body?: string | null
  url?: string | null
  citations: Citation[]
  youtube_url?: string | null
  published_at?: string | null
  is_research?: boolean
  tier?: 'raw' | 'reviewed' | null
  score?: number | null
}

interface Tag {
  id: number
  name: string
}

interface FeedCacheEntry {
  articles: Article[]
  hasNext: boolean
  fetchedAt: number
}

type FeedState = 'loading' | 'generating' | 'ready' | 'empty' | 'timeout' | 'tag_empty'

const POLL_INTERVAL = 5000
const POLL_TIMEOUT = 120000
// The progress bar is polled faster than the feed itself so the percentage
// moves smoothly between the 5s article checks.
const PROGRESS_POLL_INTERVAL = 1500
// A category collect is forced and bounded, so it needs far less patience than
// the initial whole-feed build.
const TAG_POLL_TIMEOUT = 30000

function articlesEqual(a: Article[], b: Article[]): boolean {
  if (a.length !== b.length) return false
  return a.every((item, i) => {
    const other = b[i]
    return item.id === other.id && item.tier === other.tier && item.title === other.title
  })
}

function mergeArticles(prev: Article[], incoming: Article[]): Article[] {
  if (prev.length === 0) return incoming
  const prevMap = new Map(prev.map((a) => [a.id, a]))
  return incoming.map((a) => {
    const old = prevMap.get(a.id)
    if (old && old.tier === 'raw' && a.tier === 'reviewed') {
      return { ...old, ...a }
    }
    return a
  })
}

export default function Discover() {
  const [articles, setArticles] = useState<Article[]>([])
  const [tags, setTags] = useState<Tag[]>([])
  const [selectedTag, setSelectedTag] = useState<string>('')
  const [page, setPage] = useState(1)
  const [hasNext, setHasNext] = useState(false)
  const [dismissedIds, setDismissedIds] = useState<Set<string>>(new Set())
  const [feedState, setFeedState] = useState<FeedState>('loading')
  const [hasInterests, setHasInterests] = useState(false)
  const [interestTagIds, setInterestTagIds] = useState<number[]>([])
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [progress, setProgress] = useState<FeedProgressData | null>(null)
  const [quiz, setQuiz] = useState<QuizSession | null>(null)
  const [quizEnabled, setQuizEnabled] = useState(false)

  const feedCacheRef = useRef<Map<string, FeedCacheEntry>>(new Map())
  const abortRef = useRef<AbortController | null>(null)
  const prefetchAbortRef = useRef<AbortController | null>(null)
  const prefetchStartedRef = useRef(false)
  const pollingRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const pollStartRef = useRef<number>(0)
  const mountedRef = useRef(true)
  const hasEverHadArticlesRef = useRef(false)

  const writeCache = useCallback((tag: string, entry: FeedCacheEntry) => {
    feedCacheRef.current.set(cacheKey(tag), entry)
  }, [])

  const applyFeedPage = useCallback((
    tag: string,
    pageNum: number,
    incoming: Article[],
    hasNextPage: boolean,
    options?: { background?: boolean },
  ) => {
    const now = Date.now()
    if (pageNum === 1) {
      setArticles((prev) => {
        const base = options?.background ? prev : []
        const merged = mergeArticles(base, incoming)
        if (options?.background && articlesEqual(prev, merged)) {
          return prev
        }
        return merged
      })
      writeCache(tag, {
        articles: incoming,
        hasNext: hasNextPage,
        fetchedAt: now,
      })
      if (incoming.length > 0) {
        hasEverHadArticlesRef.current = true
      }
    } else {
      setArticles((prev) => {
        const merged = [...prev, ...incoming]
        writeCache(tag, {
          articles: merged,
          hasNext: hasNextPage,
          fetchedAt: now,
        })
        return merged
      })
    }
    setHasNext(hasNextPage)
  }, [writeCache])

  const fetchFeed = useCallback(async (
    tag: string,
    pageNum: number,
    options?: { signal?: AbortSignal; background?: boolean },
  ) => {
    const params = new URLSearchParams()
    if (tag) params.set('tag', tag)
    params.set('page', String(pageNum))
    params.set('view', 'list')
    try {
      const res = await api(`/feed?${params}`, { signal: options?.signal })
      if (!res.ok) return null
      const data = await res.json()
      if (!mountedRef.current) return null

      const incoming: Article[] = data.articles || []
      applyFeedPage(tag, pageNum, incoming, Boolean(data.has_next), options)
      return data
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        return null
      }
      return null
    }
  }, [applyFeedPage])

  const prefetchAllFeeds = useCallback(async (signal?: AbortSignal) => {
    try {
      const res = await api('/feed/prefetch?view=list', { signal })
      if (!res.ok || !mountedRef.current) return
      const data = await res.json()
      const feeds = data.feeds as Record<string, { articles: Article[]; has_next: boolean }>
      const fetchedAt = Date.now()
      for (const [key, feed] of Object.entries(feeds)) {
        feedCacheRef.current.set(key, {
          articles: feed.articles || [],
          hasNext: Boolean(feed.has_next),
          fetchedAt,
        })
      }
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') return
    }
  }, [])

  useEffect(() => {
    mountedRef.current = true
    return () => { mountedRef.current = false }
  }, [])

  useEffect(() => {
    api('/interest-tags')
      .then((r) => r.json())
      .then((data) => setTags(data.tags || []))
  }, [])

  useEffect(() => {
    api('/me/interests')
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        const ids: number[] = data?.tag_ids || []
        setInterestTagIds(ids)
        setHasInterests(ids.length > 0)
      })
      .catch(() => {})
  }, [])

  useEffect(() => {
    api('/quiz/today')
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (!data || data.enabled === false) {
          setQuizEnabled(false)
          setQuiz(null)
          return
        }
        setQuizEnabled(true)
        setQuiz(data)
      })
      .catch(() => {})
  }, [])

  const refreshTag = useCallback(async (tag: string, signal?: AbortSignal) => {
    try {
      const res = await api(`/feed/refresh?tag=${encodeURIComponent(tag)}&view=list`, {
        method: 'POST',
        signal,
      })
      if (!res.ok || !mountedRef.current) return null
      return await res.json() as {
        articles?: Article[]
        has_next?: boolean
        timed_out?: boolean
      }
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') return null
      return null
    }
  }, [])

  const checkAndPoll = useCallback(async (tag: string) => {
    const data = await fetchFeed(tag, 1)
    if (!mountedRef.current) return

    if (data && data.articles && data.articles.length > 0) {
      setFeedState('ready')
      if (tag === '' && !prefetchStartedRef.current) {
        prefetchStartedRef.current = true
        prefetchAbortRef.current?.abort()
        prefetchAbortRef.current = new AbortController()
        void prefetchAllFeeds(prefetchAbortRef.current.signal)
      }
      return
    }

    const elapsed = Date.now() - pollStartRef.current
    if (elapsed >= (tag ? TAG_POLL_TIMEOUT : POLL_TIMEOUT)) {
      setFeedState(tag ? 'tag_empty' : 'timeout')
      return
    }

    pollingRef.current = setTimeout(() => { void checkAndPoll(tag) }, POLL_INTERVAL)
  }, [fetchFeed, prefetchAllFeeds])

  const startPolling = useCallback((tag: string) => {
    pollStartRef.current = Date.now()
    setFeedState('generating')
    pollingRef.current = setTimeout(() => { void checkAndPoll(tag) }, POLL_INTERVAL)
  }, [checkAndPoll])

  useEffect(() => {
    abortRef.current?.abort()
    abortRef.current = new AbortController()
    const signal = abortRef.current.signal

    setPage(1)
    setDismissedIds(new Set())

    const key = cacheKey(selectedTag)
    const cached = feedCacheRef.current.get(key)
    const allCached = feedCacheRef.current.get(CACHE_KEY_ALL)
    const cacheIsStale = cached ? isCacheStale(cached.fetchedAt) : false

    if (cached) {
      setArticles(cached.articles)
      setHasNext(cached.hasNext)
      setFeedState(cached.articles.length > 0 ? 'ready' : (selectedTag ? 'tag_empty' : 'ready'))
    } else if (selectedTag && allCached) {
      const preview = allCached.articles.filter((a) => a.topic === selectedTag)
      if (preview.length > 0) {
        setArticles(preview)
        setFeedState('ready')
      } else {
        setArticles([])
        setFeedState('loading')
      }
    } else {
      setArticles([])
      setFeedState('loading')
    }

    const needsRefresh = !cached || cacheIsStale
    if (needsRefresh) {
      setIsRefreshing(true)
      fetchFeed(selectedTag, 1, { signal, background: Boolean(cached) }).then(async (data) => {
        if (!mountedRef.current || signal.aborted) return
        setIsRefreshing(false)

        if (data?.articles?.length) {
          setFeedState('ready')
          return
        }

        if (cached) {
          setFeedState(cached.articles.length > 0 ? 'ready' : (selectedTag ? 'tag_empty' : 'ready'))
          return
        }

        if (selectedTag) {
          // An empty category means nothing was ever collected for it, so ask
          // for a forced collect instead of declaring it empty.
          setFeedState('generating')
          const filled = await refreshTag(selectedTag, signal)
          if (!mountedRef.current || signal.aborted) return

          if (filled?.articles?.length) {
            applyFeedPage(selectedTag, 1, filled.articles, Boolean(filled.has_next))
            setFeedState('ready')
          } else if (filled?.timed_out) {
            startPolling(selectedTag)
          } else {
            setFeedState('tag_empty')
          }
          return
        }

        let interested = hasInterests
        try {
          const r = await api('/me/interests')
          if (r.ok) {
            const body = await r.json()
            interested = !!body?.tag_ids?.length
            setHasInterests(interested)
          }
        } catch {
          // keep prior hasInterests
        }

        if (interested && !hasEverHadArticlesRef.current && selectedTag === '') {
          startPolling('')
        } else if (!interested) {
          setFeedState('empty')
        } else {
          setFeedState('ready')
        }
      })
    } else {
      setIsRefreshing(false)
    }

    return () => {
      abortRef.current?.abort()
      if (pollingRef.current) clearTimeout(pollingRef.current)
    }
  }, [selectedTag, fetchFeed, hasInterests, startPolling, refreshTag, applyFeedPage])

  useEffect(() => {
    if (feedState !== 'generating') {
      setProgress(null)
      return
    }

    let cancelled = false
    const controller = new AbortController()

    const tick = async () => {
      try {
        const res = await api('/feed/progress', { signal: controller.signal })
        if (!res.ok || cancelled) return
        setProgress(await res.json())
      } catch {
        // Progress is cosmetic; a failed poll must not disturb the feed.
      }
    }

    void tick()
    const timer = setInterval(() => { void tick() }, PROGRESS_POLL_INTERVAL)
    return () => {
      cancelled = true
      controller.abort()
      clearInterval(timer)
    }
  }, [feedState])

  useEffect(() => {
    if (prefetchStartedRef.current || feedState !== 'ready' || selectedTag !== '') return
    if (!feedCacheRef.current.get(CACHE_KEY_ALL)?.articles.length) return

    prefetchStartedRef.current = true
    prefetchAbortRef.current?.abort()
    prefetchAbortRef.current = new AbortController()
    void prefetchAllFeeds(prefetchAbortRef.current.signal)

    return () => {
      prefetchAbortRef.current?.abort()
    }
  }, [feedState, selectedTag, prefetchAllFeeds])

  const retry = () => {
    setFeedState('generating')

    if (selectedTag) {
      void refreshTag(selectedTag).then((filled) => {
        if (!mountedRef.current) return
        if (filled?.articles?.length) {
          applyFeedPage(selectedTag, 1, filled.articles, Boolean(filled.has_next))
          setFeedState('ready')
        } else if (filled?.timed_out) {
          startPolling(selectedTag)
        } else {
          setFeedState('tag_empty')
        }
      })
      return
    }

    pollStartRef.current = Date.now()
    pollingRef.current = setTimeout(() => { void checkAndPoll('') }, POLL_INTERVAL)
  }

  const loadMore = () => {
    const next = page + 1
    setPage(next)
    fetchFeed(selectedTag, next)
  }

  const handleDismiss = useCallback(async (articleId: string) => {
    setDismissedIds((prev) => new Set(prev).add(articleId))
    setArticles((prev) => {
      const next = prev.filter((a) => a.id !== articleId)
      writeCache(selectedTag, {
        articles: next,
        hasNext,
        fetchedAt: Date.now(),
      })
      return next
    })
    try {
      await updateFeedState(articleId, { dismissed: true })
    } catch {
      setDismissedIds((prev) => {
        const next = new Set(prev)
        next.delete(articleId)
        return next
      })
      fetchFeed(selectedTag, 1, { background: true })
    }
  }, [fetchFeed, selectedTag, hasNext, writeCache])

  const handleRead = useCallback(async (articleId: string) => {
    try {
      await updateFeedState(articleId, { seen: true, read: true })
    } catch {
      // Non-blocking; feed still usable if state sync fails.
    }
  }, [])

  const handleExpand = useCallback(async (articleId: string) => {
    try {
      const res = await api(`/feed/articles/${articleId}`)
      if (!res.ok) return null
      const data = await res.json()
      const article = data.article
      if (!article) return null

      setArticles((prev) =>
        prev.map((a) =>
          a.id === articleId
            ? {
                ...a,
                body: article.body ?? a.body,
                one_liner: article.one_liner ?? a.one_liner,
                summary: article.summary ?? a.summary,
                tier: article.tier ?? a.tier,
              }
            : a,
        ),
      )

      const tag = selectedTag
      const cached = feedCacheRef.current.get(tag)
      if (cached) {
        writeCache(tag, {
          ...cached,
          articles: cached.articles.map((a) =>
            a.id === articleId
              ? {
                  ...a,
                  body: article.body ?? a.body,
                  one_liner: article.one_liner ?? a.one_liner,
                  summary: article.summary ?? a.summary,
                  tier: article.tier ?? a.tier,
                }
              : a,
          ),
        })
      }

      return {
        body: article.body,
        oneLiner: article.one_liner,
        summary: article.summary,
        tier: article.tier,
        generating: Boolean(data.generating),
      }
    } catch {
      return null
    }
  }, [selectedTag, writeCache])

  const filteredArticles = articles.filter((a) => !dismissedIds.has(a.id))

  // The dropdown filters the feed you already have; it is not a category
  // picker, so it only lists categories the user actually follows.
  const myTags = tags.filter((t) => interestTagIds.includes(t.id))

  const showSkeleton = feedState === 'loading' && filteredArticles.length === 0

  return (
    <div className="kite-page-wide">
      <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
        <div className="kite-page-title-accent">
          <h2 className="kite-page-title">Discover Feed</h2>
          <p className="kite-page-subtitle">
            Your personalized tech briefing
            {feedState === 'ready' && filteredArticles.length > 0 && (
              <span className="kite-feed-count">
                {' '}
                · {filteredArticles.length} article{filteredArticles.length !== 1 ? 's' : ''}
              </span>
            )}
            {isRefreshing && (
              <span className="kite-label-pill kite-label-pill-muted ml-2">Updating…</span>
            )}
          </p>
        </div>
        <select
          value={selectedTag}
          onChange={(e) => setSelectedTag(e.target.value)}
          className="kite-select"
          aria-label="Filter by tag"
        >
          <option value="">All tags</option>
          {myTags.map((t) => (
            <option key={t.id} value={t.name}>
              {t.name}
            </option>
          ))}
        </select>
      </div>

      {hasInterests && quizEnabled && (
        <div className="mb-4 space-y-3">
          <StreakBar streak={quiz?.streak ?? null} passedToday={Boolean(quiz?.passed)} />
          {/* Once articles are in, the quiz collapses to a one-line header so it
              stays reachable without pushing the feed down. */}
          <QuizCard
            session={quiz}
            onSession={setQuiz}
            defaultCollapsed={feedState === 'ready' && filteredArticles.length > 0}
          />
        </div>
      )}

      {feedState === 'generating' && (
        <div className="mb-4">
          <FeedProgress data={progress} selectedTag={selectedTag} />
        </div>
      )}

      <div className="space-y-4 kite-stagger">
        {showSkeleton && <FeedSkeleton />}

        {filteredArticles.map((a, i) => (
          <ArticleCard
            key={a.id}
            id={a.id}
            index={i}
            title={a.title}
            summary={a.summary}
            oneLiner={a.one_liner}
            source={a.source}
            topic={a.topic}
            body={a.body}
            url={a.url}
            citations={a.citations}
            youtubeUrl={a.youtube_url}
            publishedAt={a.published_at}
            isResearch={Boolean(a.is_research)}
            tier={a.tier ?? 'reviewed'}
            onDismiss={handleDismiss}
            onRead={handleRead}
            onExpand={handleExpand}
          />
        ))}

        {feedState === 'generating' && filteredArticles.length === 0 && <FeedSkeleton />}

        {feedState === 'timeout' && filteredArticles.length === 0 && (
          <EmptyState
            motif="discover"
            title="Still generating your feed"
            description="This can take a minute. Articles will appear once ready."
            action={
              <button type="button" onClick={retry} className="kite-btn-primary">
                Check again
              </button>
            }
          />
        )}

        {feedState === 'tag_empty' && filteredArticles.length === 0 && (
          <EmptyState
            motif="discover"
            title={`No articles for ${selectedTag}`}
            description="Nothing was published for this category recently. Try another, or check again."
            action={
              <button type="button" onClick={retry} className="kite-btn-primary">
                Check again
              </button>
            }
          />
        )}

        {feedState === 'empty' && filteredArticles.length === 0 && (
          <EmptyState
            motif="discover"
            title="No articles yet"
            description={
              <>
                Pick your interests in{' '}
                <a href="/settings" className="kite-link">Settings</a>{' '}
                to personalise your feed.
              </>
            }
          />
        )}
      </div>

      {hasNext && (
        <button type="button" onClick={loadMore} className="kite-btn-secondary mx-auto mt-8 block">
          Load more
        </button>
      )}
    </div>
  )
}
