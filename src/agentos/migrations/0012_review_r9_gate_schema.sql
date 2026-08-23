-- 0012_review_r9_gate_schema.sql — repair old/partial 0010 gate rebuilds.
--
-- Legacy decisions remain append-only evidence.  Rows without binding columns
-- are copied with empty bindings and therefore fail closed as stale until a
-- new gate is issued.  The common-column copy also recovers a stage_gate_new
-- table left by an interrupted historical 0010.

-- On the normal path 0010 already produced this bound schema.  On a database
-- where the old rebuild completed only as far as ``stage_gate_new``, the
-- migration runner first restores a conservative pre-0010 table and retries
-- 0010.  Defining both sources here makes the final merge safe when either
-- table is absent and preserves bindings when it is present.
CREATE TABLE IF NOT EXISTS stage_gate (
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

CREATE TABLE IF NOT EXISTS stage_gate_new (
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

CREATE TABLE stage_gate_r9 (
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
INSERT OR IGNORE INTO stage_gate_r9(
  id, stage, required_eval_ids_json, decision, rationale, authority,
  goal_id, artifact_chain_hash, corpus_version, created_at)
SELECT id, stage, required_eval_ids_json, decision, rationale, authority,
       goal_id, artifact_chain_hash, corpus_version, created_at FROM stage_gate;
INSERT OR IGNORE INTO stage_gate_r9(
  id, stage, required_eval_ids_json, decision, rationale, authority,
  goal_id, artifact_chain_hash, corpus_version, created_at)
SELECT id, stage, required_eval_ids_json, decision, rationale, authority,
       goal_id, artifact_chain_hash, corpus_version, created_at
  FROM stage_gate_new;

DROP TRIGGER IF EXISTS stage_gate_no_update;
DROP TRIGGER IF EXISTS stage_gate_no_delete;
DROP INDEX IF EXISTS idx_stage_gate_goal;
DROP TABLE IF EXISTS stage_gate_new;
DROP TABLE stage_gate;
ALTER TABLE stage_gate_r9 RENAME TO stage_gate;

CREATE TRIGGER stage_gate_no_update BEFORE UPDATE ON stage_gate
BEGIN SELECT RAISE(ABORT, 'stage_gate decisions are append-only'); END;
CREATE TRIGGER stage_gate_no_delete BEFORE DELETE ON stage_gate
BEGIN SELECT RAISE(ABORT, 'stage_gate decisions are append-only'); END;
CREATE INDEX idx_stage_gate_goal ON stage_gate(goal_id);
