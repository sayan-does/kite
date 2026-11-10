# Implementation Plan - Topic-Isolated Feeds with Partitioning

## Problem Statement

The Kite feed pipeline has topic filtering leaks:
1. **NULL tag_id articles** appear in user feeds despite not matching any interest
2. **HN mis-tagged articles** (e.g., "frontend" keyword match returns backend articles) pollute topic feeds
3. **Cross-topic contamination** due to global kb_articles table with SQL filtering

Users want strict per-topic feeds with zero cross-contamination. The "All" feed mixes topics in confusing ways.

**Scope:** Implement PostgreSQL table partitioning on `kb_articles` by `tag_id`, add per-collector MIN_RELEVANCE thresholds, build LLM-based background validation for NULL tag_id articles, and remove "All" feed (require explicit topic selection).

---

## Requirements

1. **Table partitioning architecture:**
   - Partition `kb_articles` by `tag_id` (int)
   - 7 partitions for interest-kind articles (Frontend=1, Backend=2, AI/ML=3, DevOps=4, Security=5, Automation=6, Programming Languages=7)
   - 1 NULL partition for unvalidated articles (tag_id IS NULL AND topic_kind='interest')
   - 1 stack partition for all tracked-dependency articles (topic_kind='stack')

2. **Per-collector relevance thresholds:**
   - HN articles: MIN_RELEVANCE = 0.6 (stricter)
   - Search backfill: MIN_RELEVANCE = 0.6
   - RSS feeds: MIN_RELEVANCE = 0.4
   - Papers (arXiv/HF): MIN_RELEVANCE = 0.3

3. **LLM validation for NULL tag_id:**
   - Background worker queries NULL partition
   - LLM assigns correct tag_id based on title/snippet/URL/source_type/full content
   - Move article to correct partition once validated
   - Retry up to 5 times over 24 hours if LLM fails

4. **API changes (breaking):**
   - Remove "All" feed default
   - `/feed` without `?tag=` returns 400
   - Support single topic: `/feed?tag=Frontend`
   - Support multiple topics: `/feed?tag=Frontend,AI/ML`
   - Multi-topic response: `{"feeds": [{"topic": "Frontend", "articles": [...]}, ...]}`

5. **Migration strategy:**
   - Create new partitioned table
   - Backfill existing articles
   - Atomic swap (rename tables)

---

## Tasks

### Task 1: Add Per-Collector MIN_RELEVANCE Configuration ✅
- Add to `config.py`: MIN_RELEVANCE_HN, MIN_RELEVANCE_SEARCH, MIN_RELEVANCE_RSS, MIN_RELEVANCE_PAPERS
- Add `get_min_relevance_for_adapter()` to `ranking.py`
- Update `feed_pipeline.py` to use collector-specific thresholds

### Task 2: Create Partitioned kb_articles Schema ✅
- Create `XXXX_partition_kb_articles.sql`
- 9 partitions: 7 interests + NULL + stack
- Add validation tracking columns

### Task 3: Add Validation Tracking Columns ✅
- `validation_status`: 'pending_validation', 'validated', 'rejected'
- `validation_attempts`: retry count
- `last_validation_attempt`: timestamp

### Task 4: Backfill Existing Articles ✅
- Create `scripts/backfill_partitions.py`
- Copy kb_articles to kb_articles_partitioned

### Task 5: Update get_user_feed RPC ✅
- Create `XXXX_update_get_user_feed.sql`
- Query partitioned table with partition pruning

### Task 6: Implement LLM Validation Worker ✅
- Create `services/tag_validator.py`
- Process NULL partition every 15 minutes
- 5 retries before rejection

### Task 7: Schedule Validation Worker ✅
- Add to `main.py` scheduler
- Run every 15 minutes

### Task 8: Update Feed API ✅
- Require topic selection
- Support multi-topic grouped response

### Task 9: Atomic Table Swap ✅
- Create `XXXX_swap_tables.sql`
- Rename tables

### Task 10: Update Documentation ✅
- Document partitioning, migration steps

### Task 11: End-to-End Verification ✅
- Test full pipeline

---

## Done When

- [x] Per-collector MIN_RELEVANCE implemented
- [x] Partitioned table with 9 partitions created
- [x] Validation tracking columns added
- [x] Existing articles backfilled
- [x] get_user_feed RPC updated
- [x] LLM validation worker implemented
- [x] Worker scheduled every 15 minutes
- [x] Feed API requires topic selection
- [x] Atomic table swap prepared
- [x] End-to-end tests pass

---

## Notes

- Migration timeline: ~1-2 days for backfill + swap
- Rollback plan: rename tables back
- Stack partition: all stack articles together (10% of volume)
- Frontend needs to handle 400 when no tag provided