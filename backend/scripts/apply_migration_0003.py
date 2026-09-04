"""Apply migration 0003 via psycopg2 when psql is unavailable."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

import psycopg2

sql = Path(__file__).resolve().parent.parent / "migrations" / "0003_feed_restructure.sql"
conn = psycopg2.connect(os.environ["SUPABASE_DB_URL"])
conn.autocommit = True
cur = conn.cursor()
cur.execute(sql.read_text())
cur.execute(
    """
    SELECT column_name FROM information_schema.columns
    WHERE table_name = 'articles'
      AND column_name IN ('user_id','one_liner','source_type','source','topic','fetched_at')
    ORDER BY column_name
    """
)
print("Columns:", [r[0] for r in cur.fetchall()])
cur.execute(
    "SELECT indexname FROM pg_indexes WHERE tablename='articles' AND indexname='idx_articles_user_fetched'"
)
print("Index:", cur.fetchone())
conn.close()
