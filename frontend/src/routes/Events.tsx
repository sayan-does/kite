import { useEffect, useState } from 'react'

import { api } from '../api/client'

interface TechEvent {
  title: string
  url: string
  start: string
  end: string
  location: string
  online: boolean
  google_calendar_url: string
}

const API_BASE = import.meta.env.VITE_API_BASE_URL || ''

function formatRange(start: string, end: string): string {
  try {
    const s = new Date(start)
    const e = new Date(end)
    const opts: Intl.DateTimeFormatOptions = { day: 'numeric', month: 'short', year: 'numeric' }
    const sStr = s.toLocaleDateString(undefined, opts)
    const eStr = e.toLocaleDateString(undefined, opts)
    return sStr === eStr ? sStr : `${sStr} – ${eStr}`
  } catch {
    return start
  }
}

export default function Events() {
  const [events, setEvents] = useState<TechEvent[]>([])
  const [state, setState] = useState<'loading' | 'ready' | 'empty' | 'error'>('loading')

  useEffect(() => {
    let cancelled = false
    api('/events?limit=40')
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((data) => {
        if (cancelled) return
        const list: TechEvent[] = data.events || []
        setEvents(list)
        setState(list.length ? 'ready' : 'empty')
      })
      .catch(() => !cancelled && setState('error'))
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <div className="kite-page kite-page-enter">
      <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
        <div>
          <span className="kite-page-kicker">Stay in the loop</span>
          <h1 className="kite-page-title kite-page-title-accent">Tech Events</h1>
          <p className="kite-page-subtitle">Upcoming conferences and releases — add them to your calendar.</p>
        </div>
        <a href={`${API_BASE}/events.ics`} className="kite-btn-secondary text-xs" download>
          Download .ics
        </a>
      </div>

      {state === 'loading' && (
        <div className="flex justify-center py-16">
          <div className="kite-spinner kite-spinner-lg" />
        </div>
      )}

      {state === 'error' && (
        <div className="kite-empty">
          <div className="kite-empty-state">
            <p className="kite-empty-title">Couldn't load events</p>
            <p className="kite-empty-body">Please try again in a moment.</p>
          </div>
        </div>
      )}

      {state === 'empty' && (
        <div className="kite-empty">
          <div className="kite-empty-state">
            <p className="kite-empty-title">No upcoming events</p>
            <p className="kite-empty-body">Check back soon — the schedule refreshes regularly.</p>
          </div>
        </div>
      )}

      {state === 'ready' && (
        <ul className="kite-stagger flex flex-col gap-3" style={{ listStyle: 'none', margin: 0, padding: 0 }}>
          {events.map((ev, i) => (
            <li key={`${ev.url}-${i}`} className="kite-card kite-stagger-item" style={{ padding: '1rem 1.15rem' }}>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="kite-article-meta">
                    <span>{formatRange(ev.start, ev.end)}</span>
                    {ev.location && <span className="kite-article-meta-dot" />}
                    {ev.location && <span>{ev.location}</span>}
                    {ev.online && <span className="kite-badge-interest">Online</span>}
                  </div>
                  <h3 className="kite-article-title mt-1">
                    {ev.url ? (
                      <a href={ev.url} target="_blank" rel="noopener noreferrer" className="kite-article-title-link">
                        {ev.title}
                      </a>
                    ) : (
                      ev.title
                    )}
                  </h3>
                </div>
                <a
                  href={ev.google_calendar_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="kite-btn-primary text-xs px-3 py-2"
                >
                  Add to Calendar
                </a>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
