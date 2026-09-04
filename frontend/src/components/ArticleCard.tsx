import { useState, type MouseEvent } from 'react'

import { normalizeExternalUrl, openExternalUrl } from '../lib/externalUrl'

interface Citation {
  type: string
  url: string
  title: string
}

export interface ArticleDetailResult {
  body?: string | null
  oneLiner?: string | null
  summary?: string | null
  tier?: 'raw' | 'reviewed' | null
  generating?: boolean
}

interface ArticleCardProps {
  id?: string
  title: string
  summary: string
  oneLiner?: string | null
  source?: string | null
  topic?: string | null
  body?: string | null
  url?: string | null
  citations: Citation[]
  youtubeUrl?: string | null
  publishedAt?: string | null
  isResearch?: boolean
  tier?: 'raw' | 'reviewed' | null
  index?: number
  dismissed?: boolean
  onDismiss?: (id: string) => void
  onRead?: (id: string) => void
  onExpand?: (id: string) => Promise<ArticleDetailResult | null>
}

const citationClass: Record<string, string> = {
  blog: 'kite-citation-blog',
  github: 'kite-citation-github',
  official_docs: 'kite-citation-official_docs',
  youtube: 'kite-citation-youtube',
}

function sourceBadgeLabel(source?: string | null, topic?: string | null): string | null {
  if (!source || !topic) return null
  if (source === 'stack') return `From your stack: ${topic}`
  if (source === 'interest') return `From your interests: ${topic}`
  return null
}

function youtubeEmbedUrl(url: string): string {
  if (url.includes('/embed/')) return url
  const watchMatch = url.match(/[?&]v=([\w-]+)/)
  if (watchMatch) return `https://www.youtube.com/embed/${watchMatch[1]}`
  const shortMatch = url.match(/youtu\.be\/([\w-]+)/)
  if (shortMatch) return `https://www.youtube.com/embed/${shortMatch[1]}`
  return url.replace('watch?v=', 'embed/')
}

function hostname(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return url
  }
}

function formatDate(value?: string | null): string | null {
  if (!value) return null
  try {
    return new Date(value)
      .toLocaleDateString(undefined, { day: '2-digit', month: 'short', year: 'numeric' })
      .toUpperCase()
  } catch {
    return null
  }
}

function looksLikeGibberish(text: string): boolean {
  if (!text) return false
  if (/[<>{}|\\]|&(?:#\d+|#x[\da-f]+|[a-z]+);/i.test(text)) return true
  const alnum = (text.match(/[a-z0-9]/gi) || []).length
  if (text.length >= 20 && alnum / text.length < 0.45) return true
  return false
}

function displayFaceText(
  oneLiner: string | null | undefined,
  summary: string,
  title: string,
  tier: 'raw' | 'reviewed' | null | undefined,
): string {
  const candidate = (oneLiner || summary || '').trim()
  if (tier === 'raw' && candidate && looksLikeGibberish(candidate)) {
    return title
  }
  return candidate || title
}

export default function ArticleCard({
  id,
  title,
  summary,
  oneLiner,
  source,
  topic,
  body,
  url,
  citations,
  youtubeUrl,
  publishedAt,
  isResearch = false,
  tier = 'reviewed',
  index = 0,
  dismissed = false,
  onDismiss,
  onRead,
  onExpand,
}: ArticleCardProps) {
  const [expanded, setExpanded] = useState(false)
  const [loadingDetail, setLoadingDetail] = useState(false)
  const [detailBody, setDetailBody] = useState<string | null>(null)
  const [generatingNote, setGeneratingNote] = useState(false)

  const badge = sourceBadgeLabel(source, topic)
  const faceText = displayFaceText(oneLiner, summary, title, tier)
  const showSummary = Boolean(summary && summary !== faceText && !looksLikeGibberish(summary))
  const readerBody = detailBody ?? body
  const sourceUrl = normalizeExternalUrl(url || citations.find((c) => c.url)?.url)
  const paperCitation = citations.find((c) => c.title === 'Paper' || /arxiv\.org|openreview\.net/i.test(c.url))
  const paperUrl = normalizeExternalUrl(paperCitation?.url)
  const dateLabel = formatDate(publishedAt)
  const featured = index === 0
  const badgeClass = source === 'stack' ? 'kite-badge-stack' : 'kite-badge-interest'

  const markRead = () => {
    if (id && onRead) onRead(id)
  }

  const followExternalLink = (e: MouseEvent<HTMLAnchorElement>, href: string | null) => {
    e.preventDefault()
    e.stopPropagation()
    if (!href) return
    markRead()
    openExternalUrl(href)
  }

  const toggleExpanded = async () => {
    if (expanded) {
      setExpanded(false)
      return
    }

    if (id && onRead) onRead(id)

    if (id && onExpand && !readerBody) {
      setLoadingDetail(true)
      try {
        const detail = await onExpand(id)
        if (detail?.body) {
          setDetailBody(detail.body)
        }
        setGeneratingNote(Boolean(detail?.generating))
      } finally {
        setLoadingDetail(false)
      }
    }

    setExpanded(true)
  }

  return (
    <article
      className={[
        'kite-article-card kite-feed-item',
        featured ? 'kite-article-card-featured' : '',
        dismissed ? 'opacity-50' : '',
      ]
        .filter(Boolean)
        .join(' ')}
      style={{ animationDelay: `${index * 60}ms` }}
    >
      <div className="kite-article-head">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          {featured && <span className="kite-label-pill kite-label-pill-primary">Featured</span>}
          {isResearch && <span className="kite-label-pill kite-label-pill-research">Research</span>}
          {tier === 'raw' && (
            <span className="kite-label-pill kite-label-pill-muted" title="Summary not yet reviewed by AI">
              Not yet reviewed
            </span>
          )}
          {badge ? (
            <span className={badgeClass}>{badge}</span>
          ) : (
            <span className="kite-label-pill kite-label-pill-muted">Archive</span>
          )}
        </div>
        {id && onDismiss && !dismissed && (
          <button
            type="button"
            onClick={() => onDismiss(id)}
            className="kite-article-icon-btn"
            aria-label="Dismiss article"
            title="Dismiss"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <path
                d="M18 6L6 18M6 6l12 12"
                stroke="currentColor"
                strokeWidth="1.75"
                strokeLinecap="round"
              />
            </svg>
          </button>
        )}
      </div>

      <div className="kite-article-body">
        <div className="kite-article-meta">
          {dateLabel && <span>{dateLabel}</span>}
          {dateLabel && sourceUrl && <span className="kite-article-meta-dot" />}
          {sourceUrl && (
            <a
              href={sourceUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="kite-link"
              onClick={(e) => followExternalLink(e, sourceUrl)}
            >
              Source: {hostname(sourceUrl)}
            </a>
          )}
          {paperUrl && (
            <>
              <span className="kite-article-meta-dot" />
              <a
                href={paperUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="kite-link"
                onClick={(e) => followExternalLink(e, paperUrl)}
              >
                Paper
              </a>
            </>
          )}
        </div>

        {sourceUrl ? (
          <h3 className="kite-article-title">
            <a
              href={sourceUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="kite-article-title-link"
              onClick={(e) => followExternalLink(e, sourceUrl)}
            >
              {title}
            </a>
          </h3>
        ) : (
          <h3 className="kite-article-title">{title}</h3>
        )}
        <p className="kite-article-excerpt">{faceText}</p>
        {showSummary && <p className="kite-article-excerpt">{summary}</p>}

        {youtubeUrl && (
          <div className="aspect-video overflow-hidden border border-[var(--kite-border)]">
            <iframe
              src={youtubeEmbedUrl(youtubeUrl)}
              title="YouTube video"
              className="h-full w-full"
              allowFullScreen
            />
          </div>
        )}

        {loadingDetail && (
          <p className="text-sm kite-text-secondary animate-pulse">Loading summary…</p>
        )}

        {expanded && readerBody && (
          <p className="whitespace-pre-wrap text-sm leading-relaxed kite-text-secondary">{readerBody}</p>
        )}

        {expanded && generatingNote && (
          <p className="text-xs kite-text-secondary mt-2">
            Full AI summary is still being prepared. Showing best available excerpt.
          </p>
        )}

        <div className="kite-article-footer">
          <div className="kite-article-tags">
            {citations.slice(0, 3).map((c, i) => {
              const citationUrl = normalizeExternalUrl(c.url)
              if (!citationUrl) return null
              return (
              <a
                key={i}
                href={citationUrl}
                target="_blank"
                rel="noopener noreferrer"
                className={`kite-article-tag ${citationClass[c.type] || ''}`}
                onClick={(e) => followExternalLink(e, citationUrl)}
              >
                {c.title || c.type}
              </a>
              )
            })}
            {citations.length > 3 && (
              <span className="kite-article-tag">+{citations.length - 3}</span>
            )}
          </div>

          <div className="kite-article-actions">
            {sourceUrl && (
              <a
                href={sourceUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="kite-btn-secondary text-xs px-3 py-2"
                onClick={(e) => followExternalLink(e, sourceUrl)}
              >
                View source
              </a>
            )}
            <button
              type="button"
              onClick={toggleExpanded}
              disabled={loadingDetail}
              className="kite-btn-primary text-xs px-3 py-2"
            >
              {expanded ? 'Hide' : 'Open'}
              {!expanded && (
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                  <path
                    d="M5 12h14M13 6l6 6-6 6"
                    stroke="currentColor"
                    strokeWidth="1.75"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              )}
            </button>
          </div>
        </div>
      </div>
    </article>
  )
}
