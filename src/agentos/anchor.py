"""Off-host audit anchor export/verify (ROADMAP "ближний круг" item 3).

The in-DB `audit_anchor` row and its same-host mirror file
(`audit_anchor.head`, maintained transactionally by journal.py) give tamper
EVIDENCE, but an attacker (or disk loss) can destroy DB and mirror together.
This module closes that hole one step further: it exports a small, self-checking,
provider-neutral JSON bundle with the chain head so it can be pushed off-host
(git repo, object storage, any synced folder) by ANY scheduler — no network or
heavyweight deps in core (ADR-0001).

Export is fail-loudly: if the full hash chain does not verify at export time,
nothing is written. The bundle contains ONLY public digests and counters —
never payloads, secrets, or memory contents.

    anchor-export --db DIR --out PATH   -> agentos.anchor-export/v1 bundle
    anchor-verify --bundle PATH --db DIR -> independent re-check of the bundle

Verification recomputes three independent facts:
  struct_ok     — bundle integrity (state_sha256 matches canonical state)
  hist_ok       — the audit_event row AT the exported seq still hashes to the
                  exported head digest (true historical binding, works even if
                  the checked DB has legitimately moved ahead)
  chain_ok      — full_chain_check() of the checked DB right now
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from .ids import canonical_json, sha256_text
from .journal import Journal

SCHEMA = "agentos.anchor-export/v1"


class AnchorExportError(RuntimeError):
    """Raised when export must fail loudly (broken chain / empty journal)."""


def _state(db) -> dict:
    last = db.conn.execute(
        "SELECT * FROM audit_event ORDER BY seq DESC LIMIT 1").fetchone()
    if last is None:
        raise AnchorExportError("no audit events to anchor (empty journal)")
    ok, bad = Journal(db).full_chain_check()
    if not ok:
        raise AnchorExportError(
            f"audit chain fails verification at seq {bad}; refusing to "
            f"export a possibly-tampered state")
    return {"last_seq": int(last["seq"]),
            "head_digest": Journal(db).digest_of_row(last)}


def export_anchor(db, out_path: str | Path, *,
                  now_iso: str | None = None) -> dict:
    """Build and write an off-host anchor bundle for `db`. Returns the bundle.

    `now_iso` (ISO-8601 UTC string) exists for deterministic tests; when None
    the current UTC time is used."""
    state = _state(db)
    if now_iso is None:
        from datetime import datetime, timezone
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    bundle = {
        "schema": SCHEMA,
        "exported_at": now_iso,
        "source_db": Path(db.path).name,
        "state": state,
        "state_sha256": sha256_text(canonical_json(state)),
    }
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    return bundle


def load_bundle(bundle_path: str | Path) -> dict:
    return json.loads(Path(bundle_path).read_text(encoding="utf-8"))


def verify_bundle(bundle_path: str | Path, db) -> dict:
    """Verify a previously exported bundle against `db` (any copy)."""
    b = load_bundle(bundle_path)
    report: dict = {
        "schema": SCHEMA,
        "schema_ok": False, "struct_ok": False, "hist_ok": False,
        "chain_ok": False, "first_bad_seq": None, "ok": False,
    }
    if not isinstance(b, dict):
        return report
    report["schema_ok"] = b.get("schema") == SCHEMA
    report["bundle_exported_at"] = b.get("exported_at")
    state = b.get("state") or {}
    try:
        expected_digest = sha256_text(canonical_json(state))
        has_state = isinstance(state.get("last_seq"), int) and \
            isinstance(state.get("head_digest"), str)
    except TypeError:
        return report
    if not has_state:
        return report
    report["struct_ok"] = report["schema_ok"] and \
        isinstance(state.get("head_digest"), str) and \
        b.get("state_sha256") == expected_digest
    # historical binding: row at exported seq must still hash identically
    row = db.conn.execute(
        "SELECT * FROM audit_event WHERE seq=?", (state["last_seq"],)).fetchone()
    if row is not None:
        actual = Journal(db).digest_of_row(row)
        report["hist_ok"] = (actual == state["head_digest"])
        tip = db.conn.execute(
            "SELECT MAX(seq) AS m FROM audit_event").fetchone()["m"]
        report["db_last_seq"] = tip
        report["db_ahead_by"] = max(0, int(tip) - int(state["last_seq"]))
    else:
        report["hist_ok"] = False
        report["note"] = "exported seq absent from checked DB"
    ok_now, bad = Journal(db).full_chain_check()
    report["chain_ok"] = ok_now
    report["first_bad_seq"] = bad
    report["ok"] = bool(report["struct_ok"] and report["hist_ok"]
                        and report["chain_ok"])
    return report


# -- off-host mirroring (ROADMAP item 3, transport step) -------------------------

MIRROR_HISTORY = "history.ndjson"
MIRROR_LATEST = "latest.json"


def _write_atomic(path: Path, data: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(data, encoding="utf-8")
    os.replace(tmp, path)


def mirror_anchor(db, dest_dir: str | Path, *,
                  now_iso: str | None = None) -> dict:
    """Idempotent off-host mirror of the audit anchor head.

    Layout inside `dest_dir` (typically a git repo or a synced folder on
    another volume/host):
      anchors/<seq>-<head16>.json   content-addressed, immutable once written
      latest.json                   pointer to the newest mirrored anchor
      history.ndjson                append-only line per NEW mirrored anchor

    Determinism/idempotency: the bundle name is (last_seq, head_digest)-based,
    so re-running with an unchanged state writes nothing new; the first
    written bundle for a given state wins and is never silently replaced.
    Fail-loudly: a broken audit chain raises before anything is touched.
    """
    dest = Path(dest_dir)
    anchors_dir = dest / "anchors"
    pending = dest / ".pending.json"
    bundle = export_anchor(db, pending, now_iso=now_iso)
    # export succeeded (chain verified); place it content-addressed
    state = bundle["state"]
    seq = int(state["last_seq"])
    head = state["head_digest"]
    name = f"{seq:012d}-{head[:16]}.json"
    target = anchors_dir / name
    file_sha = hashlib.sha256(pending.read_bytes()).hexdigest()
    changed = True
    if target.exists():
        existing_bytes = target.read_bytes()
        existing_sha = hashlib.sha256(existing_bytes).hexdigest()
        if existing_sha == file_sha:
            changed = False          # byte-identical re-export
        else:
            try:
                existing_state_sha = json.loads(
                    existing_bytes.decode("utf-8"))["state_sha256"]
            except Exception:    # noqa: BLE001 — unreadable entry = conflict
                existing_state_sha = None
            if existing_state_sha == bundle["state_sha256"]:
                # same state, different timestamp: keep the FIRST immutable
                # bundle and report its digest
                changed = False
                file_sha = existing_sha
            else:
                # same (seq, head) but a different state: refusing to
                # overwrite an immutable mirror entry fails loudly
                pending.unlink(missing_ok=True)
                raise AnchorExportError(
                    f"mirror entry {name} already exists with a different "
                    f"state for the same chain head")
    else:
        anchors_dir.mkdir(parents=True, exist_ok=True)
        os.replace(pending, target)
    pending.unlink(missing_ok=True)

    latest = {"schema": SCHEMA, "anchor_file": f"anchors/{name}",
              "bundle_sha256": file_sha, "state": state,
              "mirrored_at": bundle["exported_at"]}
    _write_atomic(dest / MIRROR_LATEST,
                  json.dumps(latest, indent=2, sort_keys=True) + "\n")

    if changed:
        line = canonical_json({
            "mirrored_at": bundle["exported_at"],
            "last_seq": seq,
            "head_digest": head,
            "anchor_file": f"anchors/{name}",
            "bundle_sha256": file_sha,
        }) + "\n"
        with open(dest / MIRROR_HISTORY, "a", encoding="utf-8") as f:
            f.write(line)

    return {"status": "ok", "changed": changed, "anchor_file": f"anchors/{name}",
            "last_seq": seq, "head_digest": head,
            "bundle_sha256": file_sha, "dest": str(dest),
            "latest": str(dest / MIRROR_LATEST),
            "history": str(dest / MIRROR_HISTORY)}
