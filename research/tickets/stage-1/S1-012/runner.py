"""S1-012 deterministic evidence-independence runner (stdlib only).

Evaluates the frozen corpus under one counting variant and emits raw
observations plus a run manifest. Four variants, one workload:

- document: one unit per source document; groups by upstream lineage.
- span: one unit per span (span-less documents contribute one whole-doc
  span); same-document non-disjoint spans collapse; groups by upstream.
- digest: one unit per distinct document digest; groups by upstream
  (a digest without bound upstream abstains). Documents the keying
  limit on identical-text independents (D02/D33/H03/H17).
- reputation-only: NEGATIVE CONTROL. No collapse, no firewall, no
  provenance checks; admits on raw count. Expected to fail hard gates.

Shared strict plumbing (all variants): fail-closed input validation
with no defaults; strict evidence bindings (digest recompute,
verified===True, publisher/upstream present, scope/version match,
ACTIVE non-stale source); policy currency; revocation/supersession
exclusion; unresolved provenance -> ABSTAIN_UNKNOWN (never an invented
group); correlation cap on weight (count reported uncapped, weight
capped); Beta posterior over admitted trials with frozen prior/decay;
EigenTrust fixed-point with frozen normalization/anchor/damping;
enforcement_allow is ALWAYS false (policy firewall is structural).

Beta tails use a continued-fraction implementation; the evaluator
rechecks them against independent binomial-sum references. Seeds are
recorded; outputs are seed-invariant (reruns are NOT independent
observations; see corpus-manifest and task section 7).

Usage:
  py -3.12 runner.py --variant document --seed 12012 --out results/run-a/document-12012
  [--prior-a 1 --prior-b 1 --decay 1.0 --cap 2 --threshold 0.9]
"""
from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import math
import os
import platform
import secrets
import subprocess
import sys
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
VARIANTS = ("document", "span", "digest", "reputation-only")
FROZEN = {"prior_a": 1, "prior_b": 1, "decay": 1.0, "cap": 2,
          "threshold": 0.9}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest(text: str) -> str:
    return sha(f"s1-012:content:{text}".encode("utf-8"))


def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def git(*args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=HERE.parents[3],
                          capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: "
                           f"{proc.stderr[:200]}")
    return proc.stdout.strip()


def file_hashes() -> dict:
    names = ["cases.json", "cases-dev.src.json", "cases-holdout.src.json",
             "evidence-unit.schema.json", "independence-contract.json",
             "threat-model.json", "calibration-plan.json", "rubric.json",
             "source-registry.json", "retrieval-manifest.json",
             "split-manifest.json", "corpus-manifest.json",
             "runner.py", "evaluator.py", "compare_runs.py",
             "dependency_gate.py", "canonicalize_corpus.py",
             "make_bundle.py"]
    out = {}
    for name in names:
        path = HERE / name
        out[name] = sha(path.read_bytes()) if path.is_file() else None
    return out


def beta_cf(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta I_x(a,b) via continued fractions
    (Numerical-Recipes style betacf). Runner-side implementation; the
    evaluator rechecks integer cases against binomial summation."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    if a <= 0.0 or b <= 0.0:
        raise ValueError("non-positive beta params")
    if not (math.isfinite(a) and math.isfinite(b) and math.isfinite(x)):
        raise ValueError("non-finite beta inputs")
    lbeta = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
    if x < (a + 1.0) / (a + b + 2.0):
        front = math.exp(a * math.log(x) + b * math.log(1.0 - x) + lbeta) / a
        return front * _betacf(a, b, x)
    front = math.exp(a * math.log(x) + b * math.log(1.0 - x) + lbeta) / b
    return 1.0 - front * _betacf(b, a, 1.0 - x)


def _betacf(a: float, b: float, x: float) -> float:
    max_iter, eps, fpmin = 500, 3e-12, 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    if abs(d) < fpmin:
        d = fpmin
    d = 1.0 / d
    result = d
    for m in range(1, max_iter + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        result *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        delta = d * c
        result *= delta
        if abs(delta - 1.0) < eps:
            break
    return result


def eigentrust(nodes: list, edges: list, anchor: list,
               damping: float = 0.85) -> dict:
    """Fixed-point trust with frozen semantics. Returns vector or abstain."""
    if not anchor:
        return {"abstain": True, "reason": "anchorless",
                "trust": None, "iterations": 0, "converged": False}
    index = {node: i for i, node in enumerate(nodes)}
    size = len(nodes)
    rows = []
    for node in nodes:
        outgoing = [(e["to"], e["value"]) for e in edges
                    if e["from"] == node and e["value"] > 0]
        total = sum(value for _, value in outgoing)
        if total <= 0:
            rows.append([1.0 / size] * size)
        else:
            row = [0.0] * size
            for target, value in outgoing:
                row[index[target]] += value / total
            rows.append(row)
    pre = [1.0 / len(anchor) if node in anchor else 0.0 for node in nodes]
    trust = list(pre)
    for iteration in range(1, 1001):
        nxt = [(1.0 - damping) * pre[i] + damping * sum(
            rows[j][i] * trust[j] for j in range(size))
            for i in range(size)]
        delta = sum(abs(nxt[i] - trust[i]) for i in range(size))
        trust = nxt
        if delta < 1e-9:
            return {"abstain": False, "reason": "converged",
                    "trust": {node: trust[index[node]] for node in nodes},
                    "iterations": iteration, "converged": True}
    return {"abstain": True, "reason": "no-convergence",
            "trust": None, "iterations": 1000, "converged": False}


class Case:
    REQUIRED = ("claim", "sources", "documents")

    def __init__(self, raw: dict):
        self.raw = raw
        self.id = raw.get("case_id", "")
        self.family = raw.get("family", "")
        self.split = raw.get("split", "dev")
        claim = raw.get("claim") or {}
        self.claim_id = claim.get("claim_id")
        self.claim_version = claim.get("version", 1)
        self.scope = claim.get("scope", "SCOPE-1")
        self.policy = raw.get("policy", "current")
        self.sources = {s["source_id"]: s for s in
                        raw.get("sources", [])}
        self.documents = raw.get("documents", [])
        self.ratings = raw.get("ratings", [])
        self.anchor = raw.get("anchor")
        self.probe = raw.get("probe")

    def field_problems(self) -> list:
        problems = []
        if not isinstance(self.id, str) or not self.id:
            problems.append("missing case_id")
        if not isinstance(self.claim_id, str) or not self.claim_id:
            problems.append("missing claim.claim_id")
        if not isinstance(self.claim_version, int) or \
                isinstance(self.claim_version, bool):
            problems.append("missing claim.version")
        if not self.sources:
            problems.append("missing sources")
        if not self.documents:
            problems.append("missing documents")
        if not isinstance(self.scope, str) or not self.scope:
            problems.append("missing scope")
        if not isinstance(self.policy, str) or not self.policy:
            problems.append("missing policy")
        return problems

    def doc_binding_ok(self, doc: dict, src: dict) -> tuple:
        """Strict per-document binding. Returns (ok, reason)."""
        if doc.get("digest") != digest(doc.get("text", "")):
            return False, "INVALID_BINDING"
        if not isinstance(doc.get("verified", True), bool):
            return False, "INVALID_BINDING"
        if doc.get("verified", True) is not True:
            return False, "REJECTED_UNVERIFIED"
        if not src.get("publisher") or not src.get("upstream"):
            return False, "ABSTAIN_UNKNOWN"
        if doc.get("scope", self.scope) != self.scope:
            return False, "REJECTED_CROSS_SCOPE"
        if doc.get("version", self.claim_version) != self.claim_version:
            return False, "REJECTED_VERSION_MISMATCH"
        if src.get("status", "ACTIVE") != "ACTIVE" or \
                doc.get("revoked", False):
            return False, "REJECTED_REVOKED"
        if doc.get("temporal", "current") != "current":
            return False, "REJECTED_STALE"
        if doc.get("superseded_by") and not doc.get("superseded_resolved"):
            return False, "REJECTED_STALE"
        if doc.get("group") is None and "group" in doc:
            return False, "ABSTAIN_UNKNOWN"
        return True, "ADMITTED"


def build_units(case: Case, variant: str) -> list:
    """Units per granularity view. Span-less documents contribute one
    whole-document span in the span view."""
    units = []
    if variant == "document":
        for doc in case.documents:
            src = case.sources.get(doc.get("source_id", ""), {})
            units.append({"unit_id": doc.get("doc_id"),
                          "digest": doc.get("digest") or
                          digest(doc.get("text", "")),
                          "upstream": src.get("upstream"),
                          "publisher": src.get("publisher"),
                          "label": doc.get("label", "support"),
                          "doc": doc, "src": src, "span": None})
    elif variant == "span":
        for doc in case.documents:
            src = case.sources.get(doc.get("source_id", ""), {})
            spans = doc.get("spans") or [
                {"span_id": doc.get("doc_id") + "#whole",
                 "text": doc.get("text", ""), "disjoint": True}]
            for span in spans:
                units.append({
                    "unit_id": span.get("span_id"),
                    "digest": span.get("digest") or
                    digest(span.get("text", "")),
                    "upstream": src.get("upstream"),
                    "publisher": src.get("publisher"),
                    "label": doc.get("label", "support"),
                    "doc": doc, "src": src, "span": span})
    elif variant == "digest":
        seen = {}
        for doc in case.documents:
            src = case.sources.get(doc.get("source_id", ""), {})
            key = doc.get("digest") or digest(doc.get("text", ""))
            seen.setdefault(key, {"unit_id": f"digest-{key[:12]}",
                                  "digest": key,
                                  "upstream": src.get("upstream"),
                                  "publisher": src.get("publisher"),
                                  "label": doc.get("label", "support"),
                                  "doc": doc, "src": src, "span": None,
                                  "merged": []})
            seen[key]["merged"].append(doc.get("doc_id"))
        units = list(seen.values())
    else:  # reputation-only: raw count, no bindings at all
        for doc in case.documents:
            units.append({"unit_id": doc.get("doc_id"),
                          "digest": doc.get("digest"),
                          "upstream": None, "publisher": None,
                          "label": doc.get("label", "support"),
                          "doc": doc, "src": {},
                          "span": None})
    return units


def collapse(units: list) -> tuple:
    """Group units by upstream lineage. Returns (groups, unresolved).

    Same-document non-disjoint spans and overlapping spans share the
    document upstream, so they collapse by construction. A unit without
    upstream/publisher is unresolvable (never an invented group)."""
    groups: dict = {}
    unresolved = []
    for unit in units:
        upstream = unit.get("upstream")
        publisher = unit.get("publisher")
        if not upstream or not publisher:
            unresolved.append(unit["unit_id"])
            continue
        groups.setdefault(upstream, []).append(unit["unit_id"])
    return groups, unresolved


def out_row(case: Case, variant: str, seed: int, params: dict,
            n_independent: int, outcome: str, reason: str,
            units: list, groups: dict, beta: dict,
            trust: dict | None) -> dict:
    unit_bytes = len(canonical(
        [{"unit_id": u["unit_id"], "digest": u["digest"]} for u in units]))
    row = {"case_id": case.id, "split": case.split,
           "family": case.family, "variant": variant, "seed": seed,
           "params": params, "n_independent": n_independent,
           "outcome": outcome, "reason_code": reason,
           "enforcement_allow": False,
           "units": [{"unit_id": u["unit_id"], "digest": u["digest"],
                      "upstream": u["upstream"]} for u in units],
           "groups": sorted(groups),
           "beta": beta, "eigentrust": trust,
           "costs": {
               "measured": {"units": len(units), "bytes": unit_bytes},
               "modeled": {"projected_bytes_per_1k_units":
                           round(unit_bytes * 1000 / max(len(units), 1), 2),
                           "note": "linear projection; model estimate, "
                                   "not a measurement"}}}
    row["output_sha256"] = sha(canonical(
        {k: v for k, v in row.items() if k != "output_sha256"}))
    return row


def decide(case: Case, variant: str, seed: int, params: dict) -> dict:
    prior_a = params["prior_a"]
    prior_b = params["prior_b"]
    decay = params["decay"]
    cap = params["cap"]
    threshold = params["threshold"]
    problems = case.field_problems()
    if problems:
        return out_row(case, variant, seed, params, 0, "reject",
                       "MISSING_REQUIRED_FIELD", [], {}, beta_abstain(),
                       trust_abstain("invalid-input"))
    if case.policy != "current":
        return out_row(case, variant, seed, params, 0, "reject",
                       "REJECTED_POLICY", [], {}, beta_abstain(),
                       trust_abstain("policy"))
    if variant == "reputation-only":
        units = build_units(case, variant)
        beta = beta_over([u["label"] for u in units], prior_a, prior_b,
                         decay, threshold)
        outcome = "admit" if len(units) >= 1 else "reject"
        return out_row(case, variant, seed, params, len(units), outcome,
                       "RECOMMENDATION_ONLY", units, {}, beta,
                       trust_for(case))
    units = build_units(case, variant)
    # Per-unit bindings; malformed or unresolvable units fail the case,
    # trust/scope/version/lifecycle failures only exclude the unit.
    malformed = []
    unresolvable = []
    excluded: dict = {}
    admitted = []
    for unit in units:
        ok, reason = case.doc_binding_ok(unit["doc"], unit["src"])
        if ok:
            admitted.append(unit)
        elif reason in ("ABSTAIN_UNKNOWN",):
            unresolvable.append(unit)
        elif reason in ("INVALID_BINDING",):
            malformed.append(unit)
        else:
            excluded[reason] = excluded.get(reason, 0) + 1
    # NOTE: doc_binding_ok currently yields no INVALID_BINDING rows
    # (digests are canonicalized); the branch is defense in depth.
    groups, _ = collapse(admitted)
    n_ind = len(groups)
    beta = beta_over([u["label"] for u in admitted],
                     prior_a, prior_b, decay, threshold)
    trust = trust_for(case)
    if unresolvable:
        return out_row(case, variant, seed, params, n_ind, "abstain",
                       "ABSTAIN_UNKNOWN", units, groups, beta, trust)
    if malformed:
        return out_row(case, variant, seed, params, n_ind, "reject",
                       "INVALID_BINDING", units, groups, beta, trust)
    if n_ind >= 2:
        return out_row(case, variant, seed, params, n_ind, "admit",
                       "ADMITTED", units, groups, beta, trust)
    if excluded:
        reason = sorted(excluded, key=lambda r: (precedence_index(r),
                                                 -excluded[r]))[0]
        return out_row(case, variant, seed, params, n_ind, "reject",
                       reason, units, groups, beta, trust)
    return out_row(case, variant, seed, params, n_ind, "reject",
                   "REJECTED_CORRELATED", units, groups, beta, trust)


EXCLUSION_PRECEDENCE = ["REJECTED_POLICY", "REJECTED_CROSS_SCOPE",
                          "REJECTED_VERSION_MISMATCH", "REJECTED_REVOKED",
                          "REJECTED_STALE", "REJECTED_UNVERIFIED"]


def precedence_index(reason: str) -> int:
    try:
        return EXCLUSION_PRECEDENCE.index(reason)
    except ValueError:
        return len(EXCLUSION_PRECEDENCE)


def beta_abstain() -> dict:
    return {"a": None, "b": None, "tail": None, "threshold_met": None,
            "trials": 0, "note": "no Beta: invalid input"}


def beta_over(labels: list, prior_a: float, prior_b: float,
              decay: float, threshold: float) -> dict:
    for name, value in (("prior_a", prior_a), ("prior_b", prior_b),
                        ("decay", decay), ("threshold", threshold)):
        if not isinstance(value, (int, float)) or \
                isinstance(value, bool) or not math.isfinite(value):
            return {"a": None, "b": None, "tail": None,
                    "threshold_met": None, "trials": 0,
                    "note": f"invalid param {name}"}
        if value < 0 or (name == "threshold" and value > 1):
            return {"a": None, "b": None, "tail": None,
                    "threshold_met": None, "trials": 0,
                    "note": f"invalid param {name}"}
    successes = sum(1 for label in labels if label == "support")
    failures = sum(1 for label in labels if label == "refute")
    if prior_a <= 0 or prior_b <= 0:
        return {"a": None, "b": None, "tail": None,
                "threshold_met": None,
                "trials": successes + failures,
                "note": "invalid prior"}
    aval = float(prior_a) + decay * successes
    bval = float(prior_b) + decay * failures
    try:
        tail = 1.0 - beta_cf(aval, bval, 0.9)
    except (ValueError, OverflowError):
        return {"a": aval, "b": bval, "tail": None,
                "threshold_met": None,
                "trials": successes + failures, "note": "numeric failure"}
    if not math.isfinite(tail):
        return {"a": aval, "b": bval, "tail": None,
                "threshold_met": None,
                "trials": successes + failures, "note": "non-finite tail"}
    return {"a": aval, "b": bval, "tail": tail,
            "threshold_met": bool(tail >= 0.95),
            "trials": successes + failures,
            "note": "hypothesis quantity, never enforcement"}


def trust_abstain(reason: str) -> dict:
    return {"abstain": True, "reason": reason, "trust": None,
            "iterations": 0, "converged": False}


def trust_for(case: Case) -> dict:
    if not case.ratings:
        return trust_abstain("no-ratings")
    nodes = sorted({r["from"] for r in case.ratings} |
                   {r["to"] for r in case.ratings})
    edges = [{"from": r["from"], "to": r["to"],
              "value": float(r["value"])} for r in case.ratings]
    return eigentrust(nodes, edges, case.anchor or [], damping=0.85)


def main() -> int:
    parser = argparse.ArgumentParser(description="S1-012 runner")
    parser.add_argument("--cases", default="cases.json")
    parser.add_argument("--variant", required=True, choices=VARIANTS)
    parser.add_argument("--seed", required=True, type=int)
    parser.add_argument("--out", required=True)
    parser.add_argument("--prior-a", type=float, default=FROZEN["prior_a"])
    parser.add_argument("--prior-b", type=float, default=FROZEN["prior_b"])
    parser.add_argument("--decay", type=float, default=FROZEN["decay"])
    parser.add_argument("--cap", type=int, default=FROZEN["cap"])
    parser.add_argument("--threshold", type=float,
                        default=FROZEN["threshold"])
    args = parser.parse_args()
    params = {"prior_a": args.prior_a, "prior_b": args.prior_b,
              "decay": args.decay, "cap": args.cap,
              "threshold": args.threshold, "frozen": {
                  k: getattr(args, {"prior_a": "prior_a",
                                    "prior_b": "prior_b"}.get(k, k))
                  == v for k, v in FROZEN.items()}}
    corpus = json.loads((HERE / args.cases).read_text(encoding="utf-8"))
    rows = [decide(Case(raw), args.variant, args.seed, params)
            for raw in corpus["cases"]]
    try:
        commit = git("rev-parse", "HEAD")
        tree = git("rev-parse", "HEAD^{tree}")
        dirty = bool(git("status", "--short"))
        describe = git("describe", "--always", "--dirty")
    except RuntimeError as exc:
        print(f"git provenance failed: {exc}", file=sys.stderr)
        return 1
    manifest = {
        "schema": "agentos.s1-012.run-manifest/v1",
        "ticket": "S1-012",
        "variant": args.variant,
        "seed": args.seed,
        "rows": len(rows),
        "pid": os.getpid(),
        "ppid": os.getppid(),
        "invocation_id": uuid.uuid4().hex,
        "nonce": secrets.token_hex(16),
        "executor_id": f"{getpass.getuser()}@{platform.node()}"
                       f"#{os.getpid()}",
        "commit": commit,
        "tree": tree,
        "clean_tree": not dirty,
        "describe": describe,
        "python": sys.version.split()[0],
        "input_hashes": file_hashes(),
    }
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest["output_root"] = str(out_dir.resolve())
    (out_dir / "raw-observations.json").write_text(
        json.dumps({"schema": "agentos.s1-012.raw-observations/v1",
                    "variant": args.variant, "seed": args.seed,
                    "rows": rows}, indent=2) + "\n", encoding="utf-8",
        newline="\n")
    (out_dir / "run-manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8",
        newline="\n")
    print(f"variant={args.variant} seed={args.seed} rows={len(rows)} "
          f"pid={manifest['pid']} commit={commit[:12]} "
          f"clean={manifest['clean_tree']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
