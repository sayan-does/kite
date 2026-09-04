-- Phase 7: per-user discovery feed restructure
alter table articles
  add column if not exists user_id uuid references profiles(id) on delete cascade,
  add column if not exists one_liner text,
  add column if not exists source_type text check (source_type in ('official_docs','github','blog','youtube')),
  add column if not exists source text check (source in ('interest','stack')),
  add column if not exists topic text,
  add column if not exists fetched_at timestamptz default now();

create index if not exists idx_articles_user_fetched
  on articles (user_id, fetched_at desc);
