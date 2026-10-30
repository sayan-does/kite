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
