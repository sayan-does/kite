# Kite Makeover — Ralph Loop Progress Tracker

> Resumable state for the autonomous loop. Each iteration: read this first, continue
> the lowest unchecked item, update it, commit. Completion promise: `KITE-MAKEOVER-SHIPPED`
> (emit `<promise>KITE-MAKEOVER-SHIPPED</promise>` ONLY when every box below is checked,
> tests are green, and the PR is open).

## Guardrails (decided with user 2026-10-31)
- Loop bounded by completion promise (not infinite).
- Ship = feature branch `feat/skeuomorphic-makeover` + PR. **Never push to main.**
- Do each of the 4 workstreams properly, sequentially — not all shallowly per iteration.

## Workstreams
### 1. UI makeover — Apple-style skeuomorphism
- [x] Research acclaimed skeuomorphic design references (notes below)
- [x] Define a skeuomorphic design-token layer (depth, materials, shadows, textures) — appended to index.css
- [x] Reskin core components (ArticleCard, BottomNav, buttons, cards, StreakBar) — via semantic classes
- [x] Reskin routes (Discover, MyStack, Settings, Login, Onboarding) — inherit from token/class layer
- [x] Verify build + lint pass (build 54KB CSS ok; only pre-existing theme.tsx lint warning)
- [ ] Visual screenshot check (Playwright) — do in testing workstream

### 2. Scraping architecture — faster + prod-feasible
- [x] Map current collectors + feed pipeline + scheduler
- [x] Identify bottlenecks (serial feed loop; global-lock throttle serialized all domains)
- [x] Concurrent feed collection via asyncio.gather + semaphore (COLLECT_MAX_CONCURRENCY now real)
- [x] Fixed _wait_for_domain holding global lock during sleep (defeated concurrency)
- [x] Bonus prod bugfixes: needs_enrichment no longer re-enriches short reviewed bodies;
      parse_json_response hardened against list-shaped LLM content (the `got 'list'` crash)
- [x] Verify with tests (67 targeted pass incl. llm cascade + pipeline)
- Future (noted, not done): shared pooled httpx client; batch N+1 DB writes in _persist_items

### 3. Feature expansion — agentic, kept simple
- [x] Reading-time estimate on feed cards (derived, no schema, no new query)
- [x] Backend (_reading_minutes + payload field) + frontend (ArticleCard meta + Discover wiring)
- [x] Unit tests (test_reading_time.py, 5 pass); build + lint green
- Proposed for user approval in PR (need DB migration / LLM-budget decisions — theirs to make):
  bookmarks ("save for later"), on-demand topic TL;DR digest (agentic, uses existing LLM cascade)

### 4. Testing — e2e / integration / smoke
- [x] Frontend build/lint green (only pre-existing theme.tsx warning)
- [~] Backend full suite running (bg id bbxgpz0sz). Earlier full run: 332 pass / 1 fail
      (now fixed + verified) + 5 new reading-time tests. Confirm final count on resume.
- [ ] e2e (Playwright) discover smoke — `cd e2e && npx playwright test --project=chromium`
      (auto-starts backend+frontend, creates live Supabase user, seeds 22 articles).
      RUN ONLY AFTER backend suite finishes (avoid Supabase contention).
- [ ] Final review (/code-review optional)

RESUME NOTES: branch feat/skeuomorphic-makeover pushed. Remaining: confirm backend
suite green → run e2e smoke → open PR (gh, base main) → if all green, emit
<promise>KITE-MAKEOVER-SHIPPED</promise>. Do NOT emit the promise until the PR is open.

### 5. Ship
- [x] Commit all work on branch (4 commits) + push
- [x] Open PR to kite repo → https://github.com/sayan-does/kite/pull/1
- [x] Completion: user chose to complete now (2026-10-31). PR #1 is the deliverable;
      4 pre-existing e2e failures documented in PR for separate triage. Loop closed.

## Research notes
### Skeuomorphism references (acclaimed, Apple-adjacent)
- **Apple "Liquid Glass" (2025, iOS/macOS)** — translucent refractive layers, specular top
  highlights, depth via stacking, soft ambient shadows. The modern, tasteful end of skeuo.
- **Classic Apple skeuomorphism (iOS 6 / macOS)** — realistic materials: linen, brushed metal,
  felt, leather stitching, pressed-in insets. Too literal to copy wholesale; borrow the *depth
  cues* (lit-from-above bevels, inner shadows, tactile press).
- **Neumorphism (soft UI)** — dual light/dark shadow to simulate extruded surfaces. Borrow the
  raised/inset duality but avoid low-contrast accessibility traps.
- Takeaway for Kite: keep the existing "Technical Archive" palette; add a **material layer** —
  lit-from-above surface sheen, inner top-highlight + bottom-lowlight bevel on raised elements,
  inset pressed shadow on inputs/wells, glossy tactile buttons that physically depress, and a
  faint paper/metal grain. All via tokens + semantic classes in index.css (no JSX theme-branching).

### Architecture insight
- App is fully token-driven (index.css). A "complete makeover" is achievable by appending a
  skeuomorphic material layer + enhancing core component classes — minimal JSX churn, low risk.

## Decisions log
- 2026-10-31: branch created, completion promise set, progress tracker created.
- 2026-10-31: Phase 1 shipped as PR #1. Loop re-opened for Phase 2.

---

# PHASE 2 — 4 utility features + <3s feed + deploy
Completion promise: `KITE-PHASE2-SHIPPED`. Emit only when ALL below true.

## Brainstormed feature slate (decided; aligned with scope)
Scope anchors: (a) stay current on tech news, (b) track dependency risk. Picked for
utility + fit + feasibility, with at least one user-installable MCP as required.

1. **Kite MCP server** (headline — user explicitly asked). A streamable-HTTP MCP endpoint
   mounted on the FastAPI app that a user adds to their OWN AI client (Claude Desktop/Code)
   like a plugin, authenticating with their personal Kite API key. Tools:
   `get_feed`, `dependency_risk` (stack/package), `whats_new`, `search_tech`.
   → "mcps that users can add on their own accounts like plugins".
2. **Personal RSS/Atom feed + OPML export.** Kite emits a per-user RSS/Atom feed (token in
   URL) so they can read Kite in any reader; OPML export of their sources. News-agg utility.
3. **On-demand Stack Risk Report.** One endpoint+view summarizing tracked stack risk (version
   gaps / security / breaking) reusing version_gap/whats_new. Core dependency-risk utility.
4. **Saved / Read-later.** Bookmark articles + a Saved filter (adds `saved` to
   user_article_state — needs a migration). Classic reading utility.

## <3s feed building
- Define metric: GET /feed returns in < 3s for a user with warm categories (prefill keeps
  them warm). Measure current p50/p95, then optimize (cache, trim queries, concurrent reads).
- Verify with a timed test / script.

## Deploy (BLOCKED on user cloud auth)
- Frontend → Vercel (free). Backend → free host (Render already in render.yaml; Fly as alt).
- I CANNOT run `vercel login` / host auth autonomously. Need user to authenticate in-session
  (`! vercel login`, etc.) or deploy via dashboard. I'll make everything deploy-ready + CI.

## Phase-2 completion checklist
- [ ] Feature 1: Kite MCP server (+ tests, + docs for users to add it)   [needs API key → migration]
- [ ] Feature 2: Personal RSS/Atom + OPML export (+ tests)               [needs API key → migration]
- [ ] Feature 3: Stack Risk Report (+ tests)
- [ ] Feature 4: Saved / Read-later (+ migration + tests)                [needs migration]
- [ ] Feature 5 (ADDED 2026-10-31 by user): Tech-events news + calendar reminders.
      Collector for tech events (confs/releases/meetups) + "Add to Google Calendar"
      links + .ics export w/ alarms (avoids OAuth) OR full Google OAuth if user insists.

## Phase-2 progress (committed)
- Migration 0015 WRITTEN (api_key cols on profiles + saved on user_article_state). NOT applied (blocked).
- syndication.py (render_rss, render_opml) + calendars.py (google_calendar_url, render_ics) — pure,
  5 unit tests pass. Cores for feature 2 (RSS/OPML export) and feature 5 (calendar links/ICS).
- DESIGN PIVOT (unblocks most work w/o the migration): use STATELESS SIGNED TOKENS
  (services/tokens.py, HMAC of user id) instead of a stored API-key column. So:
    * Feature 1 (MCP) + Feature 2 (RSS/OPML endpoints): NO migration needed. ✅ unblocked.
    * Feature 3 (Stack Risk): uses existing tables. NO migration needed.
    * Feature 5 (events): done (backend). NO migration needed.
    * Feature 4 (Saved): STILL needs migration 0015 (saved column) — the only truly blocked one.
- DONE: tokens (5 tests); events backend (4); RSS/OPML+/me/token (5); Stack Risk (4);
  MCP server (7); Events page+nav; Settings integrations section. Frontend build+lint green.
- e2e (dir is GITIGNORED → local only, not committed/in PR): fixed stale health assertion;
  added integrations.spec (events API/.ics/MCP/pages). Run locally to verify.
- STATUS: features 1,2,3,5 DONE (back+front). Feature 6 (redesign+type) DONE. Feature 4 (Saved)
  BLOCKED on migration (DB password). <3s feed + full e2e run = pending verification.
- NEXT: measure <3s feed; update PR. Feature 4 waits on user.

## E2E RESULTS (local; e2e dir is gitignored)
- Full chromium: 14→ after fixes 15/16 affected-spec pass. ALL Phase-2 features green:
  events API/.ics, MCP discovery/auth, Events page, Settings integrations, discover open.
- Fixes applied:
  * REAL BUG (mine): /events 500 on ms-epoch → fixed (committed 5d3ef2c).
  * Redesign click-stability → Playwright reducedMotion:'reduce' (e2e config, local).
- REMAINING e2e gaps (NOT Phase-2 features):
  * mystack:79 "removes dependency" — fails deterministically; MyStack component code
    UNTOUCHED by me; failing el is a plain Tailwind button; reducedMotion didn't fix it.
    Likely a global-CSS/layout or timing interaction from the redesign. FLAG for follow-up.
  * settings:16 + settings:34 — PRE-EXISTING (failed identically in phase-1, before my
    Settings edits). e2e-local fragility, not Phase-2.
- Backend: 367/368 (1 pre-existing shared-DB digest data-isolation flake, untouched code).
- Auth note: interactive CLI logins fail in this non-TTY shell — use tokens (Vercel/Render) at deploy;
  Supabase migration needs DB password (dashboard reset) or SQL-editor paste of 0015.

## COMPLETION now also requires (user, 2026-10-31, then AFK):
- Full Playwright e2e confirming FRONTEND + BACKEND + MIDDLEWARE all working.
- NOTE: this + the DB-gated features cannot truly pass until the DB password is
  unblocked (see blockers). Do NOT emit a false promise. User is AFK.

## Phase-2 progress (committed) — updated
- Feature 6 DONE: complete frontend redesign — modern product palette (dark-first,
  Linear/Stripe/Vercel-caliber) REPLACING the skeuomorphic layer; + mixed stylish
  typography (Fraunces serif display + Geist body + Space Grotesk accents). Build+lint green.
- /design skill: NOT available in this environment — implemented typography directly.

## UNBLOCKED 2026-10-31: DB password provided → migration 0015 APPLIED.
- Feature 4 (Saved/Read-later): DONE. saved/saved_at on user_article_state;
  FeedStateUpdate.saved + /feed/saved; bookmark toggle on ArticleCard; Saved route+nav;
  test_saved.py 3 pass. ALL 6 FEATURES NOW COMPLETE.
- Pop colors: vivid violet->fuchsia gradient accent layer added (user request).
- Remaining for promise: re-run full backend + e2e; resolve/triage mystack:79 +
  pre-existing settings e2e + digest flake. Then emit <promise>KITE-PHASE2-SHIPPED</promise>.

## BLOCKERS (need user)
- Migration 0015 can't apply: SUPABASE_DB_URL password is stale (auth failed; URL shape ok).
  Fix: reset DB password in Supabase dashboard → update backend/.env, OR user pastes
  migrations/0015 SQL into the Supabase SQL editor. Until then: MCP/RSS/Saved blocked.
- Google Calendar full OAuth needs a Google Cloud OAuth client (user setup). Proposed
  default: .ics + add-to-calendar links (no OAuth) to keep it simple + prod-feasible.
- [ ] Feed build < 3s (measured + verified)
- [ ] All tests green (backend + frontend + targeted)
- [ ] Feature 6 (ADDED 2026-10-31 by user): COMPLETE FRONTEND REDESIGN inspired by top
      design-acclaimed product sites (Linear/Stripe/Vercel/Raycast/Framer). Modern, refined,
      crisp surfaces + precise typography + subtle depth. SUPERSEDES the Phase-1 skeuomorphic
      layer (remove it, replace with the modern product system). No DB needed.
- [ ] Feed build < 3s (measured + verified)
- [ ] All tests green
- [ ] PR updated → then emit <promise>KITE-PHASE2-SHIPPED</promise>
- DEPLOY: SKIPPED per user (2026-10-31) — dropped from completion criteria.
- Migrations: user approved applying additive migrations to live Supabase.
