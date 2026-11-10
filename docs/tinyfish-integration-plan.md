# Implementation Plan - TinyFish Integration for Faster Scraping and Feed Building

## Problem Statement

The Kite feed pipeline has two critical quality issues:
1. **Article enrichment failures**: `fetch_article_text()` fails on JS-rendered pages, gets blocked by anti-bot systems, and produces mangled text via `readability-lxml`, leaving articles stuck as `tier="raw"` without LLM summaries or with garbage summaries
2. **Search backfill unreliability**: SearXNG requires self-hosting and is often down; DuckDuckGo fallback has rate limits

**Scope:** Integrate TinyFish Search and Fetch APIs to improve scraping quality and search reliability while respecting free-tier limits (1,000 fetches/day, 30 searches/min).

---

## Requirements

1. **Article enrichment (primary focus)**:
   - Replace `fetch_article_text()` in slow cycle with TinyFish Fetch API
   - Use batch requests (10 URLs per request) for efficiency
   - Request `format="markdown"` for LLM-friendly content
   - LLM output includes `key_links` array: `[{"title": "...", "url": "..."}]`
   - Prioritize batching over conditional GET

2. **Search backfill (secondary)**:
   - TinyFish Search as primary, SearXNG/DDG as fallback
   - Use `domain_type="news"` mode for better structured results
   - Keep existing 12-result cap

3. **Budget management**:
   - Hard budget tracking with daily/hourly counters
   - Fall back to old paths when limits hit
   - New config: `TINYFISH_BATCH_CONCURRENCY` for slow-cycle batching

4. **Backward compatibility**:
   - Preserve existing fallback behavior (articles appear even if TinyFish fails)
   - Keep old `fetch_article_text()` / SearXNG paths as fallback
   - Feature flag: `TINYFISH_ENABLED` (opt-in)

---

## Tasks

### Task 1: Add TinyFish SDK and Configuration ✅
- Add `tinyfish>=0.1.0` to `requirements.txt`
- Add to `config.py`:
  - `TINYFISH_API_KEY`
  - `TINYFISH_ENABLED`
  - `TINYFISH_BATCH_CONCURRENCY`
- Update `.env.example`

### Task 2: Implement TinyFish Budget Tracker ✅
- Create `services/tinyfish_budget.py`
- Track 1,000 fetches/day, 30 searches/min
- Daily reset at midnight UTC

### Task 3: Create TinyFish Fetch Batch Helper ✅
- Create `services/tinyfish_fetch.py`
- Batch 10 URLs per request with concurrency control
- Automatic fallback to `fetch_article_text()`

### Task 4: Update LLM Prompt to Extract key_links ✅
- Update `article_enrich.py` prompt
- Extract 2-3 relevant links from markdown content

### Task 5: Integrate TinyFish Fetch into Slow Cycle ✅
- Update `review_graph.py` for batch fetching
- Pass prefetched content to `summarize_article()`

### Task 6: Implement TinyFish Search Integration ✅
- Update `collectors/search.py`
- TinyFish Search as primary, SearXNG/DDG fallback

### Task 7: Add Database Migration for key_links Field ✅
- Create `XXXX_add_key_links.sql`

### Task 8: Update API Response to Include key_links ✅
- Update `routers/feed.py` `_article_payload()`

### Task 9: Add Unit Tests ✅
- `test_tinyfish_budget.py`
- `test_tinyfish_search.py`

### Task 10: Add Monitoring and Logging ✅
- Log budget events and usage

### Task 11: Update Documentation ✅
- Update README.md and .env.example

### Task 12: Verification - End-to-End Testing ✅
- Run full pipeline with TinyFish enabled

---

## Done When

- [x] TinyFish SDK installed and configured
- [x] Budget tracker enforces limits
- [x] Slow cycle uses batched TinyFish Fetch
- [x] LLM prompt extracts `key_links`
- [x] Search backfill uses TinyFish Search
- [x] `key_links` column in DB and API
- [x] Unit tests created
- [x] End-to-end tests pass

---

## Notes

- Free tier: 1,000 fetches/day, 30 searches/min
- All failures fall back gracefully to existing paths
- LLM may hallucinate URLs in key_links - consider post-processing validation