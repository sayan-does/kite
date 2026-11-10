-- Atomic swap to partitioned table
-- Run this after backfill is complete

BEGIN;

-- Step 1: Ensure data integrity
-- (Assumes backfill was run and verified)

-- Step 2: Rename old table to backup
ALTER TABLE IF EXISTS kb_articles RENAME TO kb_articles_old;

-- Step 3: Rename partitioned table to main
ALTER TABLE IF EXISTS kb_articles_partitioned RENAME TO kb_articles;

-- Step 4: Update any references if needed
-- (The get_user_feed function already queries kb_articles)

COMMIT;

-- Verification queries (run separately):
-- SELECT COUNT(*) FROM kb_articles;  -- Should match old count
-- SELECT COUNT(*) FROM kb_articles_old;  -- Backup
-- SELECT COUNT(*) FROM kb_articles_p1;  -- Should have Frontend articles

-- Rollback (if needed):
-- BEGIN;
-- ALTER TABLE kb_articles RENAME TO kb_articles_partitioned;
-- ALTER TABLE kb_articles_old RENAME TO kb_articles;
-- COMMIT;