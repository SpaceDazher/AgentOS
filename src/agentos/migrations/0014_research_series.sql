-- 0014_research_series.sql — stable research identity and revision lineage.
--
-- The original research_campaign table is immutable and deliberately remains
-- untouched.  This additive table gives a host-controlled key a durable
-- revision history without rewriting already-recorded campaign evidence.

CREATE TABLE research_series (
  id TEXT PRIMARY KEY,
  research_key TEXT NOT NULL,
  revision INTEGER NOT NULL CHECK (revision > 0),
  campaign_id TEXT NOT NULL,
  goal_id TEXT NOT NULL REFERENCES goal(id),
  topic TEXT NOT NULL CHECK (length(trim(topic)) > 0),
  manifest_sha256 TEXT NOT NULL
    CHECK (length(manifest_sha256) = 64
       AND manifest_sha256 NOT GLOB '*[^0-9a-fA-F]*'),
  supersedes_campaign_id TEXT REFERENCES research_campaign(id),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  UNIQUE (research_key, revision),
  UNIQUE (campaign_id),
  FOREIGN KEY (campaign_id, goal_id)
    REFERENCES research_campaign(id, goal_id)
);

CREATE INDEX idx_research_series_key
  ON research_series(research_key, revision DESC);
CREATE INDEX idx_research_series_key_manifest
  ON research_series(research_key, manifest_sha256);
CREATE INDEX idx_research_series_campaign
  ON research_series(campaign_id);

CREATE TRIGGER research_series_no_update
BEFORE UPDATE ON research_series
BEGIN SELECT RAISE(ABORT, 'research series is append-only'); END;
CREATE TRIGGER research_series_no_delete
BEFORE DELETE ON research_series
BEGIN SELECT RAISE(ABORT, 'research series is append-only'); END;

-- Short-lived host-side coordination rows prevent two callers from creating
-- goals while they race to establish the first revision for one key.  This is
-- a reservation table, not a decision table: rows are deleted after the
-- campaign transaction commits or rolls back.
CREATE TABLE research_series_lock (
  research_key TEXT PRIMARY KEY,
  owner_token TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX idx_research_series_lock_created
  ON research_series_lock(created_at);
