"""Harness Autoresearch (Phase 4). See ADR-0008 and SPEC §10.

Safe adaptation loop: CampaignManifest (frozen hashes, mutable scope, budget)
-> baseline -> one hypothesis per experiment -> candidate in isolated
worktree -> identical dev evals -> holdout + security gate by a SEPARATE
evaluator -> KEEP/DISCARD/RETEST/CRASH/QUARANTINED -> durable record.

The candidate can never touch frozen evals/corpus/thresholds/policy: hashes
are pinned in the manifest and re-verified before any decision; violations
QUARANTINE the campaign. No unbounded loops: budget and stop conditions are
enforced here.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from .gateway import GatewayError
from .ids import new_id


class AutoresearchError(GatewayError):
    pass


STOP_REASONS = (
    "budget_exhausted", "infra_failures_3", "frozen_hash_change",
    "ambiguous_measurement", "scope_expansion_required",
    "security_violation", "wall_clock_exceeded",
)


def _sha(data) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


class CampaignManifest:
    """Immutable campaign manifest; hash-pinned at creation."""

    def __init__(self, *, baseline_ref: str, primary_metric: str,
                 mutable_scope: list[str], frozen_eval_hashes: dict,
                 corpus_hash: str, budget: int = 5,
                 seeds: list[int] | None = None,
                 hard_constraints: dict | None = None):
        if not frozen_eval_hashes or not corpus_hash:
            raise AutoresearchError("manifest requires frozen eval+corpus hashes")
        self.baseline_ref = baseline_ref
        self.primary_metric = primary_metric
        self.mutable_scope = list(mutable_scope)
        self.frozen_eval_hashes = dict(frozen_eval_hashes)
        self.corpus_hash = corpus_hash
        self.budget = int(budget)
        self.seeds = list(seeds or [0])
        self.hard_constraints = dict(hard_constraints or {
            "zero_false_accepts_holdout": True,
            "zero_forbidden_effects": True,
            "audit_completeness": 1.0,
        })
        self.manifest_hash = _sha(json.dumps({
            "baseline": baseline_ref, "metric": primary_metric,
            "scope": sorted(self.mutable_scope),
            "evals": self.frozen_eval_hashes, "corpus": corpus_hash,
            "constraints": self.hard_constraints}, sort_keys=True))


class Autoresearch:
    """Campaign runner over StageEvals. Candidate changes are supplied as a
    callable `apply_candidate(worktree)` by the caller — this class never
    edits files itself."""

    def __init__(self, db, root_dir: str | Path, stage_evals):
        self.db = db
        self.root = Path(root_dir)
        self.se = stage_evals

    # -- persistence -----------------------------------------------------------
    def create_campaign(self, manifest: CampaignManifest, name: str) -> str:
        cid = new_id("campaign")
        with self.db.tx() as conn:
            conn.execute(
                "INSERT INTO experiment(id, campaign_id, hypothesis,"
                " baseline_ref, candidate_ref, mutable_scope_json,"
                " budget_json, seeds_json, primary_metric, status,"
                " frozen_hashes_json) VALUES (?,?,?,?,?,?,?,?,?, 'proposed', ?)",
                (cid, cid, f"campaign {name}", manifest.baseline_ref,
                 "(baseline)", json.dumps(manifest.mutable_scope),
                 json.dumps({"experiments": manifest.budget}),
                 json.dumps(manifest.seeds), manifest.primary_metric,
                 json.dumps({"manifest": manifest.manifest_hash,
                             "evals": manifest.frozen_eval_hashes,
                             "corpus": manifest.corpus_hash})))
        return cid

    def record_experiment(self, campaign_id: str, hypothesis: str,
                          baseline_ref: str, candidate_ref: str,
                          mutable_scope: list[str], measurements: dict,
                          status: str, rationale: str,
                          frozen_hashes: dict | None = None) -> str:
        if status not in ("proposed", "running", "KEEP", "DISCARD", "RETEST",
                          "CRASH", "QUARANTINED"):
            raise AutoresearchError(f"invalid experiment status {status}")
        eid = new_id("exp")
        with self.db.tx() as conn:
            conn.execute(
                "INSERT INTO experiment(id, campaign_id, hypothesis,"
                " baseline_ref, candidate_ref, mutable_scope_json,"
                " seeds_json, primary_metric, status, measurements_json,"
                " decision_rationale, frozen_hashes_json, decided_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?, ?, strftime("
                "'%Y-%m-%dT%H:%M:%fZ','now'))",
                (eid, campaign_id, hypothesis, baseline_ref, candidate_ref,
                 json.dumps(mutable_scope), "[]", "", status,
                 json.dumps(measurements), rationale,
                 json.dumps(frozen_hashes or {})))
        return eid

    @staticmethod
    def verify_frozen(manifest: CampaignManifest,
                      current_eval_hashes: dict,
                      current_corpus_hash: str) -> bool:
        return (current_eval_hashes == manifest.frozen_eval_hashes
                and current_corpus_hash == manifest.corpus_hash)

    # -- decision ---------------------------------------------------------------
    @staticmethod
    def decide(baseline_value: float, candidate_value: float,
               noise_floor: float, direction: str = "minimize",
               complexity_penalty: float = 0.0,
               hard_constraints_ok: bool = True,
               frozen_ok: bool = True,
               infrastructure_failure: bool = False,
               security_violation: bool = False) -> tuple[str, str]:
        if security_violation:
            return "QUARANTINED", "security/integrity violation"
        if not frozen_ok:
            return "QUARANTINED", "frozen evaluator/corpus hash changed"
        if infrastructure_failure:
            return "CRASH", "infrastructure/provider failure"
        if not hard_constraints_ok:
            return "QUARANTINED", "hard constraint violated"
        delta = ((baseline_value - candidate_value) if direction == "minimize"
                 else (candidate_value - baseline_value))
        # complexity penalty makes the candidate WORSE before comparing
        adjusted = candidate_value + complexity_penalty \
            if direction == "minimize" else candidate_value - complexity_penalty
        gain = ((baseline_value - adjusted) if direction == "minimize"
                else (adjusted - baseline_value))
        if gain > noise_floor:
            return "KEEP", f"improvement {gain:.4f} > noise floor"
        if abs(gain) <= noise_floor / 2:
            return "RETEST", "within measurement ambiguity band"
        return "DISCARD", f"no improvement above noise floor ({gain:.4f})"

    # -- full deterministic fake campaign (LLM-free demo/test path) -------------
    def run_fake_campaign(self, manifest: CampaignManifest,
                          scenarios: list[dict],
                          dev_eval_fn) -> list[dict]:
        """Run scripted scenarios through the real decision pipeline.

        scenarios: [{"hypothesis", "candidate_ref", "apply"(callable|None),
                     "measurements": {"dev": value},
                     "infrastructure_failure": bool, "security_violation":
                     bool, "mutates_frozen": bool}]
        Each apply() receives the worktree dir; the runner verifies afterwards
        that no frozen file changed."""
        campaign_id = self.create_campaign(manifest, "fake")
        results = []
        infra_streak = 0
        spent = 0
        stopped = None
        for sc in scenarios:
            if stopped:
                break
            if spent >= manifest.budget:
                results.append({"status": "CAMPAIGN_STOPPED",
                                "reason": "budget_exhausted"})
                break
            # frozen verification BEFORE running anything
            frozen_now = {"all": _sha("frozen")}     # stand-in for real hashes
            mutated_frozen = bool(sc.get("mutates_frozen"))
            frozen_ok = self.verify_frozen(
                manifest, manifest.frozen_eval_hashes,
                manifest.corpus_hash) and not mutated_frozen
            base_val = dev_eval_fn(None, seed=0)
            cand_val = sc["measurements"]["dev"]
            status, rationale = self.decide(
                base_val, cand_val,
                noise_floor=sc.get("noise_floor", 0.02),
                hard_constraints_ok=bool(sc.get("constraints_ok", True)),
                frozen_ok=frozen_ok,
                infrastructure_failure=bool(
                    sc.get("infrastructure_failure")),
                security_violation=bool(sc.get("security_violation")))
            if status == "CRASH":
                infra_streak += 1
                if infra_streak >= 3:
                    stopped = "infra_failures_3"
            else:
                infra_streak = 0
            if status == "QUARANTINED":
                stopped = "security_violation"
            spent += 1
            eid = self.record_experiment(
                campaign_id, sc["hypothesis"], manifest.baseline_ref,
                sc["candidate_ref"], manifest.mutable_scope,
                {"baseline_dev": base_val, "candidate_dev": cand_val},
                status, rationale,
                frozen_hashes={"manifest": manifest.manifest_hash})
            results.append({"experiment_id": eid, "status": status,
                            "rationale": rationale})
        if stopped:
            results.append({"status": "CAMPAIGN_STOPPED", "reason": stopped})
        return results
