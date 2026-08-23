-- 0008_review_r5.sql — R4/R5 corrective round:
-- * decisions become append-only (stage_gate, experiment)
-- * experiments bind to a goal; campaigns are separate immutable entities
-- * eval_run gains case/goal/artifact-chain/corpus bindings

ALTER TABLE experiment ADD COLUMN goal_id TEXT;

CREATE TABLE campaign (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  manifest_json TEXT NOT NULL,
  manifest_sha256 TEXT NOT NULL,
  baseline_ref TEXT NOT NULL,
  primary_metric TEXT NOT NULL,
  budget INTEGER NOT NULL,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE TRIGGER campaign_no_update BEFORE UPDATE ON campaign
BEGIN SELECT RAISE(ABORT, 'campaign is immutable'); END;
CREATE TRIGGER campaign_no_delete BEFORE DELETE ON campaign
BEGIN SELECT RAISE(ABORT, 'campaign is immutable'); END;

CREATE TRIGGER stage_gate_no_update BEFORE UPDATE ON stage_gate
BEGIN SELECT RAISE(ABORT, 'stage_gate decisions are append-only'); END;
CREATE TRIGGER stage_gate_no_delete BEFORE DELETE ON stage_gate
BEGIN SELECT RAISE(ABORT, 'stage_gate decisions are append-only'); END;

CREATE TRIGGER experiment_no_update BEFORE UPDATE ON experiment
BEGIN SELECT RAISE(ABORT, 'experiment decisions are append-only'); END;
CREATE TRIGGER experiment_no_delete BEFORE DELETE ON experiment
BEGIN SELECT RAISE(ABORT, 'experiment decisions are append-only'); END;

CREATE INDEX idx_stage_gate_goal ON stage_gate(goal_id);
CREATE INDEX idx_experiment_goal ON experiment(goal_id);
