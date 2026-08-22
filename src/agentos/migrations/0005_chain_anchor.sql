-- 0005_chain_anchor.sql — tamper-evidence head anchor (F-P1-10 extension).
-- Stores the digest of the newest audit row, updated in the same transaction
-- as the append; full_chain_check recomputes and compares.
CREATE TABLE audit_anchor (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  head_digest TEXT,
  last_seq INTEGER
);
INSERT INTO audit_anchor(id, head_digest, last_seq)
SELECT 1,
       (SELECT prev_event_sha256 FROM audit_event ORDER BY seq DESC LIMIT 1),
       (SELECT seq FROM audit_event ORDER BY seq DESC LIMIT 1);
