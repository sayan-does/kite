-- Allow GitHub-sourced dependencies and optional provenance columns.
alter table tracked_dependencies
  drop constraint if exists tracked_dependencies_source_check;

alter table tracked_dependencies
  add constraint tracked_dependencies_source_check
  check (source in ('upload', 'manual', 'github'));

alter table tracked_dependencies
  add column if not exists github_repo text;

alter table tracked_dependencies
  add column if not exists github_path text;
