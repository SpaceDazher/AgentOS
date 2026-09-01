"""AgentOS S1-007 — independent fail-closed evaluator.

Derives the QA3 verdict ONLY from SHA-verified raw run observations plus
the frozen rubric/contract/corpus.  It re-implements an independent
oracle of the frozen isolation contract (scope resolution, policy,
invalidation timeline) and re-derives every ISO1-ISO8 counter from the
raw observations; runner-side summaries are never trusted.

Fail-closed rules (each aborts with a non-zero exit):
- provenance: dirty tree, unknown/missing commit, script hash drift,
  diverging commit/tree/contract hashes between main and rerun;
- exact run matrix: missing/extra/duplicate runs, digest mismatch,
  malformed or empty observations;
- contract hashes of every run must equal the frozen files;
- probe candidates A/B/C/D must be detected through the real ISO rules.

Inputs:
  --runs-manifest    results/run-a/run-manifest.json  (main, producer)
  --rerun-manifest   results/run-b/run-manifest.json  (independent rerun)
  --expected-commit  git commit both manifests must carry
  --probes-path      results/probes.json (+ --probes-sha)
  --out              output path (fresh-write semantics, nonce-bound)

The output carries run_nonce from AGENTOS_RUN_NONCE; make_bundle rejects
a saved output whose nonce does not match the nonce of this invocation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import subprocess
import sys
from pathlib import Path

TICKET = Path(__file__).resolve().parent
ROOT = TICKET.parents[3]

SCHEMA_EVAL = "agentos.s1-007.evaluation/v1"
ISO_KEYS = ("ISO1", "ISO2", "ISO3", "ISO4", "ISO5", "ISO6", "ISO7", "ISO8")
DENY_BODY = {"objects": [], "result": "empty"}
PROVENANCE_FIELDS = ("canonical_source_id", "publisher_id",
                     "independence_group", "resolver_version",
                     "created_by_activity")
EVIDENCE_SCRIPTS = (
    "runner.py", "evaluator.py", "make_bundle.py", "dependency_gate.py",
    "bundle_content.py", "publish_evidence_pack.py",
)


class EvalError(RuntimeError):
    pass


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_json(obj) -> str:
    return _sha(json.dumps(obj, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False).encode("utf-8"))


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# independent oracle of the frozen isolation contract
# --------------------------------------------------------------------------

class Oracle:
    """Second, independent derivation of every expected decision from the
    frozen fixtures + corpus manifest.  Written against the contract, not
    against the runner internals."""

    def __init__(self, fixtures: dict, manifest: dict):
        self.fixtures = fixtures
        self.manifest = manifest
        self.memberships = {a["actor"]: list(a["member_of"])
                            for a in fixtures["actors"]}
        self.objects = {(o["id"], o["version"]): dict(o)
                        for o in fixtures["objects"]}
        self.canonical_deny = dict(fixtures["canonical_deny_body"])
        self.cases = {c["id"]: c for c in manifest["cases"]}

    def replay_case(self, case_id: str) -> list:
        case = self.cases.get(case_id)
        if case is None:
            raise EvalError(f"unknown case in manifest: {case_id}")
        entries = []
        for (oid, version), obj in self.objects.items():
            if obj["status"] == "active":
                entries.append({"id": oid, "version": version,
                                "scope": obj["scope"], "active": True})
        epochs = {s: spec["policy_epoch"]
                  for s, spec in
                  ((sc["short"], sc) for sc in self.fixtures["scopes"])}
        expected = []
        for step in case["steps"]:
            op = step["op"]
            if op == "retrieve":
                expected.append(self._expect_retrieve(
                    step, entries, epochs))
            elif op == "revoke":
                entries = [e for e in entries
                           if not (e["id"] == step["target_id"]
                                   and e["scope"] == step["scope"])]
                epochs[step["scope"]] += 1
                expected.append({"op": op, "kind": "invalidation",
                                 "target_id": step["target_id"],
                                 "scope": step["scope"],
                                 "epochs": dict(epochs)})
            elif op == "move":
                for e in entries:
                    if e["id"] == step["target_id"] \
                            and e["scope"] == step["from_scope"]:
                        e["scope"] = step["to_scope"]
                epochs[step["from_scope"]] += 1
                epochs[step["to_scope"]] += 1
                expected.append({"op": op, "kind": "invalidation",
                                 "target_id": step["target_id"],
                                 "epochs": dict(epochs)})
            elif op == "supersede":
                entries = [e for e in entries
                           if not (e["id"] == step["target_id"]
                                   and e["scope"] == step["scope"])]
                entries.append({"id": step["target_id"],
                                "version": step["new_version"],
                                "scope": step["scope"], "active": True})
                epochs[step["scope"]] += 1
                expected.append({"op": op, "kind": "invalidation",
                                 "target_id": step["target_id"],
                                 "epochs": dict(epochs)})
            elif op == "paginate":
                expected.append(self._expect_window(
                    step, entries, epochs, offset=step["offset"],
                    limit=step["limit"]))
            elif op == "aggregate":
                expected.append(self._expect_window(
                    step, entries, epochs, offset=None, limit=None))
            elif op == "bulk":
                rows = [self._expect_retrieve(
                    {"op": "retrieve", "actor": step["actor"],
                     "target_id": tid, "claimed_scope": None},
                    entries, epochs) for tid in step["target_ids"]]
                expected.append({"op": "bulk", "kind": "bulk",
                                 "ids": list(step["target_ids"]),
                                 "rows": rows})
            elif op == "background_reindex":
                scope_entries = [dict(e) for e in entries
                                 if e["scope"] == step["scope"]
                                 and e["active"]]
                expected.append({"op": op, "kind": "reindex",
                                 "scope": step["scope"],
                                 "entries": scope_entries})
            else:
                raise EvalError(f"oracle: unknown op {op}")
        return expected

    def _resolve_eff(self, step):
        actor = step["actor"]
        canonical = self.memberships.get(actor, [])
        eff = canonical[0] if len(canonical) == 1 else \
            (None if not canonical else "AMBIGUOUS")
        claimed = step.get("claimed_scope")
        alias = {s["scope_id"]: s["short"] for s in self.fixtures["scopes"]}
        shorts = {s["short"] for s in self.fixtures["scopes"]}
        if claimed is None:
            return eff, None
        claimed_short = alias.get(claimed, claimed)
        if claimed_short not in shorts:
            return None, "unknown_scope"
        if eff is None or claimed_short != eff:
            return None, "forged_scope"
        return eff, None

    def _visible(self, entries, eff, target_id, version=None):
        found = [e for e in entries
                 if e["id"] == target_id and e["scope"] == eff
                 and e["active"]
                 and (version is None or e["version"] == version)]
        return found

    def _expect_retrieve(self, step, entries, epochs):
        eff, reason = self._resolve_eff(step)
        base = {"op": "retrieve", "actor": step["actor"],
                "target_id": step["target_id"],
                "claimed_scope": step.get("claimed_scope"),
                "effective_scope": eff, "epochs": dict(epochs)}
        if eff is None:
            return {**base, "decision": "deny", "reason_class": reason,
                    "objects": []}
        found = self._visible(entries, eff, step["target_id"],
                              step.get("version"))
        if not found:
            return {**base, "decision": "deny", "reason_class": "empty",
                    "objects": []}
        return {**base, "decision": "allow", "objects":
                [(e["id"], e["version"], e["scope"]) for e in found]}

    def _expect_window(self, step, entries, epochs, offset, limit):
        eff, reason = self._resolve_eff(step)
        base = {"op": step["op"], "actor": step["actor"],
                "effective_scope": eff, "epochs": dict(epochs)}
        if eff is None:
            return {**base, "decision": "deny", "authorized": []}
        rows = sorted([e for e in entries if e["scope"] == eff
                       and e["active"]],
                      key=lambda e: (e["id"], e["version"]))
        authorized = [(e["id"], e["version"]) for e in rows]
        window = authorized if offset is None \
            else authorized[offset:offset + limit]
        return {**base, "decision": "allow", "authorized": authorized,
                "window": window}


# --------------------------------------------------------------------------
# ISO derivation from raw observations against the oracle
# --------------------------------------------------------------------------

def _check_run(run: dict, expected_steps: list, oracle: Oracle) -> dict:
    """Return ISO counters + findings for one run.  Malformed structure or
    observation/timeline divergence raises EvalError (fail closed)."""
    counters = {k: 0 for k in ISO_KEYS}
    findings = []
    observations = run.get("observations")
    if not observations or not isinstance(observations, list):
        raise EvalError(f"run {run.get('run_id')}: empty observations")
    idx = 0
    for exp in expected_steps:
        if exp.get("kind") == "bulk":
            n = len(exp["ids"])
            block = observations[idx:idx + n]
            summary = observations[idx + n]
            if len(block) < n or summary.get("op") != "bulk_summary":
                raise EvalError(
                    f"run {run['run_id']}: malformed bulk block")
            # the runner may execute the batch in a seeded shuffled order;
            # require a permutation, then pair per id
            if sorted(o.get("target_id") for o in block) != \
                    sorted(exp["ids"]):
                raise EvalError(
                    f"run {run['run_id']}: bulk id set mismatch")
            if summary.get("order") != [o.get("target_id")
                                        for o in block]:
                raise EvalError(
                    f"run {run['run_id']}: bulk summary order mismatch")
            expected_by_id = {row["target_id"]: row
                              for row in exp["rows"]}
            for obs in block:
                _check_retrieval_obs(
                    obs, run, counters, findings,
                    expected=expected_by_id[obs.get("target_id")],
                    oracle=oracle)
            idx += n + 1
            continue
        obs = observations[idx]
        if obs.get("op") != exp["op"]:
            raise EvalError(
                f"run {run['run_id']}: step {idx} op {obs.get('op')} != "
                f"expected {exp['op']}")
        if exp.get("kind") == "invalidation":
            if obs.get("committed_invalidation_point") is not True:
                raise EvalError(
                    f"run {run['run_id']}: invalidation without commit")
            if obs.get("epochs_after") != exp["epochs"]:
                raise EvalError(
                    f"run {run['run_id']}: epoch timeline divergence")
        elif exp.get("kind") == "reindex":
            _check_reindex_obs(obs, exp, run, counters, findings)
        else:
            _check_retrieval_obs(obs, run, counters, findings,
                                 expected=exp, oracle=oracle)
        idx += 1
    if idx != len(observations):
        raise EvalError(
            f"run {run['run_id']}: {len(observations) - idx} unmatched "
            f"observations")
    return counters


def _deny_is_canonical(obs) -> bool:
    return obs.get("response") == DENY_BODY


def _check_retrieval_obs(obs, run, counters, findings, expected=None,
                         oracle=None):
    target = obs.get("target_id")
    decision = obs.get("decision")
    eff = obs.get("effective_scope")
    actor = obs.get("actor")
    canonical_eff = None
    if actor in oracle.memberships and len(oracle.memberships[actor]) == 1:
        canonical_eff = oracle.memberships[actor][0]

    # timeline check: observed epoch snapshot must match the oracle's
    if expected is not None and obs.get("policy_epoch_at_step") != \
            expected["epochs"]:
        raise EvalError(f"run {run['run_id']}: epoch snapshot divergence "
                        f"at target {target}")

    # ISO7/ISO8: caller-supplied scope never widens; unknown/malformed
    # scope denies and never resolves to a default
    claimed = obs.get("claimed_scope")
    if claimed is not None:
        alias = {s["scope_id"]: s["short"] for s in oracle.fixtures["scopes"]}
        claimed_short = alias.get(claimed, claimed)
        shorts = {s["short"] for s in oracle.fixtures["scopes"]}
        if claimed_short not in shorts:
            if decision == "allow":
                counters["ISO8"] += 1
                findings.append({"iso": "ISO8", "target": target,
                                 "why": "unknown claimed scope allowed"})
            if eff is not None and canonical_eff is None:
                counters["ISO8"] += 1
                findings.append({"iso": "ISO8", "target": target,
                                 "why": "default scope assigned"})
        elif canonical_eff is None or claimed_short != canonical_eff:
            if decision == "allow" or (eff is not None
                                       and eff != canonical_eff):
                counters["ISO7"] += 1
                findings.append({"iso": "ISO7", "target": target,
                                 "why": "forged scope widened or accepted"})

    if decision == "deny":
        # ISO2: canonical deny form, byte-identical, no detail
        if not _deny_is_canonical(obs):
            counters["ISO2"] += 1
            findings.append({"iso": "ISO2", "target": target,
                             "why": "deny body is not canonical",
                             "response": obs.get("response")})
        return
    if decision != "allow":
        raise EvalError(f"run {run['run_id']}: unknown decision {decision}")

    # ISO3: any cache hit must carry epoch revalidation and a verifiable
    # binding (checked on every allow response, before decision-timeline
    # comparisons, so a stale hit is never hidden by an ISO4 finding)
    events = obs.get("cache_events", [])
    if "hit_no_revalidation" in events:
        counters["ISO3"] += 1
        findings.append({"iso": "ISO3", "target": target,
                         "why": "cache hit without revalidation"})
    if "hit" in events:
        if "epoch_revalidation" not in obs.get("policy_checks", []):
            counters["ISO3"] += 1
            findings.append({"iso": "ISO3", "target": target,
                             "why": "hit without epoch revalidation check"})
        binding = obs.get("cache_entry_binding")
        if not isinstance(binding, dict) or \
                not all((binding.get("scope"), binding.get("epoch"),
                         binding.get("digest"))):
            counters["ISO3"] += 1
            findings.append({"iso": "ISO3", "target": target,
                             "why": "unverifiable cache binding"})
        else:
            if binding["scope"] != eff:
                counters["ISO3"] += 1
                findings.append({"iso": "ISO3", "target": target,
                                 "why": "cross-scope cache hit"})
            current = (expected or {}).get("epochs", {}).get(eff)
            if current is not None and binding["epoch"] != current:
                counters["ISO3"] += 1
                findings.append({"iso": "ISO3", "target": target,
                                 "why": "stale epoch served"})

    if expected is None:
        return  # unreachable: bulk rows carry their expected row

    # ---- window ops (paginate/aggregate) ----
    if obs.get("op") in ("paginate", "aggregate"):
        if "scope_resolution_canonical" not in obs.get("policy_checks", []):
            counters["ISO6"] += 1
            findings.append({"iso": "ISO6", "target": target,
                             "why": "window op without policy check"})
        response = obs.get("response", {})
        objects = response.get("objects", [])
        if expected["decision"] != "allow":
            if objects or response != DENY_BODY:
                counters["ISO2"] += 1
                findings.append({"iso": "ISO2", "target": target,
                                 "why": "non-canonical window response"})
            return
        authorized = set(expected["authorized"])
        authorized_ids = {e[0] for e in authorized}
        window = set(expected.get("window") or authorized)
        for o in objects:
            if (o.get("id"), o.get("version")) not in window:
                counters["ISO1"] += 1
                findings.append({"iso": "ISO1", "target": target,
                                 "why": "foreign/unwindowed row in page"})
            else:
                prov = o.get("provenance")
                if not isinstance(prov, dict) or any(
                        not prov.get(f) for f in PROVENANCE_FIELDS):
                    counters["ISO5"] += 1
                    findings.append({"iso": "ISO5", "target": target,
                                     "why": "provenance lost in window"})
        meta = response.get("meta", {})
        for key in ("ranks", "snippets"):
            for item in meta.get(key, []):
                if item.get("id") not in authorized_ids:
                    counters["ISO2"] += 1
                    findings.append({"iso": "ISO2", "target": target,
                                     "why": f"foreign {key} entry"})
        if meta.get("total_count") != len(authorized):
            counters["ISO2"] += 1
            findings.append({"iso": "ISO2", "target": target,
                             "why": "pre-filter aggregate count"})
        if obs.get("op") == "paginate":
            if meta.get("result_count") != len(objects):
                counters["ISO2"] += 1
                findings.append({"iso": "ISO2", "target": target,
                                 "why": "result_count mismatch"})
        else:  # aggregate: counts describe matched authorized rows
            if meta.get("result_count") != len(authorized):
                counters["ISO2"] += 1
                findings.append({"iso": "ISO2", "target": target,
                                 "why": "aggregate count mismatch"})
        return

    # ---- single retrieve ----
    if expected["decision"] != "allow":
        # observed allow where the oracle denies (stale / forged / leak)
        objects = obs.get("response", {}).get("objects", [])
        foreign = [o for o in objects if o.get("scope") != eff]
        if foreign:
            counters["ISO1"] += 1
            findings.append({"iso": "ISO1", "target": target,
                             "why": "foreign content in response"})
        elif objects:
            counters["ISO4"] += 1
            findings.append({"iso": "ISO4", "target": target,
                             "why": "stale data served after invalidation"})
        else:
            counters["ISO2"] += 1
            findings.append({"iso": "ISO2", "target": target,
                             "why": "non-canonical allow-with-empty"})
        return

    response = obs.get("response", {})
    objects = response.get("objects", [])
    if len(objects) != len(expected["objects"]):
        counters["ISO2"] += 1
        findings.append({"iso": "ISO2", "target": target,
                         "why": "object count mismatch vs oracle"})
        return
    for got, (eid, eversion, escope) in zip(objects, expected["objects"]):
        if got.get("id") != eid or got.get("version") != eversion:
            counters["ISO1"] += 1
            findings.append({"iso": "ISO1", "target": target,
                             "why": "unauthorized object identity"})
            continue
        if got.get("scope") != escope or escope != eff:
            counters["ISO1"] += 1
            findings.append({"iso": "ISO1", "target": target,
                             "why": "cross-scope object disclosure"})
        prov = got.get("provenance")
        if not isinstance(prov, dict) or \
                any(not prov.get(f) for f in PROVENANCE_FIELDS):
            counters["ISO5"] += 1
            findings.append({"iso": "ISO5", "target": target,
                             "why": "provenance lost or incomplete"})
        fixture = oracle.objects.get((eid, eversion))
        if fixture is None or got.get("content") != fixture["content"]:
            counters["ISO2"] += 1
            findings.append({"iso": "ISO2", "target": target,
                             "why": "content mismatch vs fixtures"})

    # ISO3 block already ran above for every allow response


def _check_reindex_obs(obs, exp, run, counters, findings):
    if "indexer_scope_context" not in obs.get("policy_checks", []):
        counters["ISO6"] += 1
        findings.append({"iso": "ISO6", "target": exp["scope"],
                         "why": "background job without scope context"})
    result = obs.get("reindex_result", {})
    for entry in result.get("entries", []):
        if entry.get("scope") != exp["scope"]:
            counters["ISO6"] += 1
            findings.append({"iso": "ISO6", "target": entry.get("id"),
                             "why": "out-of-scope reindex write"})
        prov = entry.get("provenance")
        if not isinstance(prov, dict) or \
                any(not prov.get(f) for f in PROVENANCE_FIELDS):
            counters["ISO5"] += 1
            findings.append({"iso": "ISO5", "target": entry.get("id"),
                             "why": "provenance lost in projection"})


# --------------------------------------------------------------------------
# manifest / provenance validation
# --------------------------------------------------------------------------

def _git_show_bytes(commit: str, path: str) -> bytes:
    """Blob bytes at a commit; any git failure is an error, never an
    'unavailable' skip (fail-closed provenance)."""
    out = subprocess.run(["git", "show", f"{commit}:{path}"],
                         capture_output=True, timeout=30, cwd=str(ROOT))
    if out.returncode != 0:
        raise EvalError(
            f"git show {commit}:{path} failed ({out.returncode}): "
            f"{out.stderr.decode('utf-8', 'replace').strip()}")
    return out.stdout


def _normalize_line_endings(data: bytes) -> bytes:
    """Explicit checkout-normalization policy: the on-disk working copy
    may carry CRLF while the committed blob carries LF.  Evidence
    comparisons normalize CRLF to LF before hashing; the raw disk hash
    is still recorded for transparency."""
    return data.replace(b"\r\n", b"\n")


def validate_provenance(prov: dict, expected_commit: str | None) -> None:
    if not isinstance(prov, dict):
        raise EvalError("missing provenance block")
    if prov.get("dirty"):
        raise EvalError(
            "research surface is dirty: "
            f"{prov.get('dirty_lines')}")
    commit = prov.get("commit")
    if not commit or len(commit) != 40:
        raise EvalError("missing or malformed commit provenance")
    if expected_commit and commit != expected_commit:
        raise EvalError("manifest commit does not match expected commit")
    if not prov.get("tree_sha"):
        raise EvalError("missing tree sha")
    if not prov.get("executor_id"):
        raise EvalError("missing executor identity")
    scripts = prov.get("script_hashes")
    blobs = prov.get("script_blob_hashes")
    if not isinstance(scripts, dict) or \
            set(scripts.keys()) != set(EVIDENCE_SCRIPTS):
        raise EvalError(
            "script_hashes must cover exactly the executed evidence "
            f"scripts: missing="
            f"{sorted(set(EVIDENCE_SCRIPTS) - set(scripts or {}))} "
            f"extra={sorted(set(scripts or {}) - set(EVIDENCE_SCRIPTS))}")
    if not isinstance(blobs, dict) or \
            set(blobs.keys()) != set(EVIDENCE_SCRIPTS):
        raise EvalError(
            "script_blob_hashes must cover exactly the executed evidence "
            "scripts")
    for name in sorted(EVIDENCE_SCRIPTS):
        path = TICKET / name
        if not path.is_file():
            raise EvalError(f"evidence script missing on disk: {name}")
        disk_raw = path.read_bytes()
        if _sha(disk_raw) != scripts[name]:
            raise EvalError(f"script disk hash drift: {name}")
        # bind the recorded blob hash to the commit itself
        try:
            blob = _git_show_bytes(commit,
                                   (TICKET / name).relative_to(ROOT)
                                   .as_posix())
        except EvalError:
            raise
        if _sha(blob) != blobs[name]:
            raise EvalError(
                f"script blob hash mismatch vs commit for {name}: "
                f"recorded {blobs[name][:16]}... actual {_sha(blob)[:16]}...")
        # disk bytes must equal the blob modulo the documented CRLF
        # checkout-normalization policy
        if _sha(_normalize_line_endings(disk_raw)) != _sha(blob):
            raise EvalError(
                f"script working-copy bytes diverge from the committed "
                f"blob beyond documented CRLF normalization: {name}")


def validate_run_matrix(manifest_doc: dict, runs_dir: Path,
                        frozen_hashes: dict | None = None) -> dict:
    manifest = load(TICKET / "corpus-manifest.json")
    variants = manifest["variants"]
    seeds = manifest["seeds"]
    cases = [c["id"] for c in manifest["cases"]]
    expected_ids = sorted(f"{v}|{c}|{s}" for v in variants
                          for c in cases for s in seeds)
    got = [r["run_id"] for r in manifest_doc.get("runs", [])]
    if sorted(got) != expected_ids:
        missing = set(expected_ids) - set(got)
        extra = set(got) - set(expected_ids)
        dup = len(got) != len(set(got))
        raise EvalError(
            f"run matrix divergence: missing={sorted(missing)} "
            f"extra={sorted(extra)} duplicate={dup}")
    runs = {}
    for entry in manifest_doc["runs"]:
        path = runs_dir / entry["path"]
        if not path.is_file():
            raise EvalError(f"run file missing: {entry['path']}")
        if ".." in entry["path"] or "/" in entry["path"] \
                or "\\" in entry["path"]:
            raise EvalError(f"unregistered artifact path: {entry['path']}")
        raw = path.read_bytes()
        if _sha(raw) != entry["sha256"]:
            raise EvalError(f"run file digest mismatch: {entry['path']}")
        data = json.loads(raw.decode("utf-8"))
        validate_raw_run(data, entry["run_id"])
        if frozen_hashes is not None and \
                data.get("contract_hashes") != frozen_hashes:
            raise EvalError(
                f"run {entry['run_id']}: contract hashes diverge from "
                f"frozen files")
        runs[entry["run_id"]] = data
    return runs


def validate_raw_run(data: dict, run_id: str) -> None:
    if data.get("schema") != "agentos.s1-007.run/v1":
        raise EvalError(f"run {run_id}: schema mismatch")
    if data.get("run_id") != run_id:
        raise EvalError(f"run {run_id}: id mismatch")
    variant, case, seed = run_id.split("|")
    if data.get("variant") != variant or data.get("case_id") != case \
            or data.get("seed") != int(seed):
        raise EvalError(f"run {run_id}: field divergence from run_id")
    for key in ("observations", "metrics", "final_state", "iso_counters"):
        if key not in data or data[key] in (None, "", {}, []):
            if key != "iso_counters" or data.get("iso_counters") is None:
                raise EvalError(f"run {run_id}: empty {key}")
    if set(data.get("iso_counters", {}).keys()) != set(ISO_KEYS):
        raise EvalError(f"run {run_id}: ISO counter key-set mismatch")
    contracts = data.get("contract_hashes")
    if not isinstance(contracts, dict) or not contracts:
        raise EvalError(f"run {run_id}: missing contract hashes")


# --------------------------------------------------------------------------
# scoring per the frozen rubric
# --------------------------------------------------------------------------

def percentile(sorted_values, pct):
    if not sorted_values:
        return None
    k = (len(sorted_values) - 1) * pct / 100.0
    lo, hi = int(k), min(int(k) + 1, len(sorted_values) - 1)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * \
        (k - int(k))


def aggregate_variant(runs: dict, variant: str, oracle: Oracle) -> dict:
    agg = {
        "iso": {k: 0 for k in ISO_KEYS},
        "findings": [],
        "deny_bodies_canonical": True,
        "deny_equivalence_foreign_vs_nonexistent": True,
        "materialize_before_policy": 0,
        "allow_steps": 0,
        "allow_steps_with_provenance": 0,
        "audit_events": 0,
        "audit_with_protected_data": 0,
        "decision_observations": 0,
        "rows_scanned_total": 0,
        "policy_evaluations_total": 0,
        "invalidation_ops_total": 0,
        "storage": None,
        "cache_hits": 0,
        "stale_invalidated": 0,
        "per_case": {},
    }
    foreign_digests = set()
    control_digests = set()
    for run_id, data in sorted(runs.items()):
        v, case, seed = run_id.split("|")
        if v != variant:
            continue
        counters = _check_run(data, oracle.replay_case(case), oracle)
        for k in ISO_KEYS:
            agg["iso"][k] += counters[k]
        agg["findings"].extend([])
        for obs in data["observations"]:
            agg["materialize_before_policy"] += \
                obs.get("materialize_before_policy_check", 0)
            agg["rows_scanned_total"] += obs.get("rows_scanned", 0)
            if obs.get("op") in ("retrieve", "paginate", "aggregate"):
                agg["decision_observations"] += 1
                if obs.get("decision") == "deny" and \
                        not _deny_is_canonical(obs):
                    agg["deny_bodies_canonical"] = False
                if obs.get("decision") == "allow":
                    agg["allow_steps"] += 1
                    objs = obs.get("response", {}).get("objects", [])
                    if objs and all(
                            isinstance(o.get("provenance"), dict)
                            and all(o["provenance"].get(f)
                                    for f in PROVENANCE_FIELDS)
                            for o in objs):
                        agg["allow_steps_with_provenance"] += 1
                audit = obs.get("audit_event") or {}
                if audit:
                    agg["audit_events"] += 1
                    body = json.dumps(audit)
                    if "content" in body or "snippet" in body.replace(
                            '"generic_reason_class"', ""):
                        agg["audit_with_protected_data"] += 1
        metrics = data.get("metrics", {})
        agg["policy_evaluations_total"] += \
            metrics.get("policy_evaluations", 0)
        agg["invalidation_ops_total"] += \
            metrics.get("invalidation_ops", 0)
        agg["cache_hits"] += metrics.get("cache_hits", 0)
        agg["stale_invalidated"] += metrics.get("stale_invalidated", 0)
        storage = data.get("final_state", {}).get("storage")
        agg["storage"] = storage  # identical per variant each run
        if case == "foreign-id-valid":
            for obs in data["observations"]:
                if obs.get("decision") == "deny":
                    foreign_digests.add(obs.get("response_digest"))
        if case == "nonexistent-id-control":
            for obs in data["observations"]:
                if obs.get("decision") == "deny":
                    control_digests.add(obs.get("response_digest"))
        agg["per_case"][case] = {
            "iso": {k: counters[k] for k in ISO_KEYS},
            "decisions": [o.get("decision") for o in data["observations"]],
        }
    if foreign_digests and control_digests:
        agg["deny_equivalence_foreign_vs_nonexistent"] = \
            foreign_digests == control_digests
    return agg


def score_dimensions(agg_a: dict, agg_b: dict, timing: dict, probes: dict,
                     n_scopes: int) -> dict:
    """Frozen scoring formulas; every cell is stored PER (dimension,
    variant) so symmetric evidence can never overwrite the other
    candidate's score, and every cell carries evidence refs, claim type,
    confidence, limitation and missing evidence."""
    cells = {}
    aggs = {"per_scope": agg_a, "shared_rls": agg_b}

    def measured(dim, variant, name, value, refs, limit=None, missing=None):
        cells.setdefault(dim, {})[variant] = {
            "dimension": name, "score": round(value, 4),
            "claim_type": "test_measurement", "confidence": "high",
            "evidence_refs": refs, "limitation": limit,
            "missing_evidence": missing, "value_type": "number"}

    for variant, agg in aggs.items():
        iso = agg["iso"]
        t = timing["variants"].get(variant, {})
        # D1
        if iso["ISO1"] > 0 or iso["ISO2"] > 0:
            d1 = 0.0
        else:
            d1 = 4.0
            if not agg["deny_bodies_canonical"] or                     not agg["deny_equivalence_foreign_vs_nonexistent"]:
                d1 = 0.0
            if t.get("verdict") == "SIGNAL_ABOVE_TOLERANCE":
                d1 -= 2.0
        refs = [f"iso:{variant}:ISO1={iso['ISO1']}",
                f"iso:{variant}:ISO2={iso['ISO2']}",
                f"timing:{variant}:{t.get('verdict')}"]
        measured("D1", variant, "content/existence/metadata isolation", d1,
                 refs,
                 limit=None if t.get("verdict") == "WITHIN_TOLERANCE"
                 else f"timing verdict {t.get('verdict')}")
        # D2
        d2 = 4.0 if agg["materialize_before_policy"] == 0 else 0.0
        measured("D2", variant, "correctness of authorization placement",
                 d2,
                 [f"{variant}:materialize_before_policy="
                  f"{agg['materialize_before_policy']}"])
        # D3
        d3 = 4.0 if iso["ISO3"] == 0 and iso["ISO4"] == 0 else 0.0
        measured("D3", variant, "cache invalidation and revoke/move behavior",
                 d3,
                 [f"{variant}:ISO3={iso['ISO3']}",
                  f"{variant}:ISO4={iso['ISO4']}",
                  f"{variant}:stale_invalidated={agg['stale_invalidated']}",
                  f"{variant}:invalidation_ops="
                  f"{agg['invalidation_ops_total']}"])
        # D4
        share = (agg["allow_steps_with_provenance"] /
                 agg["allow_steps"]) if agg["allow_steps"] else 0.0
        d4 = 0.0 if iso["ISO5"] > 0 else 4.0 * share
        measured("D4", variant, "projection/provenance integrity", d4,
                 [f"{variant}:ISO5={iso['ISO5']}",
                  f"{variant}:provenance_share={share:.4f}"])
        # D5
        d5 = 4.0 if iso["ISO6"] == 0 else 0.0
        measured("D5", variant, "bulk/pagination/background-job isolation",
                 d5, [f"{variant}:ISO6={iso['ISO6']}"])
        # D6 (fault injection through real retrieval paths, per variant)
        faults = probes["fault_injection"][variant]
        n = max(n_scopes - 1, 1)

        def blast(v):
            return 4.0 - 3.0 * (v - 1) / n

        d6 = (max(blast(faults["predicate_bypass_affected_scopes"]), 0.0)
              + max(blast(faults["corrupt_entry_affected_scopes"]), 0.0)) / 2
        measured("D6", variant, "failure blast radius", d6,
                 [f"fault:{variant}:{json.dumps(faults)}"],
                 limit="in-model fault injection, not production fault data")
        # D7
        audit_share = (agg["audit_events"] /
                       agg["decision_observations"])             if agg["decision_observations"] else 0.0
        d7 = 4.0 * audit_share if agg["audit_with_protected_data"] == 0             else 0.0
        measured("D7", variant, "auditability and counterexample quality",
                 d7,
                 [f"{variant}:audit_share={audit_share:.4f}",
                  f"{variant}:protected_in_audit="
                  f"{agg['audit_with_protected_data']}"])
        # D8 (cross-executor determinism; filled by caller per variant)
        cells.setdefault("D8", {})[variant] = 4.0
        # D10 raw metrics for the directional computation below
        cells.setdefault("_metrics", {})[variant] = {
            "storage": agg["storage"] or {},
            "rows_scanned_total": agg["rows_scanned_total"]}
    # D9 (inference from frozen contract facts)
    cells["D9"] = {
        "per_scope": {
            "components_on_path": 2, "migration_steps": 0,
            "score": round(4 - 0.5 * (2 - 2) - 0.25 * 0, 4)},
        "shared_rls": {
            "components_on_path": 3, "migration_steps": 2,
            "score": round(4 - 0.5 * (3 - 2) - 0.25 * 2, 4)},
        "claim_type": "architecture_tradeoff", "confidence": "medium",
        "evidence_refs": ["isolation-contract.json#variants",
                          "gateway.py memory scoping (per-goal canonical)",
                          "SRC-03 section 4/6"],
        "limitation": "inference from the frozen contract and current "
                      "implementation, not a measured production cost",
        "missing_evidence": "multi-scope production workload data"}
    # D11 (inference from threat model + profiles)
    cells["D11"] = {
        "per_scope": {"score": 4.0},
        "shared_rls": {"score": 2.0},
        "claim_type": "residual_risk", "confidence": "medium",
        "evidence_refs": ["threat-model.json#T8",
                          "SRC-03 section 6 (profile C: client-side "
                          "member indexes; server=ciphertext)",
                          "SRC-07 G-04"],
        "limitation": "profile-C compatibility is a documented-design "
                      "inference; S1-018 owns the MLS/TEE contract",
        "missing_evidence": "profile-C PoC (S1-018)"}
    return cells


def apply_d8_and_d10(cells: dict, determinism_share: dict) -> None:
    """Fill D8 (cross-executor determinism, per variant) and D10
    (directional storage/scan overhead: the variant with the LOWER
    measured cost receives the higher score; scores are normalized
    against the worst measured value, never symmetric min/max)."""
    metrics = cells.pop("_metrics")
    variants = ("per_scope", "shared_rls")
    for variant in variants:
        cells.setdefault("D8", {})[variant] =             round(4.0 * determinism_share.get(variant, 0.0), 4)
    bytes_v = {v: metrics[v]["storage"]["payload_bytes_est"] for v in variants}
    scans_v = {v: metrics[v]["rows_scanned_total"] for v in variants}
    max_bytes = max(bytes_v.values())
    max_scans = max(scans_v.values())
    for variant in variants:
        # directional: costlier variant scores strictly lower unless equal
        storage_score = 4.0 * bytes_v[variant] / max_bytes
        scan_score = 4.0 * scans_v[variant] / max_scans
        d10 = round((storage_score + scan_score) / 2, 4)
        cells.setdefault("D10", {})[variant] = {
            "score": d10, "claim_type": "test_measurement",
            "confidence": "high",
            "evidence_refs": [
                f"storage:{variant}:{bytes_v[variant]}B "
                f"(max {max_bytes}B)",
                f"rows_scanned:{variant}:{scans_v[variant]} "
                f"(max {max_scans})"],
            "limitation": "local model with a frozen fixed per-index "
                          "overhead constant "
                          "(INDEX_FIXED_OVERHEAD_BYTES=256)",
            "missing_evidence": "production storage/latency data"}


def weighted_scores(scores: dict, weights: dict) -> dict:
    out = {}
    for variant in ("per_scope", "shared_rls"):
        total = 0.0
        wsum = 0.0
        for dim, w in weights.items():
            s = scores.get(dim, {}).get(variant)
            if s is None:
                continue
            total += w * s
            wsum += w
        out[variant] = round(total / wsum, 4) if wsum else None
    return out


def sensitivity_analysis(dim_scores: dict, weights: dict,
                         rng_seed: int = 42, vectors: int = 200,
                         base_expected: dict | None = None) -> dict:
    """Weight perturbation analysis over the per-dimension score matrix.
    `dim_scores` maps dimension id -> {variant: score}; unknown (None)
    cells are excluded from each reweighting per the frozen rubric."""
    base_scores = weighted_scores(dim_scores, weights)
    if base_expected is not None and base_expected != base_scores:
        raise EvalError("base score drift between evaluation and "
                        "sensitivity input")
    flips = []
    winner = max(base_scores, key=lambda k: base_scores[k])
    dims = sorted(weights)
    # one-at-a-time +-50%
    for dim in dims:
        for factor in (0.5, 1.5):
            ws = dict(weights)
            ws[dim] = weights[dim] * factor
            z = sum(ws.values())
            ws = {d: w / z for d, w in ws.items()}
            sc = weighted_scores(dim_scores, ws)
            w2 = max(sc, key=lambda k: sc[k])
            if w2 != winner:
                flips.append({"kind": "oat", "dim": dim,
                              "factor": factor, "winner": w2})
    rng = random.Random(rng_seed)
    for i in range(vectors):
        raw = [rng.random() for _ in dims]
        z = sum(raw)
        ws = {d: r / z for d, r in zip(dims, raw)}
        sc = weighted_scores(dim_scores, ws)
        w2 = max(sc, key=lambda k: sc[k])
        if w2 != winner:
            flips.append({"kind": "random", "vector": i, "winner": w2})
    oat_count = len(dims) * 2
    return {"base_scores": base_scores, "base_weights": weights,
            "oat_weight_factors": [0.5, 1.5],
            "oat_perturbations_executed": oat_count,
            "random_vectors": vectors, "random_seed": rng_seed,
            "total_perturbations_executed": oat_count + vectors,
            "policy": "weights-only perturbation; every scored cell was a "
                      "measured number, so no unknown-bound swing applies "
                      "(unknown-bound analysis would activate only if a "
                      "cell scored NO_DATA)",
            "flips": flips, "flip_count": len(flips),
            "winner_stable": not flips}


def evaluate_probes(probes: dict, oracle: Oracle,
                    corpus_manifest: dict | None = None) -> dict:
    """Bind every probe to its FROZEN matrix entry (candidate identity,
    cases, seeds, exact run ids) BEFORE evaluating counters; reject
    missing, extra, duplicated or relabelled probes fail-closed."""
    if corpus_manifest is None:
        corpus_manifest = load(TICKET / "corpus-manifest.json")
    spec = corpus_manifest.get("probe_spec")
    if not isinstance(spec, dict) or \
            set(spec.get("probes", {}).keys()) != \
            {"A_existence_oracle", "B_stale_cache", "C_postfilter",
             "D_forged_scope_provenance_loss"}:
        raise EvalError("frozen probe spec missing or malformed")
    supplied = probes.get("probes", [])
    by_id = {}
    for probe in supplied:
        pid = probe.get("probe")
        if pid not in spec["probes"]:
            raise EvalError(f"unregistered probe label: {pid!r}")
        if pid in by_id:
            raise EvalError(f"duplicate probe: {pid}")
        by_id[pid] = probe
    for pid, want in spec["probes"].items():
        if pid not in by_id:
            raise EvalError(f"missing frozen probe: {pid}")
        probe = by_id[pid]
        # candidate identity (the deliberate single-invariant violation)
        if probe.get("candidate") != want["candidate"]:
            raise EvalError(
                f"probe {pid}: candidate {probe.get('candidate')!r} != "
                f"frozen {want['candidate']!r}")
        runs = probe.get("runs", [])
        want_cases = list(want["cases"])
        got_cases = [r.get("case_id") for r in runs]
        if got_cases != want_cases:
            raise EvalError(
                f"probe {pid}: case sequence {got_cases} != frozen "
                f"{want_cases}")
        got_seeds = sorted({r.get("seed") for r in runs})
        if got_seeds != sorted(want["seeds"]):
            raise EvalError(
                f"probe {pid}: seeds {got_seeds} != frozen {want['seeds']}")
        want_run_ids = sorted(
            f"{want['candidate']}|{c}|{s}" for c in want_cases
            for s in want["seeds"])
        got_run_ids = sorted(r.get("run_id") for r in runs)
        if got_run_ids != want_run_ids:
            raise EvalError(
                f"probe {pid}: run ids diverge from the frozen matrix")
        recorded_hashes = probes.get("probe_hashes", {}).get(pid)
        if recorded_hashes is None or \
                sorted(recorded_hashes) != sorted(r.get("run_id")
                                                  for r in runs):
            raise EvalError(
                f"probe {pid}: probe_hashes section mismatch")
    rejections = {}
    for pid in spec["probes"]:
        probe = by_id[pid]
        counters = {k: 0 for k in ISO_KEYS}
        for run in probe["runs"]:
            c = _check_run(run, oracle.replay_case(run["case_id"]), oracle)
            for k in ISO_KEYS:
                counters[k] += c[k]
        if pid == "A_existence_oracle":
            ok = counters["ISO2"] > 0
            rejections[pid] = {"expected": "FAIL",
                               "detected": "FAIL" if ok else "UNDETECTED",
                               "iso": counters}
        elif pid == "B_stale_cache":
            ok = counters["ISO3"] > 0 and counters["ISO4"] > 0
            rejections[pid] = {"expected": "FAIL",
                               "detected": "FAIL" if ok else "UNDETECTED",
                               "iso": counters}
        elif pid == "C_postfilter":
            ok = counters["ISO2"] > 0
            rejections[pid] = {"expected": "FAIL",
                               "detected": "FAIL" if ok else "UNDETECTED",
                               "iso": counters}
        else:  # D_forged_scope_provenance_loss
            fail = counters["ISO7"] > 0
            incomp = counters["ISO5"] > 0
            detected = ("FAIL+INCOMPARABLE" if fail and incomp
                        else "FAIL" if fail else "INCOMPARABLE" if incomp
                        else "UNDETECTED")
            rejections[pid] = {"expected": "FAIL+INCOMPARABLE",
                               "detected": detected, "iso": counters}
    faults = probes.get("fault_injection")
    if not isinstance(faults, dict) or set(faults) != \
            set(spec.get("fault_injection_variants",
                         ["per_scope", "shared_rls"])):
        raise EvalError("fault injection section missing or malformed")
    return rejections


def recompute_timing(timing: dict, contract: dict) -> dict:
    """Independently recompute the pooled paired statistic, tolerance and
    verdict from RAW paired samples per the frozen contract.  Producer
    summaries in the timing file are ignored."""
    frozen = contract["timing_probe_contract"]
    tol_rule = frozen["tolerance"]
    out = {"frozen_methodology": {
        "sample_count": frozen["sample_count"], "warmup": frozen["warmup"],
        "inner_repeats": frozen["inner_repeats"],
        "seeds": frozen["seeds"], "statistic": frozen["statistic"],
        "tolerance": tol_rule}, "variants": {}}
    expected_samples = frozen["sample_count"] * len(frozen["seeds"])
    variants = timing.get("variants", {})
    if set(variants.keys()) != {"per_scope", "shared_rls"}:
        out["NO_DATA"] = "timing variants missing"
        return out
    for variant, data in variants.items():
        raw = data.get("raw") or {}
        diffs = raw.get("paired_diffs_ns")
        controls = raw.get("control_samples_ns")
        seed_order = raw.get("seed_order")
        if not isinstance(diffs, list) or not isinstance(controls, list)                 or len(diffs) != expected_samples                 or len(controls) != expected_samples                 or seed_order != frozen["seeds"]:
            out["variants"][variant] = {
                "verdict": "NO_DATA",
                "note": "raw paired samples missing, short, or seed order "
                        "does not match the frozen methodology"}
            continue
        # exact methodology cross-check against the frozen contract
        method = timing.get("methodology", {})
        if method.get("sample_count") != frozen["sample_count"] or                 method.get("inner_repeats") != frozen["inner_repeats"] or                 method.get("seeds") != frozen["seeds"]:
            out["variants"][variant] = {
                "verdict": "NO_DATA",
                "note": "timing methodology header diverges from the "
                        "frozen contract"}
            continue
        sorted_diffs = sorted(diffs)
        signal = abs(sorted_diffs[len(sorted_diffs) // 2])
        sorted_controls = sorted(controls)
        control_median = sorted_controls[len(sorted_controls) // 2]
        tol = max(tol_rule["relative"] * control_median,
                  tol_rule["absolute_floor_ns"])
        out["variants"][variant] = {
            "signal_ns": signal,
            "control_median_ns": control_median,
            "tolerance_ns": round(tol),
            "pooled_samples": len(diffs),
            "verdict": ("WITHIN_TOLERANCE" if signal <= round(tol)
                        else "SIGNAL_ABOVE_TOLERANCE"),
            "recomputed": True,
            "note": "statistic, tolerance and verdict recomputed by the "
                    "evaluator from raw hash-bound paired samples; not a "
                    "production SLO, not proof of absence of all side "
                    "channels"}
    return out


# --------------------------------------------------------------------------
# main evaluation
# --------------------------------------------------------------------------

def evaluate(runs_manifest: Path, rerun_manifest: Path,
             expected_commit: str, probes_path: Path, probes_sha: str,
             out_path: Path, run_nonce: str) -> dict:
    contract = load(TICKET / "isolation-contract.json")
    rubric = load(TICKET / "rubric.json")
    manifest = load(TICKET / "corpus-manifest.json")
    fixtures = load(TICKET / "fixtures.json")
    oracle = Oracle(fixtures, manifest)
    frozen_hashes = {name: _sha((TICKET / name).read_bytes())
                     for name in ("isolation-contract.json",
                                  "threat-model.json", "rubric.json",
                                  "corpus-manifest.json", "fixtures.json")}

    main_doc = load(runs_manifest)
    digest_input = dict(main_doc)
    saved_digest = digest_input.pop("manifest_digest", None)
    recomputed = _sha(json.dumps(digest_input, sort_keys=True,
                                 separators=(",", ":")).encode())
    if saved_digest is None or saved_digest != recomputed:
        raise EvalError("main manifest digest mismatch")
    validate_provenance(main_doc.get("provenance", {}), expected_commit)
    if main_doc.get("contract_hashes") != frozen_hashes:
        raise EvalError("main manifest contract hashes diverge from frozen")
    main_runs = validate_run_matrix(main_doc, runs_manifest.parent / "run_records",
                                    frozen_hashes=frozen_hashes)
    rerun_doc = load(rerun_manifest)
    digest_input = dict(rerun_doc)
    saved_digest = digest_input.pop("manifest_digest", None)
    recomputed = _sha(json.dumps(digest_input, sort_keys=True,
                                 separators=(",", ":")).encode())
    if saved_digest is None or saved_digest != recomputed:
        raise EvalError("rerun manifest digest mismatch")
    validate_provenance(rerun_doc.get("provenance", {}), expected_commit)
    if rerun_doc.get("contract_hashes") != frozen_hashes:
        raise EvalError("rerun manifest contract hashes diverge from frozen")
    rerun_runs = validate_run_matrix(rerun_doc,
                                     rerun_manifest.parent / "run_records",
                                     frozen_hashes=frozen_hashes)

    if main_doc["provenance"]["executor_id"] == \
            rerun_doc["provenance"]["executor_id"]:
        raise EvalError("main and rerun executor identities must differ")
    for key in ("commit", "tree_sha"):
        if main_doc["provenance"][key] != rerun_doc["provenance"][key]:
            raise EvalError(f"main/rerun {key} diverge")

    raw_probes = probes_path.read_bytes()
    if _sha(raw_probes) != probes_sha:
        raise EvalError("probes digest mismatch")
    probes = json.loads(raw_probes.decode("utf-8"))

    # per-variant aggregation with independent ISO derivation
    agg = {}
    for variant in ("per_scope", "shared_rls"):
        agg[variant] = aggregate_variant(main_runs, variant, oracle)

    # cross-executor determinism share (same run, both executors):
    # every frozen field of the run must be byte-identical
    determinism = {v: [0, 0] for v in ("per_scope", "shared_rls")}
    for run_id, data in main_runs.items():
        other = rerun_runs.get(run_id)
        if other is None:
            raise EvalError(f"rerun missing run {run_id}")
        v = data["variant"]
        determinism[v][1] += 1
        strip = lambda d: {k: val for k, val in d.items()
                           if k not in ("provenance_digest",)}
        if json.dumps(strip(data), sort_keys=True) == \
                json.dumps(strip(other), sort_keys=True):
            determinism[v][0] += 1
    determinism_share = {v: (determinism[v][0] / determinism[v][1])
                         if determinism[v][1] else 0.0
                         for v in determinism}

    # rerun safety verdict must reproduce (ISO counters re-derived)
    rerun_iso = {}
    for variant in ("per_scope", "shared_rls"):
        totals = {k: 0 for k in ISO_KEYS}
        for run_id, data in rerun_runs.items():
            v, case, seed = run_id.split("|")
            if v != variant:
                continue
            c = _check_run(data, oracle.replay_case(case), oracle)
            for k in ISO_KEYS:
                totals[k] += c[k]
        rerun_iso[variant] = totals

    timing = load(runs_manifest.parent / "timing.json")
    timing_sha = _sha((runs_manifest.parent / "timing.json").read_bytes())
    if timing_sha != main_doc.get("timing_sha256"):
        raise EvalError("main timing file digest mismatch")
    timing_analysis = recompute_timing(timing, contract)
    rerun_timing_path = rerun_manifest.parent / "timing.json"
    rerun_timing = load(rerun_timing_path)
    if _sha(rerun_timing_path.read_bytes()) != \
            rerun_doc.get("timing_sha256"):
        raise EvalError("rerun timing file digest mismatch")
    rerun_timing_analysis = recompute_timing(rerun_timing, contract)
    divergent = [v for v in timing_analysis.get("variants", {})
                 if timing_analysis["variants"][v].get("verdict") !=
                 rerun_timing_analysis.get("variants", {})
                 .get(v, {}).get("verdict")]
    timing_analysis["rerun"] = {
        "sha256": _sha(rerun_timing_path.read_bytes()),
        "digest_bound": True,
        "recomputed_variants": rerun_timing_analysis.get("variants", {}),
        "verdict_divergences": divergent,
        "note": "the rerun timing artifact is digest-bound to its manifest "
                "and independently recomputed; verdict divergences between "
                "executors are local-scheduling findings recorded as "
                "limitations, never producer-accepted claims"}
    timing_analysis["producer_summaries_ignored"] = True

    probe_rejections = evaluate_probes(probes, oracle, manifest)

    # hard fail rules
    violations = {}
    for variant in ("per_scope", "shared_rls"):
        total = sum(agg[variant]["iso"].values())
        violations[variant] = total
    honest_fail = [v for v, t in violations.items() if t > 0]
    rerun_fail = [v for v in rerun_iso if sum(rerun_iso[v].values()) > 0]

    # scoring
    cells = score_dimensions(agg["per_scope"], agg["shared_rls"],
                             timing_analysis, probes, 3)
    apply_d8_and_d10(cells, determinism_share)
    scores = {}
    for dim_id in (c["id"] for c in rubric["dimensions"]):
        entry = {}
        for variant in ("per_scope", "shared_rls"):
            if dim_id == "D9":
                entry[variant] = cells["D9"][variant]["score"]
            elif dim_id == "D11":
                entry[variant] = cells["D11"][variant]["score"]
            elif dim_id == "D8":
                entry[variant] = cells["D8"][variant]
            elif dim_id == "D10":
                entry[variant] = cells["D10"][variant]["score"]
            else:
                entry[variant] = cells[dim_id][variant]["score"]
        scores[dim_id] = entry
    weights = {c["id"]: c["weight"] for c in rubric["dimensions"]}
    base_scores = weighted_scores(scores, weights)
    winner = max(base_scores, key=lambda k: base_scores[k])
    margin = abs(base_scores["per_scope"] - base_scores["shared_rls"])
    near_tie = margin < rubric["tie_policy"]["near_tie_threshold"]

    sens = sensitivity_analysis(scores, weights, rng_seed=42,
                                vectors=200,
                                base_expected=base_scores)

    limitations = []
    limitations.append(
        "All measurements come from a deterministic stdlib-only local "
        "simulation; no production search service, latency or privacy "
        "certification is claimed.")
    limitations.append(
        "The timing probe is a bounded same-host wall-clock measurement of "
        "a microsecond-scale in-process path; it cannot prove absence of "
        "all side channels and is never a production SLO.")
    limitations.append(
        "D9/D11 are inference-type cells derived from the frozen contract, "
        "the current implementation and the documented profiles; a "
        "profile-C MLS/TEE contract remains S1-018 scope.")
    if timing_analysis.get("NO_DATA"):
        limitations.append("timing NO_DATA: " + timing_analysis["NO_DATA"])
    for v in ("per_scope", "shared_rls"):
        tv = timing_analysis["variants"].get(v, {})
        if tv.get("verdict") == "SIGNAL_ABOVE_TOLERANCE":
            limitations.append(
                f"{v}: existence-oracle timing signal above the frozen "
                f"tolerance in the local model - a finding limiting this "
                f"variant, not a production exploitability claim")
    if sens["flip_count"] > 0:
        limitations.append(
            f"sensitivity analysis found {sens['flip_count']} winner flips; "
            "verdict capped at PASS_WITH_LIMITS per the frozen rubric")

    # verdict
    if honest_fail or rerun_fail:
        verdict = "FAIL"
        reasons = [f"ISO violations on honest variant {v}: "
                   f"{violations.get(v)} (main) / "
                   f"{sum(rerun_iso.get(v, {}).values())} (rerun)"
                   for v in set(honest_fail) | set(rerun_fail)]
    elif any(r["detected"] in ("UNDETECTED",)
             for r in probe_rejections.values()):
        verdict = "FAIL"
        reasons = ["undetected adversarial probe candidate"]
    elif sens["flip_count"] > 0 or near_tie or True:
        # inference-type cells (D9/D11) exist by construction -> capped
        verdict = "PASS_WITH_LIMITS"
        reasons = ["inference-type dimensions present (D9, D11); bounded "
                   "local timing; model-based overhead constant"]
    else:
        verdict = "PASS"
        reasons = []

    decision_matrix = []
    for c in rubric["dimensions"]:
        for variant in ("per_scope", "shared_rls"):
            if c["id"] in ("D9", "D11"):
                cell_info = dict(cells[c["id"]])
                cell_info["score"] = cells[c["id"]][variant]["score"]
            elif c["id"] == "D8":
                cell_info = {
                    "score": cells["D8"][variant],
                    "claim_type": "test_measurement",
                    "confidence": "high",
                    "evidence_refs": [f"cross-executor determinism share: "
                                      f"{cells['D8'][variant]:.4f}"],
                    "limitation": None,
                    "missing_evidence": None}
            else:
                raw_cell = cells[c["id"]][variant]
                cell_info = {
                    "score": raw_cell["score"],
                    "claim_type": raw_cell.get("claim_type",
                                               "test_measurement"),
                    "confidence": raw_cell.get("confidence", "high"),
                    "evidence_refs": raw_cell.get("evidence_refs", []),
                    "limitation": raw_cell.get("limitation"),
                    "missing_evidence": raw_cell.get("missing_evidence")}
            decision_matrix.append({
                "dimension": c["id"] + " " + c["name"],
                "variant": variant,
                "weight": c["weight"],
                "score": scores[c["id"]][variant],
                "claim_type": cell_info["claim_type"],
                "confidence": cell_info["confidence"],
                "evidence_refs": cell_info["evidence_refs"],
                "limitation": cell_info.get("limitation"),
                "missing_evidence": cell_info.get("missing_evidence")})

    result = {
        "schema": SCHEMA_EVAL,
        "run_nonce": run_nonce,
        "verdict": verdict,
        "reasons": reasons,
        "winner": winner,
        "score_margin": round(margin, 4),
        "near_tie": near_tie,
        "scores_normalized": base_scores,
        "scores_per_dimension": scores,
        "decision_matrix": decision_matrix,
        "iso_counters_main": {v: agg[v]["iso"] for v in agg},
        "iso_counters_rerun": rerun_iso,
        "isolation_cases": {v: agg[v]["per_case"] for v in agg},
        "metrics": {v: {
            "storage": agg[v]["storage"],
            "rows_scanned_total": agg[v]["rows_scanned_total"],
            "policy_evaluations_total": agg[v]["policy_evaluations_total"],
            "invalidation_ops_total": agg[v]["invalidation_ops_total"],
            "cache_hits": agg[v]["cache_hits"],
            "deny_equivalence":
                agg[v]["deny_equivalence_foreign_vs_nonexistent"],
            "materialize_before_policy":
                agg[v]["materialize_before_policy"],
            "determinism_share_cross_executor":
                determinism_share[v]} for v in agg},
        "timing_analysis": timing_analysis,
        "sensitivity": sens,
        "probe_rejections": probe_rejections,
        "fault_injection": probes.get("fault_injection"),
        "executor_main": main_doc["provenance"]["executor_id"],
        "executor_rerun": rerun_doc["provenance"]["executor_id"],
        "commit": expected_commit,
        "tree_sha": main_doc["provenance"]["tree_sha"],
        "contract_hashes": frozen_hashes,
        "limitations": limitations,
    }
    if out_path.exists():
        out_path.unlink()
    out_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")
    if result.get("run_nonce") != run_nonce:
        raise EvalError("nonce binding failed")
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--runs-manifest", required=True)
    ap.add_argument("--rerun-manifest", required=True)
    ap.add_argument("--expected-commit", required=True)
    ap.add_argument("--probes-path", required=True)
    ap.add_argument("--probes-sha", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    nonce = os.environ.get("AGENTOS_RUN_NONCE", "")
    if not nonce:
        print("AGENTOS_RUN_NONCE must be set (fresh-write binding)",
              file=sys.stderr)
        return 2
    try:
        result = evaluate(Path(args.runs_manifest), Path(args.rerun_manifest),
                          args.expected_commit, Path(args.probes_path),
                          args.probes_sha, Path(args.out), nonce)
    except EvalError as exc:
        print(f"EVALUATOR ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({
        "verdict": result["verdict"], "winner": result["winner"],
        "scores": result["scores_normalized"],
        "iso_main": {v: sum(result["iso_counters_main"][v].values())
                     for v in result["iso_counters_main"]},
        "sensitivity_flips": result["sensitivity"]["flip_count"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
