-- Phase 9: shared knowledgebase + per-user read state

create table if not exists kb_articles (
  id uuid primary key default gen_random_uuid(),
  topic text not null,
  topic_kind text not null check (topic_kind in ('interest', 'stack')),
  tag_id int references interest_tags(id),
  title text not null,
  one_liner text,
  summary text not null,
  body text,
  source_type text check (source_type in ('official_docs', 'github', 'blog', 'youtube')),
  citations jsonb not null default '[]',
  youtube_url text,
  url text,
  published_at timestamptz,
  fetched_at timestamptz default now()
);

create table if not exists user_article_state (
  user_id uuid references profiles(id) on delete cascade,
  kb_article_id uuid references kb_articles(id) on delete cascade,
  seen boolean default false,
  read boolean default false,
  dismissed boolean default false,
  updated_at timestamptz default now(),
  primary key (user_id, kb_article_id)
);

alter table profiles add column if not exists last_digest_at timestamptz;

create unique index if not exists idx_kb_articles_topic_url
  on kb_articles (topic, url)
  where url is not null;

create index if not exists idx_kb_articles_tag_fetched
  on kb_articles (tag_id, fetched_at desc);

create index if not exists idx_kb_articles_topic_fetched
  on kb_articles (topic, fetched_at desc);

create index if not exists idx_kb_articles_fetched
  on kb_articles (fetched_at);

create or replace function get_user_feed(uid uuid, lim int, off int)
returns setof kb_articles
language sql
stable
as $$
  select ka.*
  from kb_articles ka
  where (
    ka.tag_id in (select tag_id from user_interests where user_id = uid)
    or (
      ka.topic_kind = 'stack'
      and ka.topic in (select package_name from tracked_dependencies where user_id = uid)
    )
  )
  and not exists (
    select 1
    from user_article_state uas
    where uas.user_id = uid
      and uas.kb_article_id = ka.id
      and uas.dismissed = true
  )
  order by ka.fetched_at desc
  limit lim
  offset off;
$$;
