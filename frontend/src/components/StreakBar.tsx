export interface Streak {
  current_streak: number
  longest_streak: number
  last_success_date: string | null
}

const WINDOW_DAYS = 7

function utcDateString(daysAgo: number): string {
  const now = new Date()
  const day = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate() - daysAgo)
  return new Date(day).toISOString().slice(0, 10)
}

interface StreakBarProps {
  streak: Streak | null
  passedToday?: boolean
}

export default function StreakBar({ streak, passedToday = false }: StreakBarProps) {
  const current = streak?.current_streak ?? 0
  const longest = streak?.longest_streak ?? 0
  const lastSuccess = streak?.last_success_date ?? null

  // The dots reconstruct the run backwards from the last successful day, which
  // is all the server needs to send for a seven-day window.
  const days = Array.from({ length: WINDOW_DAYS }, (_, i) => {
    const offset = WINDOW_DAYS - 1 - i
    const date = utcDateString(offset)
    const daysBeforeLastSuccess = lastSuccess
      ? Math.round(
          (Date.parse(`${lastSuccess}T00:00:00Z`) - Date.parse(`${date}T00:00:00Z`)) / 86_400_000,
        )
      : null
    const done =
      daysBeforeLastSuccess !== null &&
      daysBeforeLastSuccess >= 0 &&
      daysBeforeLastSuccess < current
    return { date, done, isToday: offset === 0 }
  })

  return (
    <div className="kite-streak">
      <div className="kite-streak-count">
        <span className="kite-streak-flame" aria-hidden="true">
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
            <path
              d="M8 1.5c.6 2.2-.9 3-1.7 4.1-.7 1-.6 2 .2 2.6.5.4.6-.5.4-1.3 1.3.7 2.3 2 2.3 3.4 0 1.7-1.4 3.2-3.2 3.2S2.8 12 2.8 10.3c0-3 2.6-4 3.4-6C7 2.9 7.4 2 8 1.5Z"
              fill="currentColor"
            />
            <path
              d="M10.4 5.6c1.7 1.1 2.8 2.8 2.8 4.7 0 1.8-1.2 3.3-2.9 3.9.8-.9 1.3-2 1.3-3.2 0-2.1-.5-4-1.2-5.4Z"
              fill="currentColor"
              opacity="0.55"
            />
          </svg>
        </span>
        <strong>{current}</strong>
        <span className="kite-text-muted">day{current === 1 ? '' : 's'}</span>
      </div>

      <ol className="kite-streak-dots" aria-label={`${current} day streak`}>
        {days.map((day) => (
          <li
            key={day.date}
            title={day.date}
            className={[
              'kite-streak-dot',
              day.done ? 'kite-streak-dot-done' : '',
              day.isToday ? 'kite-streak-dot-today' : '',
            ]
              .filter(Boolean)
              .join(' ')}
          />
        ))}
      </ol>

      <p className="kite-streak-hint">
        {passedToday
          ? 'Today is banked. Come back tomorrow to keep it going.'
          : current > 0
            ? 'Pass today’s quiz to keep your streak alive.'
            : 'Pass today’s quiz to start a streak.'}
        {longest > current && <> Best: {longest} days.</>}
      </p>
    </div>
  )
}
