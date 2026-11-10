import { Link } from 'react-router-dom'
import KiteBrand from '../components/KiteBrand'
import ThemeToggle from '../components/ThemeToggle'

export default function Landing() {
  return (
    <>
      <div className="kite-app-bg" aria-hidden="true">
        <div className="kite-app-bg-mid" />
      </div>
      
      {/* Header */}
      <header className="sticky top-0 z-40 flex items-center justify-between gap-3 border-b border-[var(--kite-border)] bg-[var(--kite-chrome-gradient)] px-4 py-3 backdrop-blur-md">
        <KiteBrand size="md" />
        <div className="flex items-center gap-2">
          <ThemeToggle />
        </div>
      </header>

      {/* Hero Section */}
      <main className="kite-page-wide">
        <section className="flex flex-col items-center text-center py-12 sm:py-16">
          <h1 className="kite-page-title max-w-2xl leading-tight">
            Never miss critical dependency updates
          </h1>
          <p className="mt-4 max-w-lg text-lg text-[var(--kite-text-secondary)]">
            Kite tracks your project's dependencies and alerts you to breaking changes, security vulnerabilities, and new versions—before they catch you off guard.
          </p>
          <Link
            to="/login"
            className="kite-btn-primary mt-8 px-8 py-4 text-base"
          >
            Get Started
          </Link>
        </section>

        {/* Feature Cards */}
        <section className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3 py-8">
          {/* Personalized Feed */}
          <div className="kite-card p-6">
            <div className="mb-4 inline-flex h-12 w-12 items-center justify-center rounded-xl bg-[var(--kite-primary-soft)]">
              <svg className="h-6 w-6 text-[var(--kite-primary)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 20H5a2 2 0 01-2-2V6a2 2 0 012-2h10a2 2 0 012 2v1m2 13a2 2 0 01-2-2V7m2 13a2 2 0 002-2V9a2 2 0 00-2-2h-2m-4-3H9M7 16h6M7 8h6v4H7V8z" />
              </svg>
            </div>
            <h3 className="text-lg font-semibold text-[var(--kite-text)]">Personalized Feed</h3>
            <p className="mt-2 text-sm text-[var(--kite-text-secondary)]">
              Curated articles on technologies you care about. Machine learning summaries help you stay informed without the noise.
            </p>
          </div>

          {/* Dependency Tracking */}
          <div className="kite-card p-6">
            <div className="mb-4 inline-flex h-12 w-12 items-center justify-center rounded-xl bg-[var(--kite-blue-soft)]">
              <svg className="h-6 w-6 text-[var(--kite-blue)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4" />
              </svg>
            </div>
            <div className="flex items-center gap-2">
              <h3 className="text-lg font-semibold text-[var(--kite-text)]">Dependency Tracking</h3>
              <span className="rounded-full bg-[var(--kite-primary)] px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-white">
                Beta
              </span>
            </div>
            <p className="mt-2 text-sm text-[var(--kite-text-secondary)]">
              Upload package.json, requirements.txt, Cargo.toml and more. Get instant alerts when your dependencies have breaking changes.
            </p>
          </div>

          {/* Daily Digests */}
          <div className="kite-card p-6 sm:col-span-2 lg:col-span-1">
            <div className="mb-4 inline-flex h-12 w-12 items-center justify-center rounded-xl bg-[var(--kite-accent-stack)]">
              <svg className="h-6 w-6 text-[var(--kite-secondary)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
              </svg>
            </div>
            <h3 className="text-lg font-semibold text-[var(--kite-text)]">Daily Digests</h3>
            <p className="mt-2 text-sm text-[var(--kite-text-secondary)]">
              Receive a morning email with everything that matters—articles, dependency updates, and security alerts.
            </p>
          </div>
        </section>

        {/* Screenshot Placeholder */}
        <section className="py-8">
          <div className="kite-card overflow-hidden">
            <div className="flex h-48 items-center justify-center bg-[var(--kite-surface-2)]">
              <div className="text-center">
                <p className="text-sm text-[var(--kite-text-muted)]">Screenshot placeholder</p>
                <p className="mt-1 text-xs text-[var(--kite-text-muted)]">My Stack dashboard preview</p>
              </div>
            </div>
          </div>
        </section>

        {/* CTA */}
        <section className="flex flex-col items-center py-12 text-center">
          <h2 className="text-2xl font-bold text-[var(--kite-text)]">
            Ready to stay ahead?
          </h2>
          <p className="mt-2 max-w-md text-[var(--kite-text-secondary)]">
            Join thousands of developers who trust Kite to keep their projects secure and up-to-date.
          </p>
          <Link
            to="/login"
            className="kite-btn-primary mt-6 px-8 py-4 text-base"
          >
            Get Started — It's Free
          </Link>
        </section>
      </main>

      {/* Footer */}
      <footer className="border-t border-[var(--kite-border)] py-8 text-center">
        <p className="text-sm text-[var(--kite-text-muted)]">
          Built for developers who value their time.
        </p>
      </footer>
    </>
  )
}