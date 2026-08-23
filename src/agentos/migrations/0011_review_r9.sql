-- 0011_review_r9.sql — forward recovery and DB owner enforcement.
--
-- 0009/0010 are already shipped and may have run on user databases.  This
-- migration is therefore additive/reconstructive: campaign rows are copied
-- into a fresh immutable table, missing rows are rebuilt from append-only
-- experiment evidence, and every ambiguous owner is assigned to an explicit
-- cancelled quarantine goal.  Existing experiment rows are not updated.

INSERT OR IGNORE INTO goal(id, concept_text, status)
VALUES ('goal_MIGRATION_QUARANTINE',
        'ambiguous campaign ownership recovered during schema migration',
        'CANCELLED');

CREATE TABLE campaign_r9 (
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

-- At this point 0009 has established campaign.goal_id on every supported
-- upgrade path.  Preserve a real canonical owner.  The special
-- goal_MIGRATED value is only a historical placeholder, so replace it with a
-- unique valid owner evidenced by experiments when possible; otherwise keep
-- the explicit placeholder rather than silently inventing ownership.
INSERT INTO campaign_r9(id, goal_id, name, manifest_json, manifest_sha256,
                        baseline_ref, primary_metric, budget, created_at)
SELECT c.id,
       CASE
         WHEN c.goal_id <> 'goal_MIGRATED'
          AND EXISTS (SELECT 1 FROM goal g WHERE g.id=c.goal_id)
         THEN c.goal_id
         ELSE COALESCE((
           SELECT CASE WHEN COUNT(DISTINCT e.goal_id) = 1
                       THEN MAX(e.goal_id) END
             FROM experiment e JOIN goal eg ON eg.id=e.goal_id
            WHERE e.campaign_id=c.id AND e.goal_id IS NOT NULL
         ), (SELECT g.id FROM goal g WHERE g.id=c.goal_id),
            'goal_MIGRATION_QUARANTINE')
       END,
       c.name, c.manifest_json, c.manifest_sha256, c.baseline_ref,
       c.primary_metric, c.budget, c.created_at
  FROM campaign c;

-- campaign history may have been dropped by the old destructive 0009.  The
-- recovery snapshot catches the 0008 path; this branch handles rows that are
-- present only in that archive.
INSERT OR IGNORE INTO campaign_r9(id, goal_id, name, manifest_json,
                                  manifest_sha256, baseline_ref,
                                  primary_metric, budget, created_at)
SELECT l.id,
       COALESCE((
         SELECT CASE WHEN COUNT(DISTINCT e.goal_id) = 1
                     THEN MAX(e.goal_id) END
           FROM experiment e JOIN goal eg ON eg.id=e.goal_id
          WHERE e.campaign_id=l.id AND e.goal_id IS NOT NULL
       ), 'goal_MIGRATION_QUARANTINE'),
       l.name, l.manifest_json, l.manifest_sha256, l.baseline_ref,
       l.primary_metric, l.budget, l.created_at
  FROM campaign_legacy_r9 l;

-- If both canonical campaign and the pre-0009 snapshot are gone, rebuild the
-- minimum campaign record from the immutable experiment evidence.
INSERT OR IGNORE INTO campaign_r9(id, goal_id, name, manifest_json,
                                  manifest_sha256, baseline_ref,
                                  primary_metric, budget, created_at)
SELECT e.campaign_id,
       COALESCE((
         SELECT CASE WHEN COUNT(DISTINCT e2.goal_id) = 1
                     THEN MAX(e2.goal_id) END
           FROM experiment e2 JOIN goal eg ON eg.id=e2.goal_id
          WHERE e2.campaign_id=e.campaign_id AND e2.goal_id IS NOT NULL
       ), 'goal_MIGRATION_QUARANTINE'),
       'recovered-' || e.campaign_id, '{}', '',
       MIN(e.baseline_ref), MIN(e.primary_metric), 0,
       MIN(e.created_at)
  FROM experiment e
 WHERE NOT EXISTS (SELECT 1 FROM campaign_r9 c WHERE c.id=e.campaign_id)
 GROUP BY e.campaign_id;

DROP TRIGGER IF EXISTS experiment_goal_owner;
DROP TRIGGER IF EXISTS campaign_no_update;
DROP TRIGGER IF EXISTS campaign_no_delete;
DROP INDEX IF EXISTS idx_campaign_goal;
DROP TABLE campaign;
ALTER TABLE campaign_r9 RENAME TO campaign;

CREATE TRIGGER campaign_no_update BEFORE UPDATE ON campaign
BEGIN SELECT RAISE(ABORT, 'campaign is immutable'); END;
CREATE TRIGGER campaign_no_delete BEFORE DELETE ON campaign
BEGIN SELECT RAISE(ABORT, 'campaign is immutable'); END;
CREATE INDEX idx_campaign_goal ON campaign(goal_id);

-- Historic NULL owners remain immutable evidence and are projected through
-- campaign.goal_id.  New rows must always identify an existing campaign and
-- exactly its owner; NULL, unknown, and mismatched inserts are rejected here
-- in SQLite, not merely by the Python service.
CREATE TRIGGER experiment_goal_owner BEFORE INSERT ON experiment
WHEN NEW.goal_id IS NULL
  OR NOT EXISTS (SELECT 1 FROM campaign c WHERE c.id=NEW.campaign_id)
  OR NOT EXISTS (SELECT 1 FROM campaign c
                  WHERE c.id=NEW.campaign_id AND c.goal_id=NEW.goal_id)
BEGIN SELECT RAISE(ABORT, 'experiment goal must match campaign owner'); END;
