-- Phase 11: daily AI quiz and streak.
--
-- Questions are stored server-side with their answers so grading cannot be
-- tampered with from the client, and so a day's quiz cannot be re-rolled for a
-- better set of questions.

create table if not exists quiz_sessions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references profiles(id) on delete cascade,

  tag_id int references interest_tags(id) on delete set null,
  topic text,
  niche text,
  niche_options jsonb not null default '[]',

  -- UTC calendar day. One row per user per day is what enforces the single
  -- scoring attempt; a failed quiz locks the day out until tomorrow.
  quiz_date date not null,

  status text not null default 'niche_pending'
    check (status in ('niche_pending', 'questions_ready', 'submitted')),

  correct_count int,
  passed boolean,

  created_at timestamptz default now(),
  submitted_at timestamptz,

  unique (user_id, quiz_date)
);

create index if not exists idx_quiz_sessions_user_date
  on quiz_sessions (user_id, quiz_date desc);

create table if not exists quiz_questions (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null references quiz_sessions(id) on delete cascade,

  position int not null check (position between 1 and 3),
  question text not null,
  options jsonb not null,
  correct_index int not null check (correct_index between 0 and 3),
  chosen_index int check (chosen_index between 0 and 3),

  created_at timestamptz default now(),

  unique (session_id, position)
);

create index if not exists idx_quiz_questions_session
  on quiz_questions (session_id, position);

create table if not exists user_streaks (
  user_id uuid primary key references profiles(id) on delete cascade,
  current_streak int not null default 0,
  longest_streak int not null default 0,
  last_success_date date,
  updated_at timestamptz default now()
);
