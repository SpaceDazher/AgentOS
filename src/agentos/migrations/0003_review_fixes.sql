-- 0003_review_fixes.sql — criterion versioning, evaluation binding, fence counter.
-- acceptance_criteria recreated: (goal_id, criterion_id) is no longer UNIQUE;
-- each refine_spec appends a new immutable criterion_version.
CREATE TABLE acceptance_criteria_new (
  id TEXT PRIMARY KEY,
  goal_id TEXT NOT NULL REFERENCES goal(id),
  criterion_id TEXT NOT NULL,
  criterion_version INTEGER NOT NULL,
  kind TEXT NOT NULL,
  params_json TEXT NOT NULL DEFAULT '{}',
  config_hash TEXT NOT NULL DEFAULT '',
  UNIQUE (goal_id, criterion_id, criterion_version)
);
INSERT INTO acceptance_criteria_new(id, goal_id, criterion_id, criterion_version,
                                    kind, params_json, config_hash)
SELECT id, goal_id, criterion_id, 1, kind, params_json, '' FROM acceptance_criteria;
DROP TABLE acceptance_criteria;
ALTER TABLE acceptance_criteria_new RENAME TO acceptance_criteria;

ALTER TABLE evaluation ADD COLUMN criterion_version INTEGER;
ALTER TABLE evaluation ADD COLUMN artifact_chain_hash TEXT;

CREATE TABLE fence_counter (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  value INTEGER NOT NULL
);
INSERT INTO fence_counter(id, value) VALUES (1, 0);
