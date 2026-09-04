"""Apply migration 0005 via psycopg2 when psql is unavailable."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

import psycopg2

sql = Path(__file__).resolve().parent.parent / "migrations" / "0005_package_version_timeline.sql"
conn = psycopg2.connect(os.environ["SUPABASE_DB_URL"])
conn.autocommit = True
cur = conn.cursor()
cur.execute(sql.read_text())

cur.execute(
    """
    SELECT column_name FROM information_schema.columns
    WHERE table_name = 'package_version_timeline'
    ORDER BY ordinal_position
    """
)
print("package_version_timeline columns:", [r[0] for r in cur.fetchall()])

cur.execute(
    """
    SELECT indexname FROM pg_indexes
    WHERE tablename = 'package_version_timeline'
    ORDER BY indexname
    """
)
print("indexes:", [r[0] for r in cur.fetchall()])
conn.close()
