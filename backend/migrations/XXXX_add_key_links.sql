-- Add key_links JSONB column to kb_articles for extracted relevant links

ALTER TABLE kb_articles 
    ADD COLUMN IF NOT EXISTS key_links JSONB DEFAULT '[]'::jsonb;

COMMENT ON COLUMN kb_articles.key_links IS 'Extracted relevant links: [{"title":"...","url":"..."}]';

-- Also add to partitioned table if it exists
ALTER TABLE kb_articles_partitioned 
    ADD COLUMN IF NOT EXISTS key_links JSONB DEFAULT '[]'::jsonb;

COMMENT ON COLUMN kb_articles_partitioned.key_links IS 'Extracted relevant links: [{"title":"...","url":"..."}]';

-- Create index on key_links for potential future queries
CREATE INDEX IF NOT EXISTS idx_kb_articles_key_links ON kb_articles (key_links) 
    WHERE key_links IS NOT NULL AND jsonb_array_length(key_links) > 0;