-- Update get_user_feed to query partitioned table with partition pruning
-- This RPC filters for validated articles only

CREATE OR REPLACE FUNCTION get_user_feed(
    uid uuid,
    lim int,
    off int,
    topic_filter text DEFAULT NULL
)
RETURNS SETOF kb_articles_partitioned
LANGUAGE sql
STABLE
AS $fn$
  WITH matched AS (
    SELECT ka.*
    FROM kb_articles_partitioned ka
    WHERE ka.status = 'active'
      AND ka.validation_status = 'validated'  -- Exclude pending/rejected
      AND (topic_filter IS NULL OR ka.topic = topic_filter)
      AND (
        ka.tag_id IN (SELECT tag_id FROM user_interests WHERE user_id = uid)
        OR (
          ka.topic_kind = 'stack'
          AND ka.topic IN (
            SELECT package_name FROM tracked_dependencies WHERE user_id = uid
          )
        )
      )
      AND NOT EXISTS (
        SELECT 1 FROM user_article_state uas
        WHERE uas.user_id = uid
          AND uas.kb_article_id = ka.id
          AND uas.dismissed = true
      )
  ),
  deduped AS (
    SELECT DISTINCT ON (COALESCE(cluster_id, id)) *
    FROM matched
    ORDER BY
      COALESCE(cluster_id, id),
      (tier = 'reviewed') DESC,
      score DESC,
      fetched_at DESC
  )
  SELECT *
  FROM deduped
  ORDER BY score DESC, fetched_at DESC
  LIMIT lim
  OFFSET off;
$fn$;

-- Grant execute permission
GRANT EXECUTE ON FUNCTION get_user_feed(uuid, int, int, text) TO postgres, anon, authenticated;