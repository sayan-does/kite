-- Phase 11: curated source feeds for the seven supported categories.
--
-- Every URL below was verified to return HTTP 200 with parseable feed content.
-- Sources from the original brief that have no machine-readable feed are not
-- seeded: nvd.nist.gov (RSS retired, JSON CVE API only), docs.python.org
-- whatsnew, tiobe.com/tiobe-index, paperswithcode.com, devopsweekly.com, and
-- playwright.dev/blog. Playwright is covered through its GitHub releases atom
-- feed instead. Hacker News is already covered by the kind='hn' row seeded in
-- 0009, which is expanded per target topic at collect time.

-- ---------------------------------------------------------------------------
-- 12.1  topic_kind: let a feed opt into interest-kind articles
-- ---------------------------------------------------------------------------
-- Left nullable rather than defaulted, so collect_github_releases keeps its
-- existing 'stack' behaviour for the dynamic pkg: rows that carry no value.

alter table source_feeds add column if not exists topic_kind text;

do $$
begin
  if not exists (select 1 from pg_constraint where conname = 'source_feeds_topic_kind_check') then
    alter table source_feeds add constraint source_feeds_topic_kind_check
      check (topic_kind is null or topic_kind in ('interest', 'stack'));
  end if;
end $$;

-- ---------------------------------------------------------------------------
-- 12.2  Seed per-category feeds
-- ---------------------------------------------------------------------------
-- Reddit rate-limits aggressively and answers 429 to unknown clients. The
-- collector already retries with Retry-After backoff, but a 180 minute poll
-- interval keeps normal operation well clear of the limit.

insert into source_feeds (kind, url, title, topic, tag_id, weight, poll_interval_minutes, topic_kind)
select v.kind, v.url, v.title, v.topic, t.id, v.weight, v.poll_interval, v.topic_kind
  from (values
    -- Frontend
    ('rss',    'https://frontendfoc.us/rss',              'Frontend Focus',        'Frontend',              1.3, 180, 'interest'),
    ('rss',    'https://web.dev/feed.xml',                'web.dev Blog',          'Frontend',              1.3,  60, 'interest'),
    ('rss',    'https://css-tricks.com/feed/',            'CSS-Tricks',            'Frontend',              1.1,  90, 'interest'),

    -- Backend
    ('rss',    'https://feed.infoq.com/',                 'InfoQ',                 'Backend',               1.2,  60, 'interest'),
    ('rss',    'https://changelog.com/feed',              'Changelog',             'Backend',               1.1,  90, 'interest'),
    ('rss',    'https://www.reddit.com/r/node/.rss',      'r/node',                'Backend',               0.9, 180, 'interest'),
    ('rss',    'https://www.reddit.com/r/golang/.rss',    'r/golang',              'Backend',               0.9, 180, 'interest'),
    ('rss',    'https://www.reddit.com/r/rust/.rss',      'r/rust',                'Backend',               0.9, 180, 'interest'),

    -- AI/ML  (HF blog, HF daily papers and arXiv cs.LG already seeded in 0009)
    ('papers', 'http://export.arxiv.org/api/query?search_query=cat:cs.AI&sortBy=submittedDate&sortOrder=descending&max_results=40',
                                                          'arXiv cs.AI',           'AI/ML',                 1.1, 180, 'interest'),

    -- DevOps  (kubernetes.io already seeded in 0009)
    ('rss',    'https://www.cncf.io/feed/',               'CNCF Blog',             'DevOps',                1.2,  90, 'interest'),

    -- Security
    ('rss',    'https://thehackernews.com/feeds/posts/default',
                                                          'The Hacker News',       'Security',              1.2,  60, 'interest'),
    ('rss',    'https://krebsonsecurity.com/feed/',       'Krebs on Security',     'Security',              1.2,  90, 'interest'),
    ('rss',    'https://www.reddit.com/r/netsec/.rss',    'r/netsec',              'Security',              1.0, 180, 'interest'),

    -- Automation
    ('rss',    'https://n8n.io/blog/rss',                 'n8n Blog',              'Automation',            1.3,  90, 'interest'),
    ('github', 'https://github.com/microsoft/playwright/releases.atom',
                                                          'Playwright Releases',   'Automation',            1.2, 180, 'interest'),
    ('rss',    'https://www.reddit.com/r/automation/.rss','r/automation',          'Automation',            0.9, 180, 'interest'),

    -- Programming Languages  (blog.rust-lang.org already seeded in 0009)
    ('rss',    'https://go.dev/blog/feed.atom',           'Go Blog',               'Programming Languages', 1.3,  90, 'interest')
  ) as v(kind, url, title, topic, weight, poll_interval, topic_kind)
  join interest_tags t on t.name = v.topic
on conflict (kind, url) do nothing;

-- Existing rows predate the column and are all interest-kind category feeds.
update source_feeds
   set topic_kind = 'interest'
 where topic_kind is null
   and kind in ('rss', 'papers', 'hn')
   and url not like 'pkg:%';
