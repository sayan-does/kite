insert into interest_tags (name, category) values
  ('Frontend', 'Frontend'),
  ('Backend', 'Backend'),
  ('AI/ML', 'AI/ML'),
  ('DevOps', 'DevOps'),
  ('Databases', 'Databases'),
  ('Mobile', 'Mobile'),
  ('Security', 'Security'),
  ('Cloud Infra', 'Cloud Infra'),
  ('Programming Languages', 'Programming Languages'),
  ('Developer Tools', 'Developer Tools')
on conflict (name) do nothing;
