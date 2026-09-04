"""Apply one or more migration files by name, for when psql is unavailable.

    python scripts/apply_migration.py 0013_feed_build_jobs 0014_quiz_streak

Each file runs in its own transaction, so a failure leaves earlier files
applied and stops before the rest.
"""
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

import os

import psycopg2

MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations"


def main(names: list[str]) -> int:
    if not names:
        print("usage: apply_migration.py <name> [<name> ...]")
        return 2

    conn = psycopg2.connect(os.environ["SUPABASE_DB_URL"])
    try:
        for name in names:
            path = MIGRATIONS / (name if name.endswith(".sql") else f"{name}.sql")
            if not path.exists():
                print(f"missing migration: {path}")
                return 1
            with conn:
                with conn.cursor() as cur:
                    cur.execute(path.read_text())
            print(f"applied {path.name}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
