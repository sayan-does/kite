-- Partition kb_articles by tag_id for topic isolation
-- 7 interest partitions + NULL partition + stack partition

-- Step 1: Create partitioned parent table
CREATE TABLE IF NOT EXISTS kb_articles_partitioned (
    LIKE kb_articles INCLUDING ALL
) PARTITION BY LIST (
    CASE 
        WHEN topic_kind = 'stack' THEN -2
        WHEN tag_id IS NULL AND topic_kind = 'interest' THEN -1
        ELSE COALESCE(tag_id, 0)
    END
);

-- Step 2: Create partitions for interest tags (1-7)
CREATE TABLE IF NOT EXISTS kb_articles_p1 PARTITION OF kb_articles_partitioned 
    FOR VALUES IN (1);  -- Frontend

CREATE TABLE IF NOT EXISTS kb_articles_p2 PARTITION OF kb_articles_partitioned 
    FOR VALUES IN (2);  -- Backend

CREATE TABLE IF NOT EXISTS kb_articles_p3 PARTITION OF kb_articles_partitioned 
    FOR VALUES IN (3);  -- AI/ML

CREATE TABLE IF NOT EXISTS kb_articles_p4 PARTITION OF kb_articles_partitioned 
    FOR VALUES IN (4);  -- DevOps

CREATE TABLE IF NOT EXISTS kb_articles_p5 PARTITION OF kb_articles_partitioned 
    FOR VALUES IN (5);  -- Security

CREATE TABLE IF NOT EXISTS kb_articles_p6 PARTITION OF kb_articles_partitioned 
    FOR VALUES IN (6);  -- Automation

CREATE TABLE IF NOT EXISTS kb_articles_p7 PARTITION OF kb_articles_partitioned 
    FOR VALUES IN (7);  -- Programming Languages

-- Step 3: Create NULL partition for unvalidated interest articles
CREATE TABLE IF NOT EXISTS kb_articles_pnull PARTITION OF kb_articles_partitioned 
    FOR VALUES IN (-1);

-- Step 4: Create stack partition for all stack-kind articles
CREATE TABLE IF NOT EXISTS kb_articles_pstack PARTITION OF kb_articles_partitioned 
    FOR VALUES IN (-2);

-- Step 5: Add validation tracking columns
ALTER TABLE kb_articles_partitioned 
    ADD COLUMN IF NOT EXISTS validation_status text DEFAULT 'validated' 
        CHECK (validation_status IN ('pending_validation', 'validated', 'rejected')),
    ADD COLUMN IF NOT EXISTS validation_attempts int DEFAULT 0,
    ADD COLUMN IF NOT EXISTS last_validation_attempt timestamptz;

-- Step 6: Create indexes per partition for performance
-- p1 (Frontend)
CREATE INDEX IF NOT EXISTS idx_kb_articles_p1_score ON kb_articles_p1 (tag_id, score DESC, fetched_at DESC) 
    WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_kb_articles_p1_topic ON kb_articles_p1 (topic) WHERE status = 'active';

-- p2 (Backend)
CREATE INDEX IF NOT EXISTS idx_kb_articles_p2_score ON kb_articles_p2 (tag_id, score DESC, fetched_at DESC) 
    WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_kb_articles_p2_topic ON kb_articles_p2 (topic) WHERE status = 'active';

-- p3 (AI/ML)
CREATE INDEX IF NOT EXISTS idx_kb_articles_p3_score ON kb_articles_p3 (tag_id, score DESC, fetched_at DESC) 
    WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_kb_articles_p3_topic ON kb_articles_p3 (topic) WHERE status = 'active';

-- p4 (DevOps)
CREATE INDEX IF NOT EXISTS idx_kb_articles_p4_score ON kb_articles_p4 (tag_id, score DESC, fetched_at DESC) 
    WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_kb_articles_p4_topic ON kb_articles_p4 (topic) WHERE status = 'active';

-- p5 (Security)
CREATE INDEX IF NOT EXISTS idx_kb_articles_p5_score ON kb_articles_p5 (tag_id, score DESC, fetched_at DESC) 
    WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_kb_articles_p5_topic ON kb_articles_p5 (topic) WHERE status = 'active';

-- p6 (Automation)
CREATE INDEX IF NOT EXISTS idx_kb_articles_p6_score ON kb_articles_p6 (tag_id, score DESC, fetched_at DESC) 
    WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_kb_articles_p6_topic ON kb_articles_p6 (topic) WHERE status = 'active';

-- p7 (Programming Languages)
CREATE INDEX IF NOT EXISTS idx_kb_articles_p7_score ON kb_articles_p7 (tag_id, score DESC, fetched_at DESC) 
    WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_kb_articles_p7_topic ON kb_articles_p7 (topic) WHERE status = 'active';

-- pnull (unvalidated)
CREATE INDEX IF NOT EXISTS idx_kb_articles_pnull_pending ON kb_articles_pnull (validation_status, last_validation_attempt) 
    WHERE validation_status = 'pending_validation';
CREATE INDEX IF NOT EXISTS idx_kb_articles_pnull_score ON kb_articles_pnull (score DESC, fetched_at DESC) 
    WHERE status = 'active';

-- pstack (stack)
CREATE INDEX IF NOT EXISTS idx_kb_articles_pstack_score ON kb_articles_pstack (topic, score DESC, fetched_at DESC) 
    WHERE status = 'active';

-- Step 7: Create validation trigger
CREATE OR REPLACE FUNCTION validate_kb_article_partition() RETURNS TRIGGER AS $$
BEGIN
    IF NEW.topic_kind = 'interest' AND NEW.tag_id IS NULL THEN
        -- Allow, goes to NULL partition
        RETURN NEW;
    END IF;
    IF NEW.topic_kind = 'stack' THEN
        -- Force to stack partition
        RETURN NEW;
    END IF;
    IF NEW.tag_id IS NOT NULL AND (NEW.tag_id < 1 OR NEW.tag_id > 7) THEN
        RAISE EXCEPTION 'Invalid tag_id: %. Must be 1-7 for interest topics.', NEW.tag_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS kb_article_partition_check ON kb_articles_partitioned;
CREATE TRIGGER kb_article_partition_check
    BEFORE INSERT OR UPDATE ON kb_articles_partitioned
    FOR EACH ROW EXECUTE FUNCTION validate_kb_article_partition();

COMMENT ON TABLE kb_articles_partitioned IS 'Partitioned kb_articles table for topic isolation';
COMMENT ON TABLE kb_articles_p1 IS 'Frontend partition';
COMMENT ON TABLE kb_articles_p2 IS 'Backend partition';
COMMENT ON TABLE kb_articles_p3 IS 'AI/ML partition';
COMMENT ON TABLE kb_articles_p4 IS 'DevOps partition';
COMMENT ON TABLE kb_articles_p5 IS 'Security partition';
COMMENT ON TABLE kb_articles_p6 IS 'Automation partition';
COMMENT ON TABLE kb_articles_p7 IS 'Programming Languages partition';
COMMENT ON TABLE kb_articles_pnull IS 'NULL tag_id partition for unvalidated articles';
COMMENT ON TABLE kb_articles_pstack IS 'Stack (tracked dependencies) partition';