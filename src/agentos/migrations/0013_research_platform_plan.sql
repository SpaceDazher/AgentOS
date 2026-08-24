-- 0013_research_platform_plan.sql — bounded, provider-neutral research
-- campaigns.  This migration is intentionally additive: historical schema
-- files are never rewritten and the wiki/evidence layers treat these tables
-- as canonical state.

CREATE TABLE research_campaign (
  id TEXT PRIMARY KEY,
  goal_id TEXT NOT NULL REFERENCES goal(id),
  topic TEXT NOT NULL CHECK (length(trim(topic)) > 0),
  config_json TEXT NOT NULL DEFAULT '{}',
  thresholds_json TEXT NOT NULL DEFAULT '{}',
  manifest_sha256 TEXT NOT NULL
    CHECK (length(manifest_sha256) = 64
       AND manifest_sha256 NOT GLOB '*[^0-9a-fA-F]*'),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  UNIQUE (id, goal_id),
  UNIQUE (goal_id)
);

CREATE TRIGGER research_campaign_no_update
BEFORE UPDATE ON research_campaign
BEGIN SELECT RAISE(ABORT, 'research campaign is immutable'); END;
CREATE TRIGGER research_campaign_no_delete
BEFORE DELETE ON research_campaign
BEGIN SELECT RAISE(ABORT, 'research campaign is immutable'); END;

-- A separate immutable projection makes the campaign configuration explicit
-- and gives consumers a stable table to audit without parsing the campaign
-- envelope.  The duplicate values are deliberate canonical evidence.
CREATE TABLE research_campaign_config (
  campaign_id TEXT NOT NULL,
  goal_id TEXT NOT NULL REFERENCES goal(id),
  topic TEXT NOT NULL CHECK (length(trim(topic)) > 0),
  thresholds_json TEXT NOT NULL DEFAULT '{}',
  manifest_sha256 TEXT NOT NULL
    CHECK (length(manifest_sha256) = 64
       AND manifest_sha256 NOT GLOB '*[^0-9a-fA-F]*'),
  config_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  PRIMARY KEY (campaign_id, goal_id),
  FOREIGN KEY (campaign_id, goal_id)
    REFERENCES research_campaign(id, goal_id)
);

CREATE TRIGGER research_campaign_config_no_update
BEFORE UPDATE ON research_campaign_config
BEGIN SELECT RAISE(ABORT, 'research campaign config is immutable'); END;
CREATE TRIGGER research_campaign_config_no_delete
BEFORE DELETE ON research_campaign_config
BEGIN SELECT RAISE(ABORT, 'research campaign config is immutable'); END;

CREATE TABLE research_source (
  id TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL,
  goal_id TEXT NOT NULL REFERENCES goal(id),
  canonical_uri TEXT NOT NULL CHECK (length(trim(canonical_uri)) > 0),
  title TEXT NOT NULL CHECK (length(trim(title)) > 0),
  source_type TEXT NOT NULL CHECK (length(trim(source_type)) > 0),
  content_sha256 TEXT NOT NULL
    CHECK (length(content_sha256) = 64
       AND content_sha256 NOT GLOB '*[^0-9a-fA-F]*'),
  verification_status TEXT NOT NULL
    CHECK (verification_status IN ('verified','unverified','excluded')),
  verifier TEXT,
  verification_method TEXT,
  verifier_provenance_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  UNIQUE (goal_id, canonical_uri),
  UNIQUE (id, goal_id),
  FOREIGN KEY (campaign_id, goal_id)
    REFERENCES research_campaign(id, goal_id),
  CHECK (verification_status <> 'verified'
     OR (length(trim(COALESCE(verifier, ''))) > 0
     AND length(trim(COALESCE(verification_method, ''))) > 0))
);

CREATE TRIGGER research_source_no_update
BEFORE UPDATE ON research_source
BEGIN SELECT RAISE(ABORT, 'research sources are append-only'); END;
CREATE TRIGGER research_source_no_delete
BEFORE DELETE ON research_source
BEGIN SELECT RAISE(ABORT, 'research sources are append-only'); END;
CREATE TRIGGER research_source_uri_valid
BEFORE INSERT ON research_source
WHEN (NEW.canonical_uri NOT GLOB 'http://*'
   AND NEW.canonical_uri NOT GLOB 'https://*')
  OR instr(NEW.canonical_uri, ' ') > 0
  OR instr(NEW.canonical_uri, '#') > 0
BEGIN SELECT RAISE(ABORT, 'research source URI is not a canonical HTTP(S) URI'); END;

CREATE TABLE research_claim (
  id TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL,
  goal_id TEXT NOT NULL REFERENCES goal(id),
  text TEXT NOT NULL CHECK (length(trim(text)) > 0),
  claim_class TEXT NOT NULL
    CHECK (claim_class IN ('fact','inference','assumption','target')),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  UNIQUE (id, goal_id),
  FOREIGN KEY (campaign_id, goal_id)
    REFERENCES research_campaign(id, goal_id)
);

CREATE TRIGGER research_claim_no_update
BEFORE UPDATE ON research_claim
BEGIN SELECT RAISE(ABORT, 'research claims are append-only'); END;
CREATE TRIGGER research_claim_no_delete
BEFORE DELETE ON research_claim
BEGIN SELECT RAISE(ABORT, 'research claims are append-only'); END;

CREATE TABLE research_claim_source (
  claim_id TEXT NOT NULL,
  source_id TEXT NOT NULL,
  goal_id TEXT NOT NULL REFERENCES goal(id),
  relation TEXT NOT NULL DEFAULT 'supports'
    CHECK (relation IN ('supports','contradicts','context')),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  PRIMARY KEY (claim_id, source_id),
  FOREIGN KEY (claim_id, goal_id)
    REFERENCES research_claim(id, goal_id),
  FOREIGN KEY (source_id, goal_id)
    REFERENCES research_source(id, goal_id)
);

-- The triggers are redundant with the composite FKs when PRAGMA
-- foreign_keys=ON, but keep the invariant true for raw SQLite connections
-- that forgot to enable the per-connection pragma.
CREATE TRIGGER research_claim_source_owner
BEFORE INSERT ON research_claim_source
WHEN NOT EXISTS (
  SELECT 1 FROM research_claim c
   WHERE c.id=NEW.claim_id AND c.goal_id=NEW.goal_id
) OR NOT EXISTS (
  SELECT 1 FROM research_source s
   WHERE s.id=NEW.source_id AND s.goal_id=NEW.goal_id
)
BEGIN SELECT RAISE(ABORT, 'research claim/source goal mismatch'); END;
CREATE TRIGGER research_claim_source_no_update
BEFORE UPDATE ON research_claim_source
BEGIN SELECT RAISE(ABORT, 'research claim/source links are append-only'); END;
CREATE TRIGGER research_claim_source_no_delete
BEFORE DELETE ON research_claim_source
BEGIN SELECT RAISE(ABORT, 'research claim/source links are append-only'); END;

CREATE TABLE research_artifact (
  id TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL,
  goal_id TEXT NOT NULL REFERENCES goal(id),
  kind TEXT NOT NULL CHECK (length(trim(kind)) > 0),
  artifact_name TEXT NOT NULL DEFAULT '',
  version INTEGER NOT NULL CHECK (version > 0),
  content_sha256 TEXT NOT NULL
    CHECK (length(content_sha256) = 64
       AND content_sha256 NOT GLOB '*[^0-9a-fA-F]*'),
  storage_path TEXT NOT NULL CHECK (length(trim(storage_path)) > 0),
  claim_refs_json TEXT NOT NULL DEFAULT '[]',
  producer TEXT NOT NULL DEFAULT 'system',
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  UNIQUE (goal_id, kind, version),
  UNIQUE (id, goal_id),
  FOREIGN KEY (campaign_id, goal_id)
    REFERENCES research_campaign(id, goal_id)
);

CREATE TRIGGER research_artifact_no_update
BEFORE UPDATE ON research_artifact
BEGIN SELECT RAISE(ABORT, 'research artifacts are append-only'); END;
CREATE TRIGGER research_artifact_no_delete
BEFORE DELETE ON research_artifact
BEGIN SELECT RAISE(ABORT, 'research artifacts are append-only'); END;

CREATE TABLE research_artifact_claim (
  artifact_id TEXT NOT NULL,
  claim_id TEXT NOT NULL,
  goal_id TEXT NOT NULL REFERENCES goal(id),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  PRIMARY KEY (artifact_id, claim_id),
  FOREIGN KEY (artifact_id, goal_id)
    REFERENCES research_artifact(id, goal_id),
  FOREIGN KEY (claim_id, goal_id)
    REFERENCES research_claim(id, goal_id)
);

CREATE TRIGGER research_artifact_claim_owner
BEFORE INSERT ON research_artifact_claim
WHEN NOT EXISTS (
  SELECT 1 FROM research_artifact a
   WHERE a.id=NEW.artifact_id AND a.goal_id=NEW.goal_id
) OR NOT EXISTS (
  SELECT 1 FROM research_claim c
   WHERE c.id=NEW.claim_id AND c.goal_id=NEW.goal_id
)
BEGIN SELECT RAISE(ABORT, 'research artifact/claim goal mismatch'); END;
CREATE TRIGGER research_artifact_claim_no_update
BEFORE UPDATE ON research_artifact_claim
BEGIN SELECT RAISE(ABORT, 'research artifact/claim links are append-only'); END;
CREATE TRIGGER research_artifact_claim_no_delete
BEFORE DELETE ON research_artifact_claim
BEGIN SELECT RAISE(ABORT, 'research artifact/claim links are append-only'); END;

CREATE TABLE research_evaluation (
  id TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL,
  goal_id TEXT NOT NULL REFERENCES goal(id),
  evaluation_version INTEGER NOT NULL DEFAULT 1 CHECK (evaluation_version > 0),
  result TEXT NOT NULL CHECK (result IN ('pass','pass_with_limits','fail')),
  artifact_chain_hash TEXT NOT NULL
    CHECK (length(artifact_chain_hash) = 64
       AND artifact_chain_hash NOT GLOB '*[^0-9a-fA-F]*'),
  reasons_json TEXT NOT NULL DEFAULT '[]',
  limitations_json TEXT NOT NULL DEFAULT '[]',
  details_json TEXT NOT NULL DEFAULT '{}',
  method TEXT NOT NULL DEFAULT 'agentos.research.deterministic.v1',
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  UNIQUE (campaign_id, evaluation_version),
  FOREIGN KEY (campaign_id, goal_id)
    REFERENCES research_campaign(id, goal_id)
);

CREATE TRIGGER research_evaluation_no_update
BEFORE UPDATE ON research_evaluation
BEGIN SELECT RAISE(ABORT, 'research evaluations are append-only'); END;
CREATE TRIGGER research_evaluation_no_delete
BEFORE DELETE ON research_evaluation
BEGIN SELECT RAISE(ABORT, 'research evaluations are append-only'); END;

CREATE INDEX idx_research_source_goal ON research_source(goal_id);
-- SQLite's default TEXT uniqueness is case-sensitive.  Canonical URI host
-- variants must not create duplicate sources within one research goal.
CREATE UNIQUE INDEX idx_research_source_goal_uri_nocase
  ON research_source(goal_id, canonical_uri COLLATE NOCASE);
CREATE INDEX idx_research_claim_goal ON research_claim(goal_id);
CREATE INDEX idx_research_artifact_goal ON research_artifact(goal_id);
CREATE INDEX idx_research_evaluation_goal ON research_evaluation(goal_id);
