export interface FeedProgressData {
  status: string
  stage: string
  percent: number
  articles_ready: number
  categories_total: number
  categories_ready: number
  per_category: Record<string, number>
  topics: string[]
  error?: string | null
}

const STAGE_LABELS: Record<string, string> = {
  queued: 'Queued',
  collecting: 'Reading your sources',
  ranking: 'Ranking and de-duplicating',
  reviewing: 'Writing summaries',
  done: 'Done',
}

interface FeedProgressProps {
  data: FeedProgressData | null
  selectedTag?: string
}

export default function FeedProgress({ data, selectedTag }: FeedProgressProps) {
  const percent = Math.max(0, Math.min(100, data?.percent ?? 0))
  const stage = STAGE_LABELS[data?.stage ?? 'queued'] ?? 'Working'
  const categories = data?.topics ?? []

  return (
    <div className="kite-panel kite-section-enter">
      <div className="flex items-baseline justify-between gap-3">
        <p className="text-sm font-semibold" style={{ color: 'var(--kite-text)' }}>
          {selectedTag ? `Building your ${selectedTag} feed` : 'Building your discovery feed'}
        </p>
        <span className="kite-feed-count text-sm font-semibold">{percent}%</span>
      </div>

      <div
        className="kite-progress mt-3"
        role="progressbar"
        aria-valuenow={percent}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label="Feed generation progress"
      >
        <div className="kite-progress-fill" style={{ width: `${percent}%` }} />
      </div>

      <p className="mt-2 text-xs kite-text-muted" aria-live="polite">
        {stage}
        {data && data.categories_total > 0 && (
          <>
            {' · '}
            {data.categories_ready} of {data.categories_total} categor
            {data.categories_total === 1 ? 'y' : 'ies'} ready
          </>
        )}
        {data && data.articles_ready > 0 && (
          <>
            {' · '}
            {data.articles_ready} article{data.articles_ready === 1 ? '' : 's'} so far
          </>
        )}
      </p>

      {categories.length > 0 && (
        <ul className="mt-3 flex flex-wrap gap-2">
          {categories.map((name) => {
            const count = data?.per_category?.[name] ?? 0
            return (
              <li
                key={name}
                className={`kite-label-pill ${count > 0 ? '' : 'kite-label-pill-muted'}`}
              >
                {name}
                {count > 0 ? ` · ${count}` : ' · pending'}
              </li>
            )
          })}
        </ul>
      )}

      {data?.error && (
        <p className="mt-3 text-xs kite-text-danger">
          Some sources failed. Showing whatever was collected.
        </p>
      )}
    </div>
  )
}
