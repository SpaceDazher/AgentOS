-- 0009_review_r6.sql — R6 corrective:
-- * real binding columns on eval_run (case_id, corpus_version,
--   artifact_chain_hash NOT NULL) instead of env_json packing
--   (artifact_chain_hash already existed as nullable since 0007)
-- * campaign gains a required goal_id (campaign belongs to ONE goal)

CREATE TABLE eval_run_new (
  id TEXT PRIMARY KEY,
  goal_id TEXT, task_id TEXT, run_id TEXT, artifact_chain_hash TEXT NOT NULL,
  definition_id TEXT NOT NULL,
  definition_version INTEGER NOT NULL,
  env_json TEXT NOT NULL DEFAULT '{}',
  seed INTEGER,
  metrics_json TEXT NOT NULL DEFAULT '{}',
  outcome TEXT NOT NULL CHECK (outcome IN ('pass','fail','error','skipped')),
  logs_sha256 TEXT,
  duration_ms INTEGER,
  failure_class TEXT,
  judge_json TEXT,
  case_id TEXT,
  corpus_version TEXT NOT NULL DEFAULT 'c1',
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  FOREIGN KEY (definition_id, definition_version)
    REFERENCES eval_definition(id, version)
);
INSERT INTO eval_run_new SELECT id, goal_id, task_id, run_id,
       COALESCE(artifact_chain_hash,''), definition_id, definition_version,
       env_json, seed, metrics_json, outcome, logs_sha256, duration_ms,
       failure_class, judge_json, NULL, 'c1', created_at FROM eval_run;
DROP TABLE eval_run;
ALTER TABLE eval_run_new RENAME TO eval_run;
CREATE TRIGGER eval_run_no_update BEFORE UPDATE ON eval_run
BEGIN SELECT RAISE(ABORT, 'eval_run is append-only'); END;
CREATE TRIGGER eval_run_no_delete BEFORE DELETE ON eval_run
BEGIN SELECT RAISE(ABORT, 'eval_run is append-only'); END;
CREATE INDEX idx_eval_run_def ON eval_run(definition_id, definition_version);
CREATE INDEX idx_eval_run_goal ON eval_run(goal_id);

-- Preserve campaign history: rebind pre-goal-binding campaigns to an
-- explicit migration goal instead of destroying them. (Status must satisfy
-- the goal status CHECK; CANCELLED marks it non-executable.)
INSERT OR IGNORE INTO goal(id, concept_text, status)
VALUES ('goal_MIGRATED',
        'campaigns migrated from pre-goal-binding schema (0009)',
        'CANCELLED');

CREATE TABLE campaign_migrated (
  id TEXT PRIMARY KEY,
  goal_id TEXT NOT NULL REFERENCES goal(id),
  name TEXT NOT NULL,
  manifest_json TEXT NOT NULL,
  manifest_sha256 TEXT NOT NULL,
  baseline_ref TEXT NOT NULL,
  primary_metric TEXT NOT NULL,
  budget INTEGER NOT NULL,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
INSERT INTO campaign_migrated(id, goal_id, name, manifest_json,
                              manifest_sha256, baseline_ref,
                              primary_metric, budget, created_at)
SELECT id, 'goal_MIGRATED', name, manifest_json, manifest_sha256,
       baseline_ref, primary_metric, budget, created_at FROM campaign;
DROP TABLE campaign;
ALTER TABLE campaign_migrated RENAME TO campaign;
CREATE TRIGGER campaign_no_update BEFORE UPDATE ON campaign
BEGIN SELECT RAISE(ABORT, 'campaign is immutable'); END;
CREATE TRIGGER campaign_no_delete BEFORE DELETE ON campaign
BEGIN SELECT RAISE(ABORT, 'campaign is immutable'); END;

-- stage_gate/experiment append-only triggers already exist (0008);
-- indexes idx_stage_gate_goal / idx_experiment_goal also exist from 0008
CREATE INDEX idx_campaign_goal ON campaign(goal_id);
