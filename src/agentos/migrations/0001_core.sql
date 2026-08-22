-- 0001_core.sql — canonical model v1 (see spec/SPEC.md §3)
CREATE TABLE goal (
  id TEXT PRIMARY KEY,
  concept_text TEXT NOT NULL,
  constraints_json TEXT NOT NULL DEFAULT '{}',
  risk_tier TEXT NOT NULL DEFAULT 'normal' CHECK (risk_tier IN ('normal','sensitive')),
  budget_json TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'DRAFT'
    CHECK (status IN ('DRAFT','ACTIVE','GATE_PENDING','ACCEPTED','REJECTED','ESCALATED','CANCELLED')),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE artifact_version (
  id TEXT PRIMARY KEY,
  goal_id TEXT NOT NULL REFERENCES goal(id),
  kind TEXT NOT NULL CHECK (kind IN ('concept','specification','plan','code','test_report','evidence_pack','skill_seed')),
  version INTEGER NOT NULL,
  content_sha256 TEXT NOT NULL,
  storage_path TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'CURRENT' CHECK (status IN ('DRAFT','CURRENT','SUPERSEDED','WITHDRAWN')),
  superseded_by_id TEXT REFERENCES artifact_version(id),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  UNIQUE (goal_id, kind, version)
);

CREATE TABLE task (
  id TEXT PRIMARY KEY,
  goal_id TEXT NOT NULL REFERENCES goal(id),
  title TEXT NOT NULL,
  depends_on_json TEXT NOT NULL DEFAULT '[]',
  inputs_json TEXT NOT NULL DEFAULT '{}',
  expected_outputs_json TEXT NOT NULL DEFAULT '[]',
  definition_of_done TEXT NOT NULL,
  risk_tier TEXT NOT NULL DEFAULT 'normal',
  retry_budget INTEGER NOT NULL DEFAULT 2,
  attempts INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'PENDING'
    CHECK (status IN ('PENDING','READY','RUNNING','DONE','FAILED','BLOCKED','CANCELLED')),
  owner_run_id TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE run (
  id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL REFERENCES task(id),
  goal_id TEXT NOT NULL REFERENCES goal(id),
  worker_type TEXT NOT NULL,
  config_versions_json TEXT NOT NULL DEFAULT '{}',
  lease_owner TEXT,
  lease_expires_at TEXT,
  workspace_path TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'PLANNED'
    CHECK (status IN ('PLANNED','RUNNING','PAUSED','COMPLETED','FAILED','CANCELLED')),
  terminal_reason TEXT,
  resumed_from_run_id TEXT REFERENCES run(id),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE activity (
  id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES run(id),
  op_name TEXT NOT NULL,
  tool_identity TEXT NOT NULL,
  args_canonical_json TEXT NOT NULL,
  effect_class TEXT NOT NULL CHECK (effect_class IN ('read','write_local','write_external','dangerous')),
  status TEXT NOT NULL DEFAULT 'REQUESTED'
    CHECK (status IN ('REQUESTED','AUTHORIZED','EXECUTING','SUCCEEDED','FAILED','UNKNOWN_OUTCOME','RECONCILED','DENIED')),
  result_digest TEXT,
  detail_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE evaluation (
  id TEXT PRIMARY KEY,
  goal_id TEXT NOT NULL REFERENCES goal(id),
  subject_artifact_id TEXT REFERENCES artifact_version(id),
  criterion_id TEXT NOT NULL,
  method TEXT NOT NULL,
  method_version TEXT NOT NULL,
  config_json TEXT NOT NULL DEFAULT '{}',
  result TEXT NOT NULL CHECK (result IN ('pass','fail')),
  detail_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE gate (
  id TEXT PRIMARY KEY,
  goal_id TEXT NOT NULL REFERENCES goal(id),
  predicate_name TEXT NOT NULL,
  predicate_version TEXT NOT NULL,
  input_fingerprint TEXT NOT NULL,
  result TEXT NOT NULL CHECK (result IN ('pass','fail','escalate')),
  rationale TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE approval (
  id TEXT PRIMARY KEY,
  goal_id TEXT NOT NULL REFERENCES goal(id),
  actor TEXT NOT NULL,
  operation TEXT NOT NULL,
  tool_identity TEXT NOT NULL,
  args_canonical_json TEXT NOT NULL,
  target TEXT NOT NULL,
  policy_version TEXT NOT NULL,
  limits_json TEXT NOT NULL DEFAULT '{}',
  expires_at TEXT NOT NULL,
  nonce TEXT NOT NULL UNIQUE,
  status TEXT NOT NULL DEFAULT 'GRANTED' CHECK (status IN ('GRANTED','CONSUMED','EXPIRED','REVOKED')),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE checkpoint (
  id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES run(id),
  seq INTEGER NOT NULL,
  payload_path TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  work_completed_json TEXT NOT NULL DEFAULT '[]',
  work_in_progress_json TEXT NOT NULL DEFAULT '{}',
  next_action_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  UNIQUE (run_id, seq)
);

CREATE TABLE tool_contract (
  name TEXT NOT NULL,
  version TEXT NOT NULL,
  input_schema_json TEXT NOT NULL,
  output_schema_json TEXT NOT NULL DEFAULT '{}',
  server_identity TEXT NOT NULL,
  required_capability TEXT NOT NULL,
  effect_class TEXT NOT NULL CHECK (effect_class IN ('read','write_local','write_external','dangerous')),
  sensitivity TEXT NOT NULL DEFAULT 'normal',
  idempotency TEXT NOT NULL CHECK (idempotency IN ('none','keyed','natural')),
  retry_policy_json TEXT NOT NULL DEFAULT '{}',
  compensation TEXT,
  preconditions_json TEXT NOT NULL DEFAULT '{}',
  postconditions_json TEXT NOT NULL DEFAULT '{}',
  audit_level TEXT NOT NULL DEFAULT 'full',
  schema_fingerprint TEXT NOT NULL,
  PRIMARY KEY (name, version)
);

CREATE TABLE memory_record (
  id TEXT PRIMARY KEY,
  scope_goal_id TEXT NOT NULL REFERENCES goal(id),
  kind TEXT NOT NULL,
  content TEXT NOT NULL,
  source_uri TEXT NOT NULL,
  trust TEXT NOT NULL DEFAULT 'unverified',
  ttl_until TEXT,
  invalidated_by_id TEXT REFERENCES memory_record(id),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE relation_assertion (
  id TEXT PRIMARY KEY,
  src_type TEXT NOT NULL, src_id TEXT NOT NULL,
  rel TEXT NOT NULL,
  dst_type TEXT NOT NULL, dst_id TEXT NOT NULL,
  asserter TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'asserted',
  evidence_ids_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE claim (
  id TEXT PRIMARY KEY,
  goal_id TEXT NOT NULL REFERENCES goal(id),
  text TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'asserted' CHECK (status IN ('asserted','supported','challenged','defeated')),
  validation_plan_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE evidence (
  id TEXT PRIMARY KEY,
  goal_id TEXT NOT NULL REFERENCES goal(id),
  kind TEXT NOT NULL,
  uri TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  freshness_at TEXT,
  provenance_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE decision (
  id TEXT PRIMARY KEY,
  goal_id TEXT NOT NULL REFERENCES goal(id),
  question TEXT NOT NULL,
  selected_alternative TEXT NOT NULL,
  rationale TEXT NOT NULL,
  supersedes_id TEXT REFERENCES decision(id)
);

CREATE TABLE world_observation (
  id TEXT PRIMARY KEY,
  goal_id TEXT NOT NULL REFERENCES goal(id),
  subject TEXT NOT NULL,
  value_json TEXT NOT NULL,
  observed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  source_evidence_id TEXT REFERENCES evidence(id)
);

CREATE TABLE idempotency_key (
  key_hash TEXT PRIMARY KEY,
  operation TEXT NOT NULL,
  args_canonical_json TEXT NOT NULL,
  first_seen_run_id TEXT NOT NULL,
  outcome_digest TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE audit_event (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  goal_id TEXT,
  actor TEXT NOT NULL,
  event_type TEXT NOT NULL,
  payload_json TEXT NOT NULL DEFAULT '{}',
  prev_event_sha256 TEXT
);
