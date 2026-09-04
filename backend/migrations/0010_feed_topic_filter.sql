-- Phase 10 follow-up: server-side topic filter for get_user_feed pagination.
-- Drop the 3-arg overload so PostgREST resolves a single RPC signature.

drop function if exists get_user_feed(uuid, int, int);

create or replace function get_user_feed(
  uid uuid,
  lim int,
  off int,
  topic_filter text default null
)
returns setof kb_articles
language sql
stable
as $fn$
  with matched as (
    select ka.*
    from kb_articles ka
    where ka.status = 'active'
      and (topic_filter is null or ka.topic = topic_filter)
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
      (tier = 'reviewed') desc,
      score desc,
      fetched_at desc
  )
  select *
  from deduped
  order by score desc, fetched_at desc
  limit lim
  offset off;
$fn$;
