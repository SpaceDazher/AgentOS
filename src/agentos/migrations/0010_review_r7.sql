-- 0010_review_r7.sql — R7 corrective (non-destructive upgrade):
-- * stage_gate gains binding columns (artifact_chain_hash, corpus_version);
--   existing rows are PRESERVED with empty bindings (treated as stale by the
--   release gate until re-issued against the current chain)
-- * campaigns from 0009 (which lost goal binding) are recovered: a campaign
--   whose goal is unknown keeps an explicit 'goal_ORPHANED_<id>' marker so
--   history survives; experiments stay linked to their campaign.

CREATE TABLE stage_gate_new (
  id TEXT PRIMARY KEY,
  stage TEXT NOT NULL,
  required_eval_ids_json TEXT NOT NULL,
  decision TEXT NOT NULL CHECK (decision IN ('pass','fail')),
  rationale TEXT NOT NULL,
  authority TEXT NOT NULL DEFAULT 'GateAuthority',
  goal_id TEXT,
  artifact_chain_hash TEXT NOT NULL DEFAULT '',
  corpus_version TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
INSERT INTO stage_gate_new(id, stage, required_eval_ids_json, decision,
                           rationale, authority, goal_id, artifact_chain_hash,
                           corpus_version, created_at)
SELECT id, stage, required_eval_ids_json, decision, rationale, authority,
       goal_id, '', '', created_at FROM stage_gate;
DROP TABLE stage_gate;
ALTER TABLE stage_gate_new RENAME TO stage_gate;

CREATE TRIGGER stage_gate_no_update BEFORE UPDATE ON stage_gate
BEGIN SELECT RAISE(ABORT, 'stage_gate decisions are append-only'); END;
CREATE TRIGGER stage_gate_no_delete BEFORE DELETE ON stage_gate
BEGIN SELECT RAISE(ABORT, 'stage_gate decisions are append-only'); END;
CREATE INDEX idx_stage_gate_goal ON stage_gate(goal_id);

-- R7: DB-enforced campaign/experiment goal scoping — a raw SQL INSERT can
-- no longer attach an experiment to a foreign goal (Python checks alone
-- were bypassable). Campaigns migrated by 0009 are owned by goal_MIGRATED,
-- so every experiment row resolves to an owner.
CREATE TRIGGER experiment_goal_owner BEFORE INSERT ON experiment
WHEN NEW.goal_id IS NOT NULL AND NEW.goal_id != (SELECT goal_id FROM campaign WHERE id = NEW.campaign_id)
BEGIN SELECT RAISE(ABORT, 'experiment goal must match campaign owner'); END;
