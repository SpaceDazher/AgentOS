"""Deterministic canonical corpus generator for S1-015 (40 cases, 5x8).

The generator is the single source of corpus.json + oracle.json. The UI and
the runner receive corpus.json only; oracle.json is evaluator-only. Re-running
must be byte-identical (sorted keys, LF, no timestamps inside the corpus).
"""
from __future__ import annotations

import hashlib
import json
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent

LONG_ID = "prin_9f2e4b8c1d3a5f60718293a4b5c6d7e8f90a1b2c3d4e5f6a7b8c9d0e1f2a3b4"
OVERSIZED = "L" * 500


def _case(case_id, klass, description, principal_id, principal_type, scope,
          tenant, owner, petname, state="active", version=1, supersedes=None,
          second=None, approval_outcome="approve", history=None, probe=None,
          counter=None, accessibility="standard", injection=False,
          confusable_expect=False, lifecycle=None):
    return {
        "case_id": case_id,
        "class": klass,
        "description": description,
        "principal_id": principal_id,
        "principal_type": principal_type,
        "scope": scope,
        "tenant": tenant,
        "petname_owner_id": owner,
        "petname": petname,
        "petname_state": state,
        "petname_version": version,
        "supersedes": supersedes,
        "second_principal": second,
        "approval_outcome": approval_outcome,
        "historical_identity": history if history is not None else principal_id,
        "expected_probe": probe,
        "expected_counter": counter,
        "accessibility": accessibility,
        "injection": injection,
        "confusable_expect": confusable_expect,
        "lifecycle": lifecycle,
    }


CASES = [
    # ---- class 1: benign distinct aliases and canonical controls (8) ----
    _case("BEN-01", "benign", "short ID with distinct petname",
          "prin_a1", "human", "tenant-alpha/workspace-shared", "tenant-alpha",
          "owner_A", "Courier"),
    _case("BEN-02", "benign", "long ID with distinct petname",
          LONG_ID, "human", "tenant-alpha/workspace-shared", "tenant-alpha",
          "owner_A", "Field Notes Archive"),
    _case("BEN-03", "benign", "platform agent with owner label",
          "prin_platform_01", "platform_agent", "tenant-alpha/platform", "tenant-alpha",
          "owner_A", "Sys Helper"),
    _case("BEN-04", "benign", "external agent with sponsor label",
          "prin_external_07", "external_agent", "tenant-alpha/workspace-shared", "tenant-alpha",
          "owner_A", "Contractor Scout"),
    _case("BEN-05", "benign", "publisher versus owner: owner label wins, publisher flagged",
          "prin_pub_01", "external_agent", "tenant-alpha/workspace-shared", "tenant-alpha",
          "owner_A", "Owner Pick", probe="G", lifecycle="publisher-vs-owner"),
    _case("BEN-06", "benign", "non-Latin valid single-script label (Cyrillic)",
          "prin_cyr_01", "human", "tenant-alpha/workspace-shared", "tenant-alpha",
          "owner_A", "Помощник"),
    _case("BEN-07", "benign", "keyboard-only operable display",
          "prin_kb_01", "human", "tenant-alpha/workspace-shared", "tenant-alpha",
          "owner_A", "Keyboard Star", accessibility="keyboard-only"),
    _case("BEN-08", "benign", "screen-reader representation carries canonical ID",
          "prin_sr_01", "human", "tenant-alpha/workspace-shared", "tenant-alpha",
          "owner_A", "Reader Friend", accessibility="screen-reader"),
    # ---- class 2: exact/case/normalization/cross-scope collisions (8) ----
    _case("COL-01", "collision", "exact same petname on two principals -> ambiguity",
          "prin_alex_01", "human", "tenant-alpha/workspace-shared", "tenant-alpha",
          "owner_A", "Alex", second={"principal_id": "prin_alex_02", "scope": "tenant-alpha/workspace-shared"},
          approval_outcome="require-selection", probe="A", counter="collision_auto_resolved_count"),
    _case("COL-02", "collision", "second half of the Alex pair (mirror)",
          "prin_alex_02", "human", "tenant-alpha/workspace-shared", "tenant-alpha",
          "owner_A", "Alex", second={"principal_id": "prin_alex_01", "scope": "tenant-alpha/workspace-shared"},
          approval_outcome="require-selection", probe="A", counter="collision_auto_resolved_count"),
    _case("COL-03", "collision", "case collision Alex vs alex",
          "prin_case_01", "human", "tenant-alpha/workspace-shared", "tenant-alpha",
          "owner_A", "alex", second={"principal_id": "prin_case_02", "scope": "tenant-alpha/workspace-shared"},
          approval_outcome="require-selection", probe="C"),
    _case("COL-04", "collision", "normalization collision NFC vs NFD cafe",
          "prin_nfc_01", "human", "tenant-alpha/workspace-shared", "tenant-alpha",
          "owner_A", unicodedata.normalize("NFC", "café"),
          second={"principal_id": "prin_nfd_02", "scope": "tenant-alpha/workspace-shared"},
          approval_outcome="require-selection", probe="C"),
    _case("COL-05", "collision", "cross-scope same petname different tenant -> scope mismatch",
          "prin_scout_a", "human", "tenant-alpha/workspace-shared", "tenant-alpha",
          "owner_A", "Scout", second={"principal_id": "prin_scout_b", "scope": "tenant-beta/workspace-shared"},
          approval_outcome="require-selection", probe="G", counter="petname_scope_escape_count"),
    _case("COL-06", "collision", "cross-scope near-miss: same normalized, adjacent workspace",
          "prin_nm_a", "human", "tenant-alpha/workspace-shared", "tenant-alpha",
          "owner_A", "Scout-Lead", second={"principal_id": "prin_nm_b", "scope": "tenant-alpha/workspace-private"},
          approval_outcome="require-selection", probe="G"),
    _case("COL-07", "collision", "whitespace collision: trailing space",
          "prin_ws_01", "human", "tenant-alpha/workspace-shared", "tenant-alpha",
          "owner_A", "Alex ", second={"principal_id": "prin_ws_02", "scope": "tenant-alpha/workspace-shared"},
          approval_outcome="require-selection", probe="C"),
    _case("COL-08", "collision", "owner namespaces isolate: same label different owner is not a collision",
          "prin_own_a", "human", "tenant-alpha/workspace-shared", "tenant-alpha",
          "owner_A", "Solo",
          approval_outcome="approve", probe="G"),
    # ---- class 3: rename/delete/reuse/stale-cache lifecycle (8) ----
    _case("LIF-01", "lifecycle", "rename: new versioned projection, audit stays canonical",
          "prin_ren_01", "human", "tenant-alpha/workspace-shared", "tenant-alpha",
          "owner_A", "Courier Prime", state="renamed", version=2, supersedes=1,
          history="prin_ren_01", approval_outcome="approve", probe="B", lifecycle="rename"),
    _case("LIF-02", "lifecycle", "delete: tombstone binding, audit stays canonical",
          "prin_del_01", "human", "tenant-alpha/workspace-shared", "tenant-alpha",
          "owner_A", None, state="deleted", version=3, supersedes=2,
          history="prin_del_01", approval_outcome="approve", probe="B", lifecycle="delete"),
    _case("LIF-03", "lifecycle", "reuse: new principal reuses deleted label with ambiguity history",
          "prin_reuse_02", "human", "tenant-alpha/workspace-shared", "tenant-alpha",
          "owner_A", "Courier", state="active", version=1,
          history="prin_reuse_02", approval_outcome="require-selection", probe="B", lifecycle="reuse"),
    _case("LIF-04", "lifecycle", "stale cache: old version bytes must not rebind",
          "prin_stale_01", "human", "tenant-alpha/workspace-shared", "tenant-alpha",
          "owner_A", "Courier Prime", state="renamed", version=2, supersedes=1,
          history="prin_stale_01", approval_outcome="approve", probe="F",
          counter="stale_petname_rebound_count", lifecycle="stale-cache"),
    _case("LIF-05", "lifecycle", "revoked grant: cached label must not authorize",
          "prin_rev_01", "human", "tenant-alpha/workspace-shared", "tenant-alpha",
          "owner_A", "Old Grant", state="deleted", version=2, supersedes=1,
          history="prin_rev_01", approval_outcome="deny", probe="F", lifecycle="revoke"),
    _case("LIF-06", "lifecycle", "publisher versus owner update: owner projection authoritative",
          "prin_pub_02", "external_agent", "tenant-alpha/workspace-shared", "tenant-alpha",
          "owner_A", "Owner Label", state="active", version=2, supersedes=1,
          history="prin_pub_02", approval_outcome="approve", probe="G", lifecycle="publisher-vs-owner"),
    _case("LIF-07", "lifecycle", "version chain intact across two renames",
          "prin_ch_01", "human", "tenant-alpha/workspace-shared", "tenant-alpha",
          "owner_A", "Courier v3", state="renamed", version=3, supersedes=2,
          history="prin_ch_01", approval_outcome="approve", probe="B", lifecycle="chain"),
    _case("LIF-08", "lifecycle", "deleted label still resolvable to canonical in history view",
          "prin_hist_01", "human", "tenant-alpha/workspace-shared", "tenant-alpha",
          "owner_A", None, state="deleted", version=2, supersedes=1,
          history="prin_hist_01", approval_outcome="approve", probe="B", lifecycle="history"),
    # ---- class 4: unicode/confusable/bidi/invisible/injection (8) ----
    _case("UNI-01", "unicode", "cyrillic/latin confusable: Cyrillic a + lex",
          "prin_conf_01", "human", "tenant-alpha/workspace-shared", "tenant-alpha",
          "owner_A", "аlex", approval_outcome="require-selection",
          probe="C", counter="confusable_spoof_accept_count", confusable_expect=True),
    _case("UNI-02", "unicode", "mixed-script suspicious label",
          "prin_mix_01", "human", "tenant-alpha/workspace-shared", "tenant-alpha",
          "owner_A", "Hеlper", approval_outcome="require-selection",
          probe="C", counter="confusable_spoof_accept_count", confusable_expect=True),
    _case("UNI-03", "unicode", "bidi control override",
          "prin_bidi_01", "human", "tenant-alpha/workspace-shared", "tenant-alpha",
          "owner_A", "Alex\u202eDoe", approval_outcome="require-selection",
          probe="D", confusable_expect=True),
    _case("UNI-04", "unicode", "invisible zero-width space",
          "prin_zw_01", "human", "tenant-alpha/workspace-shared", "tenant-alpha",
          "owner_A", "Alex\u200b", approval_outcome="require-selection",
          probe="D", confusable_expect=True),
    _case("UNI-05", "unicode", "script tag payload renders inert",
          "prin_xss_01", "human", "tenant-alpha/workspace-shared", "tenant-alpha",
          "owner_A", "<script>alert(1)</script>", approval_outcome="approve",
          probe="E", counter="untrusted_markup_executed_count", injection=True,
          confusable_expect=True),
    _case("UNI-06", "unicode", "event-handler + URL payload renders inert",
          "prin_xss_02", "human", "tenant-alpha/workspace-shared", "tenant-alpha",
          "owner_A", "<img src=x onerror=alert(1)>", approval_outcome="approve",
          probe="E", counter="untrusted_markup_executed_count", injection=True,
          confusable_expect=True),
    _case("UNI-07", "unicode", "oversized 500-char label quarantined for display",
          "prin_big_01", "human", "tenant-alpha/workspace-shared", "tenant-alpha",
          "owner_A", OVERSIZED, approval_outcome="approve",
          probe="E", confusable_expect=False),
    _case("UNI-08", "unicode", "empty label is valid baseline-adjacent, never authority",
          "prin_empty_01", "human", "tenant-alpha/workspace-shared", "tenant-alpha",
          "owner_A", "", approval_outcome="approve", probe="E"),
    # ---- class 5: approval/on-behalf/audit/accessibility (8) ----
    _case("APR-01", "approval", "approval binding carries canonical actor/target",
          "prin_apr_01", "human", "tenant-alpha/workspace-shared", "tenant-alpha",
          "owner_A", "Approver Pal", approval_outcome="approve", probe="H"),
    _case("APR-02", "approval", "on-behalf banner carries canonical actor+beneficiary",
          "prin_ob_01", "platform_agent", "tenant-alpha/platform", "tenant-alpha",
          "owner_A", "On-Behalf Star", approval_outcome="approve", probe="H"),
    _case("APR-03", "approval", "audit view after rename still shows canonical history",
          "prin_aud_01", "human", "tenant-alpha/workspace-shared", "tenant-alpha",
          "owner_A", "Renamed Auditor", state="renamed", version=2, supersedes=1,
          history="prin_aud_01", approval_outcome="approve", probe="B",
          counter="historical_identity_rewritten_count", lifecycle="audit"),
    _case("APR-04", "approval", "screen-reader tree includes canonical ID",
          "prin_a11y_01", "human", "tenant-alpha/workspace-shared", "tenant-alpha",
          "owner_A", "A11y Friend", approval_outcome="approve", probe="I",
          counter="accessibility_identity_omission_count", accessibility="screen-reader"),
    _case("APR-05", "approval", "keyboard-only selection of canonical candidate",
          "prin_a11y_02", "human", "tenant-alpha/workspace-shared", "tenant-alpha",
          "owner_A", "A11y Keys", approval_outcome="approve", probe="I",
          accessibility="keyboard-only"),
    _case("APR-06", "approval", "name-only approval target rejected",
          "prin_no_01", "human", "tenant-alpha/workspace-shared", "tenant-alpha",
          "owner_A", "Name Only", approval_outcome="deny", probe="H",
          counter="name_only_authorization_accept_count"),
    _case("APR-07", "approval", "copy canonical ID available without private data",
          "prin_copy_01", "human", "tenant-alpha/workspace-shared", "tenant-alpha",
          "owner_A", "Copy Cat", approval_outcome="approve", probe="I"),
    _case("APR-08", "approval", "color/icon never the sole disambiguation cue",
          "prin_cue_01", "human", "tenant-alpha/workspace-shared", "tenant-alpha",
          "owner_A", "Cue Friend", approval_outcome="approve", probe="I"),
]


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def build():
    corpus_cases = []
    oracle = {}
    for case in CASES:
        payload = {k: v for k, v in case.items()}
        semantic = sha(canonical({k: payload[k] for k in sorted(payload)}))
        corpus_cases.append({**payload, "semantic_digest": semantic})
        oracle[case["case_id"]] = {
            "expected_canonical": case["principal_id"],
            "ambiguity": case["approval_outcome"] == "require-selection",
            "approval_outcome": case["approval_outcome"],
            "historical_identity": case["historical_identity"],
            "expected_probe": case["expected_probe"],
            "expected_counter": case["expected_counter"],
        }
    corpus = {"schema": "agentos.s1-015.corpus/v1", "ticket": "S1-015",
              "case_count": len(corpus_cases), "cases": corpus_cases}
    oracle_doc = {"schema": "agentos.s1-015.oracle/v1", "ticket": "S1-015",
                  "entries": oracle}
    # Uniqueness checks.
    ids = [c["case_id"] for c in corpus_cases]
    assert len(ids) == len(set(ids)) == 40, "case IDs must be 40 unique"
    digests = [c["semantic_digest"] for c in corpus_cases]
    assert len(set(digests)) == 40, "semantic digests must be unique"
    by_class = {}
    for c in corpus_cases:
        by_class[c["class"]] = by_class.get(c["class"], 0) + 1
    assert all(v >= 8 for v in by_class.values()), f"each class needs >=8: {by_class}"
    return corpus, oracle_doc


def main() -> int:
    corpus, oracle_doc = build()
    (HERE / "corpus.json").write_text(
        json.dumps(corpus, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8", newline="\n")
    (HERE / "oracle.json").write_text(
        json.dumps(oracle_doc, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8", newline="\n")
    manifest = {
        "schema": "agentos.s1-015.corpus-manifest/v1",
        "ticket": "S1-015",
        "corpus_sha256": sha((HERE / "corpus.json").read_bytes()),
        "oracle_sha256": sha((HERE / "oracle.json").read_bytes()),
        "generator_sha256": sha((HERE / "build_corpus.py").read_bytes()),
        "case_count": 40,
        "deterministic": True,
    }
    (HERE / "corpus-manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"cases": 40, **manifest}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
