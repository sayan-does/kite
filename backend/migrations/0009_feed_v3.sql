-- Phase 10: dynamic feed pipeline
-- Additive and safe to apply while FEED_V3 is off. The new columns carry
-- defaults that reproduce today's behaviour: everything is tier='raw',
-- status='active', and score 0, so the feed keeps working unchanged until the
-- collectors start writing real values.

-- ---------------------------------------------------------------------------
-- 10.4  kb_articles: collection provenance, review tier, clustering, ranking
-- ---------------------------------------------------------------------------

alter table kb_articles add column if not exists url_canonical text;
alter table kb_articles add column if not exists collected_at timestamptz default now();
alter table kb_articles add column if not exists tier text default 'raw';
alter table kb_articles add column if not exists status text default 'active';
alter table kb_articles add column if not exists cluster_id uuid;
alter table kb_articles add column if not exists score numeric default 0;
alter table kb_articles add column if not exists source_adapter text;
alter table kb_articles add column if not exists signals jsonb default '{}'::jsonb;

do $$
begin
  if not exists (select 1 from pg_constraint where conname = 'kb_articles_tier_check') then
    alter table kb_articles add constraint kb_articles_tier_check
      check (tier in ('raw', 'reviewed'));
  end if;
  if not exists (select 1 from pg_constraint where conname = 'kb_articles_status_check') then
    alter table kb_articles add constraint kb_articles_status_check
      check (status in ('active', 'rejected'));
  end if;
end $$;

-- ---------------------------------------------------------------------------
-- URL canonicalization, in SQL, for backfilling existing rows only.
-- New writes are canonicalized in Python (app/collectors/base.py); this must
-- stay behaviourally aligned with that function.
-- ---------------------------------------------------------------------------

create or replace function canonicalize_url_sql(raw text)
returns text
language plpgsql
immutable
as $fn$
declare
  work text;
  base text;
  query text;
  kept text;
begin
  if raw is null or btrim(raw) = '' then
    return null;
  end if;

  work := btrim(raw);
  work := split_part(work, '#', 1);              -- drop fragment
  work := regexp_replace(work, '^https?://', '', 'i');
  work := regexp_replace(work, '^www\.', '', 'i');

  base  := split_part(work, '?', 1);
  query := substring(work from position('?' in work) + 1);
  if position('?' in work) = 0 then
    query := '';
  end if;

  -- Drop tracking parameters, preserve everything else in original order.
  if query <> '' then
    select string_agg(param, '&' order by ord)
      into kept
      from (
        select param, ord
        from unnest(string_to_array(query, '&')) with ordinality as t(param, ord)
        where param <> ''
          and lower(split_part(param, '=', 1)) not in (
            'utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content',
            'utm_id', 'utm_name', 'fbclid', 'gclid', 'msclkid', 'mc_cid', 'mc_eid',
            'igshid', 'ref', 'ref_src', 'source', 'amp', 'spm', 'yclid', '_hsenc',
            '_hsmi', 'vero_id', 'wt_mc', 'at_medium', 'at_campaign'
          )
      ) filtered;
  end if;

  -- Strip AMP suffixes, then a single trailing slash.
  base := regexp_replace(base, '/amp/?$', '', 'i');
  base := regexp_replace(base, '\.amp$', '', 'i');
  base := regexp_replace(base, '/+$', '');

  -- Host lowercased; path case preserved because many paths are case sensitive.
  base := lower(split_part(base, '/', 1))
          || case when position('/' in base) > 0
                  then substring(base from position('/' in base))
                  else '' end;

  if kept is not null and kept <> '' then
    return base || '?' || kept;
  end if;
  return base;
end $$;

update kb_articles
   set url_canonical = canonicalize_url_sql(url)
 where url_canonical is null
   and url is not null;

-- Canonicalization can collapse rows that were distinct under (topic, url),
-- so collapse duplicates before the unique index is created. Oldest row wins
-- to preserve the original fetched_at ordering.
with ranked as (
  select id,
         row_number() over (
           partition by topic, url_canonical
           order by fetched_at asc, id asc
         ) as rn
    from kb_articles
   where url_canonical is not null
)
delete from kb_articles
 where id in (select id from ranked where rn > 1);

drop index if exists idx_kb_articles_topic_url;

create unique index if not exists idx_kb_articles_topic_url_canonical
  on kb_articles (topic, url_canonical)
  where url_canonical is not null;

create index if not exists idx_kb_articles_cluster
  on kb_articles (cluster_id)
  where cluster_id is not null;

create index if not exists idx_kb_articles_score
  on kb_articles (score desc, fetched_at desc);

create index if not exists idx_kb_articles_tier_status
  on kb_articles (tier, status);

create index if not exists idx_kb_articles_collected
  on kb_articles (collected_at desc);

-- ---------------------------------------------------------------------------
-- 10.5  source_feeds: curated allowlist plus conditional-GET bookkeeping
-- ---------------------------------------------------------------------------

create table if not exists source_feeds (
  id uuid primary key default gen_random_uuid(),
  kind text not null check (kind in ('rss', 'hn', 'github', 'papers', 'search')),
  url text not null,
  title text,
  topic text,
  tag_id int references interest_tags(id),
  weight numeric not null default 1.0,
  enabled boolean not null default true,

  -- Conditional GET state. A feed that keeps answering 304 costs almost
  -- nothing, which is what makes hourly polling affordable.
  etag text,
  last_modified text,
  last_polled_at timestamptz,
  last_success_at timestamptz,
  last_status int,

  -- Adaptive polling: widened when a feed is quiet, tightened when productive.
  poll_interval_minutes int not null default 60,
  consecutive_failures int not null default 0,
  consecutive_not_modified int not null default 0,

  created_at timestamptz default now(),
  unique (kind, url)
);

create index if not exists idx_source_feeds_due
  on source_feeds (enabled, last_polled_at);

create index if not exists idx_source_feeds_tag
  on source_feeds (tag_id);

-- Seed: curated research outlets carried over from RESEARCH_OUTLET_DOMAINS in
-- app/agents/discovery/research.py, plus a starter feed per interest tag.
insert into source_feeds (kind, url, title, topic, tag_id, weight) values
  ('rss', 'https://huggingface.co/blog/feed.xml',              'Hugging Face Blog',   'AI/ML', 3, 1.4),
  ('rss', 'https://blog.google/technology/ai/rss/',            'Google AI Blog',      'AI/ML', 3, 1.3),
  ('rss', 'https://deepmind.google/blog/rss.xml',              'Google DeepMind',     'AI/ML', 3, 1.4),
  ('rss', 'https://www.deeplearning.ai/the-batch/feed/',       'The Batch',           'AI/ML', 3, 1.2),
  ('papers', 'https://huggingface.co/api/daily_papers',        'HF Daily Papers',     'AI/ML', 3, 1.3),
  ('papers', 'http://export.arxiv.org/api/query?search_query=cat:cs.LG&sortBy=submittedDate&sortOrder=descending&max_results=40',
                                                               'arXiv cs.LG',         'AI/ML', 3, 1.1),
  ('rss', 'https://react.dev/rss.xml',                         'React Blog',          'Frontend', 1, 1.4),
  ('rss', 'https://nodejs.org/en/feed/blog.xml',               'Node.js Blog',        'Backend', 2, 1.4),
  ('rss', 'https://kubernetes.io/feed.xml',                    'Kubernetes Blog',     'DevOps', 4, 1.3),
  ('rss', 'https://www.postgresql.org/news.rss',               'PostgreSQL News',     'Databases', 5, 1.4),
  ('rss', 'https://developer.android.com/feeds/blog.xml',      'Android Developers',  'Mobile', 6, 1.2),
  ('rss', 'https://www.schneier.com/feed/atom/',               'Schneier on Security','Security', 7, 1.1),
  ('rss', 'https://aws.amazon.com/blogs/aws/feed/',            'AWS News Blog',       'Cloud Infra', 8, 1.1),
  ('rss', 'https://blog.rust-lang.org/feed.xml',               'Rust Blog',           'Programming Languages', 9, 1.3),
  ('rss', 'https://github.blog/feed/',                         'GitHub Blog',         'Developer Tools', 10, 1.1),
  ('hn',  'https://hn.algolia.com/api/v1/search',              'Hacker News',         null, null, 1.0)
on conflict (kind, url) do nothing;

-- ---------------------------------------------------------------------------
-- 10.6  get_user_feed v2 — one row per cluster, ranked by score
-- ---------------------------------------------------------------------------

-- Preserved verbatim for rollback: restore by renaming this back over
-- get_user_feed if FEED_V3 has to be reverted.
create or replace function get_user_feed_v1(uid uuid, lim int, off int)
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

create or replace function get_user_feed(uid uuid, lim int, off int)
returns setof kb_articles
language sql
stable
as $$
  -- Collapse each cluster to its best-scoring member, then rank. Articles with
  -- no cluster_id fall back to their own id so they always stand alone.
  with matched as (
    select ka.*
    from kb_articles ka
    where ka.status = 'active'
      and (
        ka.tag_id in (select tag_id from user_interests where user_id = uid)
        or (
          ka.topic_kind = 'stack'
          and ka.topic in (
            select package_name from tracked_dependencies where user_id = uid
          )
        )
      )
      and not exists (
        select 1
        from user_article_state uas
        where uas.user_id = uid
          and uas.kb_article_id = ka.id
          and uas.dismissed = true
      )
  ),
  deduped as (
    select distinct on (coalesce(cluster_id, id)) *
    from matched
    order by
      coalesce(cluster_id, id),
      -- Prefer the reviewed member of a cluster, then the best score.
      (tier = 'reviewed') desc,
      score desc,
      fetched_at desc
  )
  select *
  from deduped
  order by score desc, fetched_at desc
  limit lim
  offset off;
$$;
