"""Apply migration 0004 via psycopg2 when psql is unavailable."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

import psycopg2

sql = Path(__file__).resolve().parent.parent / "migrations" / "0004_shared_kb.sql"
conn = psycopg2.connect(os.environ["SUPABASE_DB_URL"])
conn.autocommit = True
cur = conn.cursor()
cur.execute(sql.read_text())

cur.execute(
    """
    SELECT column_name FROM information_schema.columns
    WHERE table_name = 'kb_articles'
    ORDER BY ordinal_position
    """
)
print("kb_articles columns:", [r[0] for r in cur.fetchall()])

cur.execute(
    """
    SELECT column_name FROM information_schema.columns
    WHERE table_name = 'user_article_state'
    ORDER BY ordinal_position
    """
)
print("user_article_state columns:", [r[0] for r in cur.fetchall()])

cur.execute(
    """
    SELECT column_name FROM information_schema.columns
    WHERE table_name = 'profiles' AND column_name = 'last_digest_at'
    """
)
print("profiles.last_digest_at:", cur.fetchone())

cur.execute(
    """
    SELECT indexname FROM pg_indexes
    WHERE tablename = 'kb_articles' AND indexname = 'idx_kb_articles_topic_url'
    """
)
print("unique (topic,url) index:", cur.fetchone())

cur.execute(
    """
    SELECT proname FROM pg_proc WHERE proname = 'get_user_feed'
    """
)
print("get_user_feed:", cur.fetchone())
conn.close()
