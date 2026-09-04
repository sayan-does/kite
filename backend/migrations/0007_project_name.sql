-- Group tracked dependencies by project.
alter table tracked_dependencies
  add column if not exists project_name text;

update tracked_dependencies
set project_name = 'Uncategorized'
where project_name is null or btrim(project_name) = '';

alter table tracked_dependencies
  alter column project_name set not null;

alter table tracked_dependencies
  drop constraint if exists tracked_dependencies_user_id_ecosystem_package_name_key;

alter table tracked_dependencies
  drop constraint if exists tracked_dependencies_user_id_project_name_ecosystem_package_name_key;

alter table tracked_dependencies
  add constraint tracked_dependencies_user_id_project_name_ecosystem_package_name_key
  unique (user_id, project_name, ecosystem, package_name);
