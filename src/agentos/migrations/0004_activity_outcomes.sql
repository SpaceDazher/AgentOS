-- 0004_activity_outcomes.sql — F8: outcome-specific reconciliation states
CREATE TABLE activity_new (
  id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES run(id),
  op_name TEXT NOT NULL,
  tool_identity TEXT NOT NULL,
  args_canonical_json TEXT NOT NULL,
  effect_class TEXT NOT NULL CHECK (effect_class IN ('read','write_local','write_external','dangerous')),
  status TEXT NOT NULL DEFAULT 'REQUESTED'
    CHECK (status IN ('REQUESTED','AUTHORIZED','EXECUTING','SUCCEEDED','FAILED','UNKNOWN_OUTCOME','RECONCILED_SUCCEEDED','RECONCILED_FAILED','DENIED')),
  result_digest TEXT,
  detail_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
INSERT INTO activity_new SELECT * FROM activity;
DROP TABLE activity;
ALTER TABLE activity_new RENAME TO activity;
