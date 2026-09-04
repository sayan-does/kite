create table if not exists profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  created_at timestamptz default now()
);

create table if not exists interest_tags (
  id serial primary key,
  name text unique not null,
  category text not null
);

create table if not exists user_interests (
  user_id uuid references profiles(id) on delete cascade,
  tag_id int references interest_tags(id),
  primary key (user_id, tag_id)
);

create table if not exists articles (
  id uuid primary key default gen_random_uuid(),
  tag_id int references interest_tags(id),
  title text not null,
  summary text not null,
  body text,
  citations jsonb not null default '[]',
  youtube_url text,
  published_at timestamptz default now()
);

create table if not exists tracked_dependencies (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references profiles(id) on delete cascade,
  ecosystem text not null check (ecosystem in ('npm','pip','maven')),
  package_name text not null,
  version text not null,
  source text not null check (source in ('upload','manual')),
  created_at timestamptz default now(),
  unique (user_id, ecosystem, package_name)
);

create table if not exists package_registry_cache (
  ecosystem text not null,
  package_name text not null,
  latest_version text,
  last_checked_at timestamptz,
  primary key (ecosystem, package_name)
);

create table if not exists dependency_updates (
  id uuid primary key default gen_random_uuid(),
  ecosystem text not null,
  package_name text not null,
  version text not null,
  update_type text not null check (update_type in ('release','security','breaking','buzz')),
  summary text not null,
  citations jsonb not null default '[]',
  published_at timestamptz default now(),
  unique (ecosystem, package_name, version, update_type)
);

create table if not exists notification_settings (
  user_id uuid references profiles(id) on delete cascade,
  category text not null,
  channel text not null check (channel in ('in_app','email')),
  enabled boolean default true,
  primary key (user_id, category, channel)
);

create table if not exists citation_prefs (
  user_id uuid references profiles(id) on delete cascade,
  source_type text not null check (source_type in ('official_docs','github','blog','youtube')),
  enabled boolean default true,
  primary key (user_id, source_type)
);
