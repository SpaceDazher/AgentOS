"""Deterministic 48-case corpus generator for S1-018 (Phase A fixtures).

Single source of cases.json + oracle.json. Oracle entries are frozen by the
reference runner at build time; the evaluator recomputes everything from
corpus bytes. Re-running must be byte-identical. The final 864-cell matrix
runs in a later phase; this module only freezes fixtures.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

SA = {"tenant_id": "t-a", "workspace_id": "w-1", "goal_id": "g-1"}
SB = {"tenant_id": "t-b", "workspace_id": "w-9", "goal_id": "g-9"}


def op(op_name: str, **args) -> dict:
    return {"op": op_name, "args": args}


def case(case_id: str, klass: str, description: str, transitions: list,
         oracle: dict) -> dict:
    return {"case_id": case_id, "class": klass, "description": description,
            "inputs": {"scope": dict(SA), "arch_scope": "home"},
            "transitions": transitions, "oracle_hint": oracle}


def std_docs(*docs: str) -> dict:
    return {doc: f"alpha beta {doc} gamma" for doc in docs}


def SCENARIOS() -> list[dict]:
    cases = []
    # ---------------- MLS/member/key lifecycle (12) ----------------
    cases.append(case("ML-01", "mls_lifecycle", "create group and add member",
        [op("create_group", group="g1", members=["m1"]),
         op("add_member", group="g1", member="m2")],
        {"decision": "allow", "post_revoke_allow": 0}))
    cases.append(case("ML-02", "mls_lifecycle", "epoch commit rotates keys",
        [op("create_group", group="g1", members=["m1"]),
         op("commit_epoch", group="g1"),
         op("commit_epoch", group="g1")],
        {"decision": "allow", "epochs": [0, 1, 2]}))
    cases.append(case("ML-03", "mls_lifecycle", "remove then rejoin gets new keys",
        [op("create_group", group="g1", members=["m1"]),
         op("revoke", member="m1"),
         op("add_member", group="g1", member="m1")],
        {"decision": "allow", "post_revoke_allow": 0}))
    cases.append(case("ML-04", "mls_lifecycle", "duplicate add is idempotent",
        [op("create_group", group="g1", members=["m1"]),
         op("add_member", group="g1", member="m1")],
        {"decision": "allow"}))
    cases.append(case("ML-05", "mls_lifecycle", "unknown member denied",
        [op("create_group", group="g1", members=["m1"]),
         op("query_as", member="ghost", terms=["alpha"])],
        {"decision": "deny"}))
    cases.append(case("ML-06", "mls_lifecycle", "empty group denies all",
        [op("create_group", group="g1", members=[]),
         op("query_as", member="m1", terms=["alpha"])],
        {"decision": "deny"}))
    cases.append(case("ML-07", "mls_lifecycle", "multi-group membership",
        [op("create_group", group="g1", members=["m1"]),
         op("create_group", group="g2", members=["m1", "m2"])],
        {"decision": "allow"}))
    cases.append(case("ML-08", "mls_lifecycle", "exact scope binding enforced",
        [op("create_group", group="g1", members=["m1"]),
         op("submit", doc="d1", scope="foreign")],
        {"decision": "deny"}))
    cases.append(case("ML-09", "mls_lifecycle", "cross-scope read denied",
        [op("create_group", group="g1", members=["m1"]),
         op("submit", doc="d1"),
         op("query_foreign", member="m1", scope="foreign")],
        {"decision": "deny", "cross_scope_read": 0}))
    cases.append(case("ML-10", "mls_lifecycle", "submit then query roundtrip",
        [op("create_group", group="g1", members=["m1"]),
         op("submit", doc="d1"),
         op("build_index", partition="p1"),
         op("query_as", member="m1", terms=["alpha"])],
        {"decision": "allow"}))
    cases.append(case("ML-11", "mls_lifecycle", "unknown document, empty result",
        [op("create_group", group="g1", members=["m1"]),
         op("submit", doc="d1"),
         op("query_as", member="m1", terms=["zzz"])],
        {"decision": "allow", "empty": True}))
    cases.append(case("ML-12", "mls_lifecycle", "wrong action denied",
        [op("create_group", group="g1", members=["m1"]),
         op("admin_as", member="m1")],
        {"decision": "deny"}))
    # ---------------- attestation/appraisal/freshness (12) ----------------
    cases.append(case("AT-01", "attestation", "valid session serves query",
        [op("create_group", group="g1", members=["m1"]),
         op("submit", doc="d1"),
         op("build_index", partition="p1"),
         op("attest", member="m1"),
         op("query_session", member="m1", terms=["alpha"])],
        {"decision": "allow", "session": "open"}))
    cases.append(case("AT-02", "attestation", "stale evidence denied",
        [op("create_group", group="g1", members=["m1"]),
         op("attest_tamper", member="m1", tamper="stale")],
        {"decision": "deny", "reason": "replay"}))
    cases.append(case("AT-03", "attestation", "wrong measurement denied",
        [op("create_group", group="g1", members=["m1"]),
         op("attest_tamper", member="m1", tamper="wrong_measurement")],
        {"decision": "deny", "reason": "wrong_measurement"}))
    cases.append(case("AT-04", "attestation", "replayed nonce denied",
        [op("create_group", group="g1", members=["m1"]),
         op("attest_replay", member="m1")],
        {"decision": "deny", "reason": "replay"}))
    cases.append(case("AT-05", "attestation", "revoked TCB denied",
        [op("create_group", group="g1", members=["m1"]),
         op("attest_tamper", member="m1", tamper="revoked_tcb")],
        {"decision": "deny", "reason": "revoked_tcb"}))
    cases.append(case("AT-06", "attestation", "missing endorsement denied",
        [op("create_group", group="g1", members=["m1"]),
         op("attest_tamper", member="m1", tamper="no_endorsement")],
        {"decision": "deny", "reason": "missing_endorsement"}))
    cases.append(case("AT-07", "attestation", "unknown signer denied",
        [op("create_group", group="g1", members=["m1"]),
         op("attest_signer", member="m1", signer="evil-signer")],
        {"decision": "deny", "reason": "unknown_signer"}))
    cases.append(case("AT-08", "attestation", "unknown quote profile denied",
        [op("create_group", group="g1", members=["m1"]),
         op("attest_tamper", member="m1", tamper="unknown_version")],
        {"decision": "deny", "reason": "unknown_profile"}))
    cases.append(case("AT-09", "attestation", "expired session denied",
        [op("create_group", group="g1", members=["m1"]),
         op("submit", doc="d1"),
         op("build_index", partition="p1"),
         op("attest", member="m1"),
         op("expire_session", member="m1"),
         op("query_session", member="m1", terms=["alpha"])],
        {"decision": "deny", "reason": "stale_session"}))
    cases.append(case("AT-10", "attestation", "wrong-scope session denied",
        [op("create_group", group="g1", members=["m1"]),
         op("submit", doc="d1"),
         op("build_index", partition="p1"),
         op("attest_scope", member="m1", scope="foreign"),
         op("query_session", member="m1", terms=["alpha"])],
        {"decision": "deny", "reason": "scope_mismatch"}))
    cases.append(case("AT-11", "attestation", "challenge nonce reuse denied",
        [op("create_group", group="g1", members=["m1"]),
         op("attest_twice_same_nonce", member="m1")],
        {"decision": "deny", "reason": "replay"}))
    cases.append(case("AT-12", "attestation", "no-session query denied",
        [op("create_group", group="g1", members=["m1"]),
         op("submit", doc="d1"),
         op("build_index", partition="p1"),
         op("query_session", member="m1", terms=["alpha"])],
        {"decision": "deny", "reason": "no_session"}))
    # ---------------- scope/revocation/cache/restart (12) ----------------
    cases.append(case("RC-01", "revocation_cache", "revocation dominates warm cache",
        [op("create_group", group="g1", members=["m1"]),
         op("submit", doc="d1"),
         op("build_index", partition="p1"),
         op("attest", member="m1"),
         op("query_cached", member="m1", terms=["alpha"]),
         op("revoke", member="m1"),
         op("query_cached", member="m1", terms=["alpha"])],
        {"decision": "deny", "post_revoke_allow": 0}))
    cases.append(case("RC-02", "revocation_cache", "restart keeps warm cache but revoked stays denied",
        [op("create_group", group="g1", members=["m1"]),
         op("submit", doc="d1"),
         op("build_index", partition="p1"),
         op("attest", member="m1"),
         op("query_cached", member="m1", terms=["alpha"]),
         op("revoke", member="m1"),
         op("restart", keep_cache=True),
         op("query_cached", member="m1", terms=["alpha"])],
        {"decision": "deny", "post_revoke_allow": 0}))
    cases.append(case("RC-03", "revocation_cache", "rollback of sealed state detected",
        [op("create_group", group="g1", members=["m1"]),
         op("snapshot", name="s0"),
         op("commit_epoch", group="g1"),
         op("restore", name="s0")],
        {"decision": "rollback_detected"}))
    cases.append(case("RC-04", "revocation_cache", "stale session after rotation denied",
        [op("create_group", group="g1", members=["m1"]),
         op("submit", doc="d1"),
         op("build_index", partition="p1"),
         op("attest", member="m1"),
         op("rotate", group="g1"),
         op("query_session", member="m1", terms=["alpha"])],
        {"decision": "deny", "reason": "stale_session"}))
    cases.append(case("RC-05", "revocation_cache", "token invalidated on revoke",
        [op("create_group", group="g1", members=["m1"]),
         op("submit", doc="d1"),
         op("build_index", partition="p1"),
         op("attest", member="m1"),
         op("make_token", member="m1", terms=["alpha"]),
         op("revoke", member="m1"),
         op("use_token", member="m1")],
        {"decision": "deny", "reason": "unknown_token"}))
    cases.append(case("RC-06", "revocation_cache", "crash before commit reconciles",
        [op("create_group", group="g1", members=["m1"]),
         op("submit_crash", doc="d1", crash="before_commit"),
         op("reconcile_doc", doc="d1")],
        {"decision": "allow", "reconciled": True}))
    cases.append(case("RC-07", "revocation_cache", "crash before audit reconciles",
        [op("create_group", group="g1", members=["m1"]),
         op("submit_crash", doc="d1", crash="before_audit"),
         op("reconcile_doc", doc="d1")],
        {"decision": "allow", "reconciled": True}))
    cases.append(case("RC-08", "revocation_cache", "blind retry refused",
        [op("create_group", group="g1", members=["m1"]),
         op("submit_crash", doc="d1", crash="before_commit"),
         op("blind_retry", doc="d1")],
        {"decision": "deny", "reason": "blind_retry_refused"}))
    cases.append(case("RC-09", "revocation_cache", "rejoin gets new keys, old token dead",
        [op("create_group", group="g1", members=["m1"]),
         op("submit", doc="d1"),
         op("build_index", partition="p1"),
         op("attest", member="m1"),
         op("make_token", member="m1", terms=["alpha"]),
         op("revoke", member="m1"),
         op("add_member", group="g1", member="m1"),
         op("use_token", member="m1")],
        {"decision": "deny", "post_revoke_allow": 0}))
    cases.append(case("RC-10", "revocation_cache", "epoch monotonic across restart",
        [op("create_group", group="g1", members=["m1"]),
         op("commit_epoch", group="g1"),
         op("restart", keep_cache=False),
         op("commit_epoch", group="g1")],
        {"decision": "allow", "epochs": [0, 1, 2]}))
    cases.append(case("RC-11", "revocation_cache", "restart clears cache when asked",
        [op("create_group", group="g1", members=["m1"]),
         op("submit", doc="d1"),
         op("build_index", partition="p1"),
         op("attest", member="m1"),
         op("make_token", member="m1", terms=["alpha"]),
         op("restart", keep_cache=False),
         op("use_token", member="m1")],
        {"decision": "deny", "reason": "unknown_token"}))
    cases.append(case("RC-12", "revocation_cache", "generation rotation invalidates old snapshot",
        [op("create_group", group="g1", members=["m1"]),
         op("snapshot", name="s0"),
         op("revoke", member="m1"),
         op("restore", name="s0")],
        {"decision": "rollback_detected"}))
    # ---------------- leakage/error/unknown outcomes (12) ----------------
    cases.append(case("LK-01", "leakage_unknown", "error carries no plaintext",
        [op("create_group", group="g1", members=["m1"]),
         op("submit", doc="d1"),
         op("query_as", member="ghost", terms=["alpha"])],
        {"decision": "deny", "no_plaintext_in_error": True}))
    cases.append(case("LK-02", "leakage_unknown", "logs carry no keys",
        [op("create_group", group="g1", members=["m1"]),
         op("submit", doc="d1"),
         op("build_index", partition="p1")],
        {"decision": "allow", "no_keys_in_audit": True}))
    cases.append(case("LK-03", "leakage_unknown", "forged result digest denied",
        [op("create_group", group="g1", members=["m1"]),
         op("submit", doc="d1"),
         op("build_index", partition="p1"),
         op("attest", member="m1"),
         op("forge_result", member="m1", terms=["alpha"])],
        {"decision": "deny", "reason": "forged_result"}))
    cases.append(case("LK-04", "leakage_unknown", "cross-tenant query denied",
        [op("create_group", group="g1", members=["m1"]),
         op("submit", doc="d1"),
         op("build_index", partition="p1"),
         op("query_tenant", member="m1", terms=["alpha"], tenant="t-b")],
        {"decision": "deny"}))
    cases.append(case("LK-05", "leakage_unknown", "repeated query equality observed",
        [op("create_group", group="g1", members=["m1"]),
         op("submit", doc="d1"),
         op("build_index", partition="p1"),
         op("attest", member="m1"),
         op("query_twice", member="m1", terms=["alpha"])],
        {"decision": "allow", "equality_observed": True}))
    cases.append(case("LK-06", "leakage_unknown", "timeout censored, not allowed",
        [op("create_group", group="g1", members=["m1"]),
         op("verifier_timeout", member="m1")],
        {"decision": "deny", "reason": "censored"}))
    cases.append(case("LK-07", "leakage_unknown", "unknown side effect reconciles",
        [op("create_group", group="g1", members=["m1"]),
         op("submit_crash", doc="d1", crash="before_commit"),
         op("reconcile_doc", doc="d1")],
        {"decision": "allow"}))
    cases.append(case("LK-08", "leakage_unknown", "provider trust claim ignored",
        [op("create_group", group="g1", members=["m1"]),
         op("submit", doc="d1"),
         op("provider_query", member="mallory", claim={"attested": True})],
        {"decision": "deny"}))
    cases.append(case("LK-09", "leakage_unknown", "secret content censored from bundle",
        [op("create_group", group="g1", members=["m1"]),
         op("submit", doc="sek", content="token sk-proj-abcdefgh12345678")],
        {"decision": "quarantined"}))
    cases.append(case("LK-10", "leakage_unknown", "empty corpus query denies cleanly",
        [op("create_group", group="g1", members=["m1"]),
         op("build_index", partition="p1"),
         op("query_as", member="ghost", terms=["alpha"])],
        {"decision": "deny"}))
    cases.append(case("LK-11", "leakage_unknown", "oversized query rejected",
        [op("create_group", group="g1", members=["m1"]),
         op("oversized_query", member="m1")],
        {"decision": "deny", "reason": "oversized"}))
    cases.append(case("LK-12", "leakage_unknown", "redacted receipt counts omission",
        [op("create_group", group="g1", members=["m1"]),
         op("submit", doc="d1"),
         op("build_index", partition="p1"),
         op("redacted_export", scope="home")],
        {"decision": "allow", "redaction_receipt": True}))
    return cases


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def validate_case(case: dict, known_ids: set | None = None) -> dict:
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "s1018_contract_val", HERE / "contract.py")
    contract = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(contract)
    schema = contract.load("schemas/case.schema.json")
    contract.validate(case, schema)
    if known_ids is not None and case["case_id"] in known_ids:
        raise ValueError("duplicate case id")
    return case


def build(reference=None):
    """Build cases + oracle skeleton; reference fills semantic digests."""
    sys.path.insert(0, str(HERE))
    import runner as runner_mod
    cases = []
    oracle = {}
    seen: set[str] = set()
    for scenario in SCENARIOS():
        validate_case({"case_id": scenario["case_id"],
                       "class": scenario["class"],
                       "description": scenario["description"],
                       "inputs": scenario["inputs"],
                       "transitions": [t["op"] for t in scenario["transitions"]]},
                      seen)
        seen.add(scenario["case_id"])
        digest = sha(canonical({k: scenario[k] for k in sorted(scenario)}))
        entry = dict(scenario)
        entry["semantic_digest"] = digest
        cases.append(entry)
        oracle[scenario["case_id"]] = runner_mod.oracle_for(scenario)
    ids = [c["case_id"] for c in cases]
    assert len(ids) == len(set(ids)) == 48, "case ids must be 48 unique"
    assert len({c["semantic_digest"] for c in cases}) == 48
    by_class: dict[str, int] = {}
    for c in cases:
        by_class[c["class"]] = by_class.get(c["class"], 0) + 1
    assert by_class == {"mls_lifecycle": 12, "attestation": 12,
                        "revocation_cache": 12, "leakage_unknown": 12}, by_class
    corpus = {"schema": "agentos.s1-018.corpus/v1", "ticket": "S1-018",
              "phase": "A", "case_count": 48, "cases": cases}
    oracle_doc = {"schema": "agentos.s1-018.oracle/v1", "ticket": "S1-018",
                  "phase": "A", "entries": oracle}
    return corpus, oracle_doc


def main() -> int:
    corpus, oracle_doc = build()
    (HERE / "cases.json").write_text(
        json.dumps(corpus, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8", newline="\n")
    (HERE / "oracle.json").write_text(
        json.dumps(oracle_doc, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8", newline="\n")
    manifest = {
        "schema": "agentos.s1-018.corpus-manifest/v1",
        "ticket": "S1-018",
        "phase": "A",
        "corpus_sha256": sha((HERE / "cases.json").read_bytes()),
        "oracle_sha256": sha((HERE / "oracle.json").read_bytes()),
        "generator_sha256": sha((HERE / "build_corpus.py").read_bytes()),
        "case_count": 48,
        "deterministic": True,
    }
    (HERE / "corpus-manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"cases": 48, **manifest}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
