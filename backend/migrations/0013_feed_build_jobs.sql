-- Phase 11: real feed build progress.
--
-- The Discover screen used to show an indeterminate spinner for up to two
-- minutes with no indication of what was happening. This table is written by
-- the collect and review cycles so the client can report actual progress
-- instead of guessing from a timer.

create table if not exists feed_build_jobs (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references profiles(id) on delete cascade,

  status text not null default 'pending'
    check (status in ('pending', 'running', 'done', 'failed')),
  stage text not null default 'queued'
    check (stage in ('queued', 'collecting', 'ranking', 'reviewing', 'done')),

  topics text[] not null default '{}',

  feeds_total int not null default 0,
  feeds_done int not null default 0,
  topics_total int not null default 0,
  topics_ready int not null default 0,

  articles_collected int not null default 0,
  articles_inserted int not null default 0,
  articles_reviewed int not null default 0,

  -- Held monotonic by the writer: a later cycle stage must never make the bar
  -- appear to move backwards.
  percent int not null default 0 check (percent between 0 and 100),

  error text,

  started_at timestamptz default now(),
  updated_at timestamptz default now(),
  finished_at timestamptz
);

create index if not exists idx_feed_build_jobs_user_started
  on feed_build_jobs (user_id, started_at desc);

create index if not exists idx_feed_build_jobs_status
  on feed_build_jobs (status)
  where status in ('pending', 'running');
