import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import type { Streak } from './StreakBar'

export interface QuizQuestion {
  position: number
  question: string
  options: string[]
  chosen_index: number | null
  correct_index?: number
  is_correct?: boolean
}

export interface QuizSession {
  state: 'not_started' | 'niche_pending' | 'questions_ready' | 'submitted'
  session_id?: string
  topic?: string | null
  niche?: string | null
  niche_options?: string[]
  questions?: QuizQuestion[]
  correct_count?: number | null
  passed?: boolean | null
  streak: Streak
  pass_threshold: number
  questions_per_quiz: number
}

interface QuizCardProps {
  session: QuizSession | null
  onSession: (session: QuizSession) => void
  defaultCollapsed?: boolean
}

export default function QuizCard({ session, onSession, defaultCollapsed = false }: QuizCardProps) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [answers, setAnswers] = useState<Record<number, number>>({})
  const [collapsed, setCollapsed] = useState(defaultCollapsed)

  useEffect(() => {
    setCollapsed(defaultCollapsed)
  }, [defaultCollapsed])

  const post = useCallback(
    async (path: string, body?: unknown) => {
      setBusy(true)
      setError('')
      try {
        const res = await api(path, {
          method: 'POST',
          body: body === undefined ? undefined : JSON.stringify(body),
        })
        if (!res.ok) {
          const detail = await res.json().catch(() => null)
          throw new Error(detail?.detail || 'Something went wrong')
        }
        onSession(await res.json())
        return true
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Something went wrong')
        return false
      } finally {
        setBusy(false)
      }
    },
    [onSession],
  )

  if (session === null) return null

  const threshold = session.pass_threshold
  const total = session.questions_per_quiz
  const submitted = session.state === 'submitted'

  const header = (
    <div className="flex items-baseline justify-between gap-3">
      <div>
        <span className="kite-page-kicker">Daily quiz</span>
        <p className="text-sm font-semibold" style={{ color: 'var(--kite-text)' }}>
          {submitted
            ? session.passed
              ? `Passed — ${session.correct_count} of ${total} correct`
              : `${session.correct_count} of ${total} correct — need ${threshold} to score`
            : session.niche || session.topic || 'Test yourself while your feed builds'}
        </p>
      </div>
      <button
        type="button"
        onClick={() => setCollapsed((c) => !c)}
        className="kite-btn-secondary text-xs"
        aria-expanded={!collapsed}
      >
        {collapsed ? 'Open' : 'Hide'}
      </button>
    </div>
  )

  if (collapsed) {
    return <div className="kite-panel">{header}</div>
  }

  return (
    <div className="kite-panel">
      {header}

      {error && <p className="mt-3 text-sm kite-text-danger">{error}</p>}

      {session.state === 'not_started' && (
        <>
          <p className="mt-2 text-sm kite-text-muted">
            Answer {threshold} of {total} correctly to earn today’s streak point. One attempt per
            day.
          </p>
          <button
            type="button"
            onClick={() => void post('/quiz/start')}
            disabled={busy}
            className="kite-btn-primary mt-4"
          >
            {busy ? 'Preparing…' : 'Start today’s quiz'}
          </button>
        </>
      )}

      {session.state === 'niche_pending' && (
        <>
          <p className="mt-2 text-sm kite-text-muted">
            Pick a topic from {session.topic}. Your choice is locked in for today.
          </p>
          <div className="mt-4 grid gap-2">
            {(session.niche_options || []).map((niche) => (
              <button
                key={niche}
                type="button"
                onClick={() => void post('/quiz/niche', { niche })}
                disabled={busy}
                className="kite-chip text-left"
              >
                {niche}
              </button>
            ))}
          </div>
        </>
      )}

      {(session.state === 'questions_ready' || submitted) && (
        <>
          <ol className="mt-4 space-y-5">
            {(session.questions || []).map((q) => {
              const chosen = submitted ? q.chosen_index : answers[q.position]
              return (
                <li key={q.position}>
                  <p className="text-sm font-medium" style={{ color: 'var(--kite-text)' }}>
                    {q.position}. {q.question}
                  </p>
                  <div className="mt-2 grid gap-2">
                    {q.options.map((option, i) => {
                      const isChosen = chosen === i
                      const isAnswer = submitted && q.correct_index === i
                      const isWrongChoice = submitted && isChosen && !isAnswer
                      return (
                        <label
                          key={option}
                          className={[
                            'kite-quiz-option',
                            isChosen ? 'kite-quiz-option-chosen' : '',
                            isAnswer ? 'kite-quiz-option-correct' : '',
                            isWrongChoice ? 'kite-quiz-option-wrong' : '',
                          ]
                            .filter(Boolean)
                            .join(' ')}
                        >
                          <input
                            type="radio"
                            name={`q${q.position}`}
                            checked={isChosen}
                            disabled={submitted || busy}
                            onChange={() =>
                              setAnswers((prev) => ({ ...prev, [q.position]: i }))
                            }
                            className="h-4 w-4 accent-[var(--kite-primary)]"
                          />
                          <span>{option}</span>
                          {isAnswer && <span className="kite-label-pill ml-auto">Correct</span>}
                        </label>
                      )
                    })}
                  </div>
                </li>
              )
            })}
          </ol>

          {!submitted && (
            <button
              type="button"
              onClick={() => {
                const ordered = (session.questions || []).map((q) => answers[q.position])
                void post('/quiz/submit', { answers: ordered })
              }}
              disabled={busy || Object.keys(answers).length < total}
              className="kite-btn-primary mt-5"
            >
              {busy
                ? 'Checking…'
                : Object.keys(answers).length < total
                  ? `Answer all ${total} to submit`
                  : 'Submit answers'}
            </button>
          )}

          {submitted && (
            <p className="mt-4 text-sm kite-text-muted">
              {session.passed
                ? 'Streak point earned. A new quiz unlocks tomorrow.'
                : 'No point today — a new quiz unlocks tomorrow.'}
            </p>
          )}
        </>
      )}
    </div>
  )
}
