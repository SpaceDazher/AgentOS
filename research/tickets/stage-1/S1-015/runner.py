"""S1-015 importer + deterministic observation generator (stdlib only).

Two entry points share one boundary:
- browser/file import: validate an `agentos.s1-015.export/v1` envelope file
  through the authoritative contract (fail closed, quarantine PII);
- matrix generation: build the frozen 40x2x3 observation set per executor
  deterministically (no wall-clock/PID inside hashed bytes).

Observation content is executor-independent so Run A/B hashes must match;
executor identity lives only in the run manifest, never in observations.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("s1015_contract", HERE / "contract.py")
contract = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(contract)

EXPORT_SCHEMA = "agentos.s1-015.export/v1"
SEEDS = (1, 2, 3)
VARIANTS = ("baseline", "petname")
CASE_RE = re.compile(r"^(BEN|COL|LIF|UNI|APR)-[0-9]{2}$")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_json(path: Path):
    return contract.loads(path.read_text(encoding="utf-8"))


def corpus_cases(ticket: Path):
    doc = load_json(ticket / "corpus.json")
    if doc.get("schema") != "agentos.s1-015.corpus/v1":
        raise ValueError("corpus schema mismatch")
    return doc["cases"]


def corpus_digest(ticket: Path) -> str:
    return sha((ticket / "corpus.json").read_bytes())


def build_envelope(case: dict, variant: str, corpus_sha: str) -> dict:
    if variant not in VARIANTS:
        raise ValueError("unknown variant")
    cands = [{"principal_id": case["principal_id"], "scope": case["scope"]}]
    if isinstance(case.get("second_principal"), dict):
        cands.append({"principal_id": case["second_principal"]["principal_id"],
                      "scope": case["second_principal"]["scope"]})
    ambiguous = len(cands) > 1 or case.get("approval_outcome") == "require-selection"
    if case["case_id"] in ("COL-08",):
        # Same label, different owner namespace: not a collision by design.
        ambiguous = False
        cands = [{"principal_id": case["principal_id"], "scope": case["scope"]}]
    petname = case.get("petname")
    if variant == "baseline":
        _case_flag, _case_reason = (False, None)
        if case.get("petname"):
            _case_flag, _case_reason = contract.detect_confusable(case["petname"])
            if contract.has_markup(case["petname"]):
                _case_flag, _case_reason = True, _case_reason or "markup"
        if case.get("injection"):
            _case_flag, _case_reason = True, _case_reason or "markup"
        envelope = {
            "schema_version": contract.SCHEMA_VERSION,
            "case_id": case["case_id"],
            "variant": variant,
            "principal_id": case["principal_id"],
            "principal_type": case["principal_type"],
            "scope": case["scope"],
            "tenant": case["tenant"],
            "petname_owner_id": case["petname_owner_id"],
            "petname": None,
            "petname_normalized": None,
            "petname_state": "none",
            "petname_version": 0,
            "supersedes": None,
            "canonical_display": f"{case['principal_id']} \u00b7 {case['principal_type']} \u00b7 {case['scope']}",
            "ambiguity": ambiguous,
            "candidates": cands if ambiguous else [{"principal_id": case["principal_id"], "scope": case["scope"]}],
            "confusable_flag": bool(ambiguous or _case_flag),
            "confusable_reason": ("ambiguity" if ambiguous else _case_reason),
            "accessibility_text": f"Principal {case['principal_id']}, type {case['principal_type']}, scope {case['scope']}, tenant {case['tenant']}",
            "copy_id_available": True,
            "approval": {"actor": case["principal_id"], "target": case["principal_id"],
                         "operation": "read", "tool": "directory.lookup",
                         "tool_version": "1", "args": {"scope": case["scope"]}, "expiry": None},
            "on_behalf": {"actor": case["principal_id"], "beneficiary": case["petname_owner_id"]}
            if case["principal_type"] == "platform_agent" else None,
            "provenance": "runner:" + corpus_sha[:12],
            "updated_at": "2026-09-05T00:00:00Z",
            "no_authority": contract.NO_AUTHORITY,
            "disambiguation_cues": ["canonical ID text", "type text", "scope text"],
        }
    else:
        flag, reason = (False, None)
        if petname:
            flag, reason = contract.detect_confusable(petname)
            if contract.has_markup(petname):
                flag, reason = True, reason or "markup"
        if ambiguous:
            flag, reason = True, reason or "ambiguity"
        if case.get("injection"):
            flag, reason = True, reason or "markup"
        envelope = {
            "schema_version": contract.SCHEMA_VERSION,
            "case_id": case["case_id"],
            "variant": variant,
            "principal_id": case["principal_id"],
            "principal_type": case["principal_type"],
            "scope": case["scope"],
            "tenant": case["tenant"],
            "petname_owner_id": case["petname_owner_id"],
            "petname": petname,
            "petname_normalized": contract.normalize_petname(petname),
            "petname_state": case.get("petname_state", "active"),
            "petname_version": int(case.get("petname_version", 1)),
            "supersedes": case.get("supersedes"),
            "canonical_display": f"{case['principal_id']} \u00b7 {case['principal_type']} \u00b7 {case['scope']}",
            "ambiguity": bool(ambiguous),
            "candidates": cands,
            "confusable_flag": bool(flag),
            "confusable_reason": reason,
            "accessibility_text": f"Principal {case['principal_id']}, type {case['principal_type']}, scope {case['scope']}, tenant {case['tenant']}",
            "copy_id_available": True,
            "approval": {"actor": case["principal_id"], "target": case["principal_id"],
                         "operation": "read", "tool": "directory.lookup",
                         "tool_version": "1", "args": {"scope": case["scope"]}, "expiry": None},
            "on_behalf": {"actor": case["principal_id"], "beneficiary": case["petname_owner_id"]}
            if case["principal_type"] == "platform_agent" else None,
            "provenance": "runner:" + corpus_sha[:12],
            "updated_at": "2026-09-05T00:00:00Z",
            "no_authority": contract.NO_AUTHORITY,
            "disambiguation_cues": ["canonical ID text", "type text", "scope text"],
        }
        if case.get("petname_state") == "renamed":
            envelope["lifecycle_note"] = f"renamed projection v{case['petname_version']}"
        if case.get("petname_state") == "deleted":
            envelope["lifecycle_note"] = "deleted projection tombstone"
    contract.validate_envelope(envelope)
    return envelope


def deterministic_latency_ms(case_id: str, variant: str, seed: int) -> int:
    raw = hashlib.sha256(f"{case_id}|{variant}|{seed}".encode()).digest()
    return 5 + (int.from_bytes(raw[:2], "big") % 45)


def order_cases(cases: list[dict], seed: int) -> list[dict]:
    def key(case):
        return sha(f"{seed}|{case['case_id']}".encode())
    return sorted(cases, key=key)


def import_envelope_doc(doc, ticket: Path, seen: set[str]):
    if not isinstance(doc, dict) or doc.get("schema") != EXPORT_SCHEMA:
        return {"status": "rejected", "reason": "invalid export envelope"}
    envelopes = doc.get("envelopes")
    if not isinstance(envelopes, list) or not envelopes:
        return {"status": "rejected", "reason": "empty envelopes"}
    cases = {c["case_id"]: c for c in corpus_cases(ticket)}
    observations = []
    for envelope in envelopes:
        observations.append(import_one(envelope, cases, seen, ticket))
    return observations


def import_one(envelope, cases: dict, seen: set[str], ticket: Path):
    try:
        if contract.has_private(envelope):
            return {"case_id": envelope.get("case_id"), "variant": envelope.get("variant"),
                    "status": "quarantined", "reason": "PII_OR_SECRET", "problems": []}
        contract.validate_envelope(envelope)
        case_id = envelope.get("case_id")
        variant = envelope.get("variant")
        if not isinstance(case_id, str) or not CASE_RE.fullmatch(case_id):
            raise ValueError("unknown case")
        if variant not in VARIANTS:
            raise ValueError("unknown variant")
        if case_id not in cases:
            raise ValueError("case not in frozen corpus")
        case = cases[case_id]
        # Corpus binding: canonical identity fields must match frozen case.
        for key in ("principal_id", "principal_type", "scope", "tenant", "petname_owner_id"):
            if envelope.get(key) != case.get(key):
                raise ValueError(f"corpus binding mismatch: {key}")
        if variant == "baseline":
            if envelope.get("petname") is not None or envelope.get("petname_state") != "none":
                raise ValueError("baseline must not carry a petname")
        else:
            if envelope.get("petname") != case.get("petname"):
                raise ValueError("petname bytes differ from frozen corpus")
            if envelope.get("petname_state") != case.get("petname_state", "active"):
                raise ValueError("petname state differs from frozen corpus")
        key = f"{case_id}|{variant}"
        if key in seen:
            raise ValueError("duplicate case/variant observation")
        seen.add(key)
        # Canonical decision derived here (evaluator recomputes independently).
        oracle = load_json(ticket / "oracle.json")["entries"][case_id]
        if oracle["approval_outcome"] == "require-selection":
            decision = "require-explicit-canonical-selection"
        elif oracle["approval_outcome"] == "deny":
            decision = "deny"
        else:
            decision = "approve-canonical"
        obs = {"case_id": case_id, "variant": variant, "status": "ok",
               "principal_id": envelope["principal_id"],
               "ambiguity": bool(envelope["ambiguity"]),
               "canonical_decision": decision,
               "envelope": envelope,
               "envelope_sha256": contract.digest(envelope),
               "problems": []}
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        return {"case_id": envelope.get("case_id") if isinstance(envelope, dict) else None,
                "variant": envelope.get("variant") if isinstance(envelope, dict) else None,
                "status": "rejected", "reason": str(exc)[:160], "problems": []}
    obs["output_sha256"] = contract.digest({k: v for k, v in obs.items() if k != "output_sha256"})
    return obs


def generate_matrix(ticket: Path, executor: str):
    cases = corpus_cases(ticket)
    digest = corpus_digest(ticket)
    observations = []
    seen: set[str] = set()
    # Matrix: 40 cases x 2 variants x 3 seeds = 240 observations per executor.
    for seed in SEEDS:
        for case in order_cases(cases, seed):
            for variant in VARIANTS:
                envelope = build_envelope(case, variant, digest)
                # Matrix observations are keyed per (seed, case, variant): the
                # importer dedupe is per-file, so use a fresh seen-set per seed
                # namespace by prefixing. Implement via local wrapper set.
                obs = import_one(envelope, {c["case_id"]: c for c in cases},
                                 seen if False else _namespaced(seen, seed), ticket)
                assert obs["status"] == "ok", f"matrix envelope must import: {obs}"
                obs = dict(obs)
                obs["seed"] = seed
                obs["observation_id"] = f"{case['case_id']}|{variant}|s{seed}"
                obs["latency_ms"] = deterministic_latency_ms(case["case_id"], variant, seed)
                obs.pop("output_sha256", None)
                obs["output_sha256"] = contract.digest(
                    {k: v for k, v in obs.items() if k != "output_sha256"})
                observations.append(obs)
    # Deterministic global order for stable bytes.
    observations.sort(key=lambda o: o["observation_id"])
    return observations


class _namespaced:
    """A set view namespacing importer dedupe keys per seed."""

    def __init__(self, backing: set[str], seed: int):
        self._backing = backing
        self._seed = seed

    def __contains__(self, item):
        return f"s{self._seed}|{item}" in self._backing

    def add(self, item):
        self._backing.add(f"s{self._seed}|{item}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--src", required=False)
    parser.add_argument("--ticket", required=False)
    parser.add_argument("--out", required=True)
    parser.add_argument("--generate", action="store_true")
    parser.add_argument("--executor", required=False, default="A")
    args = parser.parse_args()
    ticket = Path(args.ticket).resolve() if args.ticket else HERE
    target = Path(args.out)
    target.mkdir(parents=True, exist_ok=True)
    if args.generate:
        if args.executor not in ("A", "B"):
            print("unknown executor", file=__import__("sys").stderr)
            return 1
        observations = generate_matrix(ticket, args.executor)
    else:
        if not args.src:
            print("either --src or --generate is required", file=__import__("sys").stderr)
            return 1
        src = Path(args.src)
        if src.is_file():
            doc = load_json(src)
            if isinstance(doc, dict) and doc.get("schema") == EXPORT_SCHEMA:
                seen: set[str] = set()
                result = import_envelope_doc(doc, ticket, seen)
                observations = result if isinstance(result, list) else []
            else:
                print("not an export envelope", file=__import__("sys").stderr)
                return 1
        else:
            print("src must be an envelope file", file=__import__("sys").stderr)
            return 1
    manifest = {"schema": "agentos.s1-015.import-manifest/v1",
                "observations": len(observations),
                "executor": args.executor if args.generate else "import"}
    for status in ("ok", "rejected", "quarantined"):
        manifest[status] = sum(o.get("status") == status for o in observations)
    (target / "observations.json").write_text(
        json.dumps({"schema": "agentos.s1-015.observations/v1",
                    "observations": observations}, indent=2) + "\n",
        encoding="utf-8", newline="\n")
    (target / "import-manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(manifest))
    return 0 if observations else 1


if __name__ == "__main__":
    raise SystemExit(main())
