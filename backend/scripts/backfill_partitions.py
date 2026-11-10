#!/usr/bin/env python3
"""Backfill existing kb_articles to partitioned table."""

import asyncio
import sys
from app.db import supabase


async def backfill_partitions(batch_size: int = 1000):
    """Copy existing kb_articles to kb_articles_partitioned."""
    print("Starting backfill...")
    
    offset = 0
    total = 0
    errors = 0
    
    while True:
        rows = (
            supabase.table("kb_articles")
            .select("*")
            .order("fetched_at")
            .range(offset, offset + batch_size - 1)
            .execute()
            .data
        )
        
        if not rows:
            break
        
        for row in rows:
            try:
                # Set validation_status based on tag_id
                if row.get("tag_id") is None and row.get("topic_kind") == "interest":
                    row["validation_status"] = "pending_validation"
                else:
                    row["validation_status"] = "validated"
                
                row["validation_attempts"] = 0
                row["key_links"] = row.get("key_links", [])
                
                supabase.table("kb_articles_partitioned").insert(row).execute()
                total += 1
            except Exception as exc:
                errors += 1
                print(f"Error inserting {row.get('id')}: {exc}")
        
        offset += batch_size
        print(f"Backfilled {total} articles (errors: {errors})...")
    
    print(f"Backfill complete: {total} articles copied, {errors} errors")
    return {"total": total, "errors": errors}


if __name__ == "__main__":
    asyncio.run(backfill_partitions())