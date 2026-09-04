-- Shared 90-day rolling version timeline for My Stack package detail.
create table if not exists package_version_timeline (
  id uuid primary key default gen_random_uuid(),
  ecosystem text not null check (ecosystem in ('npm','pip','maven')),
  package_name text not null,
  version text not null,
  published_at timestamptz,
  summary text,
  is_security boolean not null default false,
  is_breaking boolean not null default false,
  citations jsonb not null default '[]',
  ingested_at timestamptz not null default now(),
  unique (ecosystem, package_name, version)
);

create index if not exists idx_pkg_timeline_eco_pkg_published
  on package_version_timeline (ecosystem, package_name, published_at desc nulls last);

create index if not exists idx_pkg_timeline_published_at
  on package_version_timeline (published_at);

create index if not exists idx_pkg_timeline_ingested_at
  on package_version_timeline (ingested_at);
