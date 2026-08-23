-- 0008z_preserve_campaigns_r9.sql — pre-R6 recovery snapshot.
--
-- This migration is deliberately ordered between 0008 and 0009.  It also
-- runs for databases that already recorded 0009/0010, because the migration
-- runner applies any newly introduced migration whose marker is absent.  The
-- table is an immutable recovery archive; it is never used as the canonical
-- source after 0011 has rebuilt campaign.

CREATE TABLE IF NOT EXISTS campaign_legacy_r9 (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  manifest_json TEXT NOT NULL,
  manifest_sha256 TEXT NOT NULL,
  baseline_ref TEXT NOT NULL,
  primary_metric TEXT NOT NULL,
  budget INTEGER NOT NULL,
  created_at TEXT NOT NULL
);

-- A partially applied historical 0009 may have dropped campaign before the
-- rename.  Create an empty common-shape table so this snapshot remains
-- forward-compatible; 0011 reconstructs missing rows from experiments.
CREATE TABLE IF NOT EXISTS campaign (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  manifest_json TEXT NOT NULL,
  manifest_sha256 TEXT NOT NULL,
  baseline_ref TEXT NOT NULL,
  primary_metric TEXT NOT NULL,
  budget INTEGER NOT NULL,
  created_at TEXT NOT NULL
);

INSERT OR IGNORE INTO campaign_legacy_r9(
  id, name, manifest_json, manifest_sha256, baseline_ref,
  primary_metric, budget, created_at)
SELECT id, name, manifest_json, manifest_sha256, baseline_ref,
       primary_metric, budget, created_at
  FROM campaign;

CREATE TRIGGER IF NOT EXISTS campaign_legacy_r9_no_update
BEFORE UPDATE ON campaign_legacy_r9
BEGIN SELECT RAISE(ABORT, 'campaign recovery archive is immutable'); END;
CREATE TRIGGER IF NOT EXISTS campaign_legacy_r9_no_delete
BEFORE DELETE ON campaign_legacy_r9
BEGIN SELECT RAISE(ABORT, 'campaign recovery archive is immutable'); END;
