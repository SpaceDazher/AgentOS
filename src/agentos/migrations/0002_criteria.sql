-- 0002_criteria.sql — acceptance criteria + fence counter
CREATE TABLE acceptance_criteria (
  id TEXT PRIMARY KEY,
  goal_id TEXT NOT NULL REFERENCES goal(id),
  criterion_id TEXT NOT NULL,
  kind TEXT NOT NULL,             -- e.g. tests_present | invariant | command_exit_0
  params_json TEXT NOT NULL DEFAULT '{}',
  UNIQUE (goal_id, criterion_id)
);
