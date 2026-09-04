-- Phase 11: reduce interest_tags to the seven supported categories.
--
-- Keeps: Frontend, Backend, AI/ML, DevOps, Security, Programming Languages.
-- Adds:  Automation.
-- Drops:  Databases, Mobile, Cloud Infra, Developer Tools.
--
-- This is destructive: articles collected for the dropped categories are
-- deleted, not archived. None of the foreign keys into interest_tags declare
-- on delete cascade, so every child row has to go first.
--
-- Tags are matched by name rather than id so the migration is safe to run
-- against a database whose serial sequence diverged from the 0002 seed.

insert into interest_tags (name, category) values
  ('Automation', 'Automation')
on conflict (name) do nothing;

-- ---------------------------------------------------------------------------
-- 11.1  Remove the dropped categories, children first
-- ---------------------------------------------------------------------------

create or replace function _dropped_tag_ids()
returns setof int
language sql
stable
as $fn$
  select id from interest_tags
   where name in ('Databases', 'Mobile', 'Cloud Infra', 'Developer Tools');
$fn$;

-- user_article_state cascades from kb_articles, so it needs no explicit delete.
delete from source_feeds     where tag_id in (select _dropped_tag_ids());
delete from kb_articles      where tag_id in (select _dropped_tag_ids());
delete from articles         where tag_id in (select _dropped_tag_ids());
delete from user_interests   where tag_id in (select _dropped_tag_ids());
delete from interest_tags    where id     in (select _dropped_tag_ids());

drop function _dropped_tag_ids();

-- ---------------------------------------------------------------------------
-- 11.2  Trim every user to at most three interests
-- ---------------------------------------------------------------------------
-- Ordering by tag_id keeps the outcome deterministic and reproducible; there
-- is no selection timestamp on user_interests to prefer instead.

with ranked as (
  select user_id,
         tag_id,
         row_number() over (partition by user_id order by tag_id) as rn
    from user_interests
)
delete from user_interests ui
 using ranked r
 where ui.user_id = r.user_id
   and ui.tag_id  = r.tag_id
   and r.rn > 3;
