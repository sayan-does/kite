-- AI/ML research news: soft Research label on KB articles (not a citation source_type)

alter table kb_articles
  add column if not exists is_research boolean not null default false;
