-- Phase 2: per-user API keys (for the MCP server + personal RSS feed) and
-- a saved/read-later flag on article state. All additive.

-- Personal API key: users mint one key they paste into their own AI client
-- (MCP) or RSS reader. We store only a sha256 hash; the raw key is shown once.
alter table profiles add column if not exists api_key_hash text;
alter table profiles add column if not exists api_key_prefix text;
alter table profiles add column if not exists api_key_created_at timestamptz;

create unique index if not exists profiles_api_key_hash_idx
  on profiles (api_key_hash)
  where api_key_hash is not null;

-- Saved / read-later.
alter table user_article_state add column if not exists saved boolean not null default false;
alter table user_article_state add column if not exists saved_at timestamptz;

create index if not exists user_article_state_saved_idx
  on user_article_state (user_id)
  where saved = true;
