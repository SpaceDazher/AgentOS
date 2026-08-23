-- 0007_stage_evals.sql — Phase 1: versioned stage-eval entities.
-- All rows append-only: UPDATE/DELETE refused by triggers (ADR-0006).
-- Corrections create NEW versions; existing definitions/results immutable.

CREATE TABLE eval_definition (
  id TEXT NOT NULL,                       -- stable definition id
  version INTEGER NOT NULL,               -- 1..n; corrections bump
  stage TEXT NOT NULL CHECK (stage IN ('concept','specification','plan',
    'execution','verification','post_episode')),
  kind TEXT NOT NULL CHECK (kind IN ('deterministic','llm_judge')),
  metric TEXT NOT NULL,
  direction TEXT NOT NULL CHECK (direction IN ('minimize','maximize')),
  threshold REAL NOT NULL,
  timeout_s REAL NOT NULL DEFAULT 30,
  corpus_version TEXT NOT NULL,
  independence_class TEXT NOT NULL DEFAULT 'normal'
    CHECK (independence_class IN ('normal','holdout','frozen')),
  required INTEGER NOT NULL DEFAULT 1,    -- 1 = blocking at gate; 0 = advisory
  prompt_version TEXT,                    -- llm_judge only
  rubric_version TEXT,                    -- llm_judge only
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  PRIMARY KEY (id, version)
);

CREATE TRIGGER eval_definition_no_update BEFORE UPDATE ON eval_definition
BEGIN SELECT RAISE(ABORT, 'eval_definition is append-only'); END;
CREATE TRIGGER eval_definition_no_delete BEFORE DELETE ON eval_definition
BEGIN SELECT RAISE(ABORT, 'eval_definition is append-only'); END;

CREATE TABLE eval_case (
  id TEXT PRIMARY KEY,                    -- stable case id
  corpus_version TEXT NOT NULL,
  stage TEXT NOT NULL,
  label TEXT NOT NULL,
  set_class TEXT NOT NULL CHECK (set_class IN ('gold','near_miss',
    'alternative_correct','adversarial','incomplete')),
  input_ref TEXT NOT NULL,                -- path or canonical pointer (data)
  expected_outcome TEXT NOT NULL,         -- 'pass' | 'fail' | json verdict
  provenance_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TRIGGER eval_case_no_update BEFORE UPDATE ON eval_case
BEGIN SELECT RAISE(ABORT, 'eval_case is append-only'); END;
CREATE TRIGGER eval_case_no_delete BEFORE DELETE ON eval_case
BEGIN SELECT RAISE(ABORT, 'eval_case is append-only'); END;

CREATE TABLE eval_run (
  id TEXT PRIMARY KEY,
  goal_id TEXT, task_id TEXT, run_id TEXT, artifact_chain_hash TEXT,
  definition_id TEXT NOT NULL,
  definition_version INTEGER NOT NULL,
  env_json TEXT NOT NULL DEFAULT '{}',    -- python/harness/tool versions
  seed INTEGER,
  metrics_json TEXT NOT NULL DEFAULT '{}',
  outcome TEXT NOT NULL CHECK (outcome IN ('pass','fail','error','skipped')),
  logs_sha256 TEXT,
  duration_ms INTEGER,
  failure_class TEXT,                     -- provider | evaluator | policy | null
  judge_json TEXT,                        -- model_id/prompt/rubric for llm_judge
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  FOREIGN KEY (definition_id, definition_version)
    REFERENCES eval_definition(id, version)
);

CREATE TRIGGER eval_run_no_update BEFORE UPDATE ON eval_run
BEGIN SELECT RAISE(ABORT, 'eval_run is append-only'); END;
CREATE TRIGGER eval_run_no_delete BEFORE DELETE ON eval_run
BEGIN SELECT RAISE(ABORT, 'eval_run is append-only'); END;

CREATE TABLE stage_gate (
  id TEXT PRIMARY KEY,
  stage TEXT NOT NULL,
  required_eval_ids_json TEXT NOT NULL,   -- ["id@version", ...]
  decision TEXT NOT NULL CHECK (decision IN ('pass','fail')),
  rationale TEXT NOT NULL,
  authority TEXT NOT NULL DEFAULT 'GateAuthority',
  goal_id TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE experiment (
  id TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL,
  hypothesis TEXT NOT NULL,
  baseline_ref TEXT NOT NULL,
  candidate_ref TEXT NOT NULL,
  mutable_scope_json TEXT NOT NULL,
  budget_json TEXT NOT NULL DEFAULT '{}',
  seeds_json TEXT NOT NULL DEFAULT '[]',
  primary_metric TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('proposed','running','KEEP',
    'DISCARD','RETEST','CRASH','QUARANTINED')),
  measurements_json TEXT NOT NULL DEFAULT '{}',
  decision_rationale TEXT,
  frozen_hashes_json TEXT NOT NULL DEFAULT '{}',
  evidence_pack_path TEXT,
  evidence_pack_sha256 TEXT,
  wiki_note TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  decided_at TEXT
);

CREATE INDEX idx_eval_run_def ON eval_run(definition_id, definition_version);
CREATE INDEX idx_experiment_campaign ON experiment(campaign_id);
