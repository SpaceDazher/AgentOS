-- 0006_fence_sink.sql — P1: sink-side fence validation.
-- fence_sink_state tracks the highest fence token each sink (workspace root)
-- has accepted; handlers must reject tokens <= the stored value for the sink
-- (stale writer protection at the SINK, not just the gateway).
CREATE TABLE fence_sink_state (
  sink TEXT PRIMARY KEY,          -- canonical sink id (e.g. workspace root path)
  last_accepted_fence INTEGER NOT NULL,
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

-- P1: registry immutability enforced at the DB layer — tool_contract rows are
-- append-only. UPDATE of enforcement-relevant columns is refused outright;
-- DELETE too. New versions are new rows.
CREATE TRIGGER tool_contract_no_update
BEFORE UPDATE ON tool_contract
BEGIN
  SELECT RAISE(ABORT, 'tool_contract is append-only: UPDATE refused (register a new version instead)');
END;

CREATE TRIGGER tool_contract_no_delete
BEFORE DELETE ON tool_contract
BEGIN
  SELECT RAISE(ABORT, 'tool_contract is append-only: DELETE refused');
END;
