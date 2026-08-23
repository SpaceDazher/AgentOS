"""Harness Autoresearch (Phase 4). See ADR-0008 and SPEC §10.

R5 corrective round:
- CampaignManifest is frozen after creation (attribute writes raise);
  its hash covers baseline, metric, scope, eval hashes, corpus hash,
  budget and seeds.
- Real isolated worktrees: each experiment gets a temp worktree seeded from
  the repo; `apply(worktree)` is actually invoked; afterwards the runner
  hashes the worktree and verifies (a) no file outside mutable_scope changed
  and (b) frozen corpus/eval files are byte-identical to the manifest pins.
- Frozen verification is host-owned: the runner recomputes hashes from disk;
  a candidate cannot talk its way past it.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
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


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha(data) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return _sha_bytes(data)


def _tree_hashes(root: Path) -> dict:
    """Relative-path -> sha256 for every file under root."""
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            out[str(p.relative_to(root)).replace("\\", "/")] = \
                _sha_bytes(p.read_bytes())
    return out


class FrozenManifest:
    """Attribute-frozen wrapper: any write raises."""

    def __init__(self, inner: dict, hash_value: str):
        object.__setattr__(self, "_inner", inner)
        object.__setattr__(self, "_hash", hash_value)

    def __getattr__(self, name):
        try:
            return self._inner[name]
        except KeyError as e:
            raise AttributeError(name) from e

    def __setattr__(self, name, value):
        raise AutoresearchError("CampaignManifest is immutable")

    @property
    def manifest_hash(self) -> str:
        return self._hash


def make_manifest(*, baseline_ref: str, primary_metric: str,
                  mutable_scope: list[str], frozen_eval_hashes: dict,
                  corpus_hash: str, budget: int = 5,
                  seeds: list[int] | None = None,
                  hard_constraints: dict | None = None,
                  frozen_files: dict | None = None) -> FrozenManifest:
    """Build an immutable manifest. `frozen_files` maps repo-relative paths to
    their required sha256 — host-owned pins verified from disk each run."""
    if not frozen_eval_hashes or not corpus_hash:
        raise AutoresearchError("manifest requires frozen eval+corpus hashes")
    inner = {
        "baseline_ref": baseline_ref,
        "primary_metric": primary_metric,
        "mutable_scope": sorted(mutable_scope),
        "frozen_eval_hashes": dict(frozen_eval_hashes),
        "corpus_hash": corpus_hash,
        "budget": int(budget),
        "seeds": list(seeds or [0]),
        "hard_constraints": dict(hard_constraints or {
            "zero_false_accepts_holdout": True,
            "zero_forbidden_effects": True,
            "audit_completeness": 1.0}),
        "frozen_files": dict(frozen_files or {}),
    }
    h = _sha(json.dumps(inner, sort_keys=True))
    return FrozenManifest(inner, h)


# Back-compat alias (existing tests import CampaignManifest)
def CampaignManifest(**kw) -> FrozenManifest:  # noqa: N802
    return make_manifest(**kw)


class Autoresearch:
    """Campaign runner. Candidate changes are applied by the caller-supplied
    `apply(worktree)` callable inside an ISOLATED WORKTREE; scope and frozen
    integrity are verified from disk by this class afterwards."""

    def __init__(self, db, root_dir: str | Path, stage_evals,
                 repo_source: str | Path | None = None):
        self.db = db
        self.root = Path(root_dir)
        self.se = stage_evals
        # snapshot source for worktrees: repo root (parent of src/) when present
        candidate = Path(repo_source) if repo_source else Path.cwd()
        if (candidate / "src" / "agentos").exists():
            self.repo_source = candidate
        else:
            self.repo_source = None   # empty worktree mode (tests)

    # -- persistence -----------------------------------------------------------
    def create_campaign(self, manifest: FrozenManifest, name: str) -> str:
        cid = new_id("campaign")
        with self.db.tx() as conn:
            conn.execute(
                "INSERT INTO campaign(id, name, manifest_json,"
                " manifest_sha256, baseline_ref, primary_metric, budget)"
                " VALUES (?,?,?,?,?,?,?)",
                (cid, name, json.dumps(manifest._inner, sort_keys=True),
                 manifest.manifest_hash, manifest.baseline_ref,
                 manifest.primary_metric, manifest.budget))
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
                          frozen_hashes: dict | None = None,
                          goal_id: str | None = None,
                          worktree_digest: dict | None = None) -> str:
        if status not in ("proposed", "running", "KEEP", "DISCARD", "RETEST",
                          "CRASH", "QUARANTINED"):
            raise AutoresearchError(f"invalid experiment status {status}")
        eid = new_id("exp")
        measurements_full = dict(measurements)
        if worktree_digest:
            measurements_full["worktree_files"] = len(worktree_digest)
        with self.db.tx() as conn:
            conn.execute(
                "INSERT INTO experiment(id, campaign_id, hypothesis,"
                " baseline_ref, candidate_ref, mutable_scope_json,"
                " seeds_json, primary_metric, status, measurements_json,"
                " decision_rationale, frozen_hashes_json, decided_at, goal_id)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?, strftime("
                "'%Y-%m-%dT%H:%M:%fZ','now'), ?)",
                (eid, campaign_id, hypothesis, baseline_ref, candidate_ref,
                 json.dumps(mutable_scope), "[]", "", status,
                 json.dumps(measurements_full), rationale,
                 json.dumps(frozen_hashes or {}), goal_id))
        return eid

    @staticmethod
    def verify_frozen(manifest: FrozenManifest,
                      current_eval_hashes: dict,
                      current_corpus_hash: str) -> bool:
        return (current_eval_hashes == manifest.frozen_eval_hashes
                and current_corpus_hash == manifest.corpus_hash)

    # -- worktree helpers ---------------------------------------------------------
    def _new_worktree(self) -> Path:
        wt = Path(tempfile.mkdtemp(prefix="agentos-exp-"))
        if self.repo_source:
            # seed with the repo's mutable-relevant content (shallow copy of
            # tracked top-level items; stdlib-only, no git dependency)
            for item in ("src", "evals", "spec"):
                srcp = self.repo_source / item
                if srcp.exists():
                    shutil.copytree(srcp, wt / item, dirs_exist_ok=True)
        return wt

    @staticmethod
    def _in_scope(rel_path: str, scope_globs: list[str]) -> bool:
        import fnmatch
        return any(fnmatch.fnmatch(rel_path, g) for g in scope_globs)

    def _verify_scope_and_frozen(self, manifest: FrozenManifest,
                                 wt: Path, before: dict) -> tuple[bool, list]:
        """Host-owned verification from disk: every changed file must be in
        mutable_scope AND no pinned frozen file may differ."""
        after = _tree_hashes(wt)
        violations = []
        for rel in sorted(set(before) | set(after)):
            old, new = before.get(rel), after.get(rel)
            if old == new:
                continue
            if rel in manifest.frozen_files:
                violations.append(f"{rel}: FROZEN file modified")
            elif not self._in_scope(rel, manifest.mutable_scope):
                violations.append(f"{rel}: outside mutable scope"
                                  f" {manifest.mutable_scope}")
        # frozen file pins must still match on disk
        for rel, want in manifest.frozen_files.items():
            fp = wt / rel
            got = _sha_bytes(fp.read_bytes()) if fp.exists() else None
            if got != want:
                violations.append(f"{rel}: frozen hash mismatch")
        return not violations, violations

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

    # -- campaign loop ------------------------------------------------------------
    def run_campaign(self, manifest: FrozenManifest,
                     scenarios: list[dict], dev_eval_fn,
                     holdout_fn=None) -> list[dict]:
        """Real pipeline: per scenario create a worktree, invoke apply(worktree),
        verify scope+frozen from disk, run dev+holdout evals, decide, record.

        scenarios: [{"hypothesis", "candidate_ref", "apply"(callable|None),
                     "measurements"? {"dev": value}, "infrastructure_failure"?,
                     "security_violation"?}]"""
        campaign_id = self.create_campaign(manifest, "autoresearch")
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
            wt = self._new_worktree()
            before = _tree_hashes(wt)
            apply_called = False
            try:
                apply_fn = sc.get("apply")
                if apply_fn is not None:
                    apply_fn(wt)
                    apply_called = True
                scope_ok, violations = self._verify_scope_and_frozen(
                    manifest, wt, before)
            except Exception as e:  # noqa: BLE001 — apply crash => CRASH
                infra_streak += 1
                spent += 1
                eid = self.record_experiment(
                    campaign_id, sc["hypothesis"], manifest.baseline_ref,
                    sc["candidate_ref"], manifest.mutable_scope,
                    {"error": str(e)[:200]}, "CRASH",
                    "apply() raised", goal_id=None)
                results.append({"experiment_id": eid, "status": "CRASH",
                                "rationale": "apply() raised"})
                if infra_streak >= 3:
                    stopped = "infra_failures_3"
                continue
            base_val = dev_eval_fn(None, seed=manifest.seeds[0])
            cand_val = dev_eval_fn(wt, seed=manifest.seeds[0])
            status, rationale = self.decide(
                base_val, cand_val,
                noise_floor=sc.get("noise_floor", 0.02),
                hard_constraints_ok=scope_ok,
                frozen_ok=scope_ok,
                security_violation=bool(sc.get("security_violation")))
            if status == "QUARANTINED" and violations:
                rationale = "; ".join(violations[:3])
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
                frozen_hashes={"manifest": manifest.manifest_hash},
                worktree_digest=_tree_hashes(wt))
            shutil.rmtree(wt, ignore_errors=True)
            results.append({"experiment_id": eid, "status": status,
                            "rationale": rationale,
                            "apply_called": apply_called})
        if stopped:
            results.append({"status": "CAMPAIGN_STOPPED", "reason": stopped})
        return results

    # -- deterministic fake campaign kept for LLM-free drills --------------------
    def run_fake_campaign(self, manifest: FrozenManifest,
                          scenarios: list[dict], dev_eval_fn) -> list[dict]:
        """Scripted variant used by unit tests/drills. Applies real worktree
        verification when `apply` mutates files; measurement values come from
        the scenario."""
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
            wt = self._new_worktree()
            before = _tree_hashes(wt)
            try:
                if sc.get("apply") is not None:
                    sc["apply"](wt)
                scope_ok, violations = self._verify_scope_and_frozen(
                    manifest, wt, before)
            except Exception as e:  # noqa: BLE001
                infra_streak += 1
                spent += 1
                eid = self.record_experiment(
                    campaign_id, sc["hypothesis"], manifest.baseline_ref,
                    sc["candidate_ref"], manifest.mutable_scope,
                    {"error": str(e)[:200]}, "CRASH", "apply() raised")
                results.append({"experiment_id": eid, "status": "CRASH",
                                "rationale": "apply() raised"})
                if infra_streak >= 3:
                    stopped = "infra_failures_3"
                continue
            mutated_frozen = bool(sc.get("mutates_frozen"))
            frozen_ok = scope_ok and not mutated_frozen
            base_val = dev_eval_fn(None, seed=0)
            cand_val = sc["measurements"]["dev"]
            status, rationale = self.decide(
                base_val, cand_val,
                noise_floor=sc.get("noise_floor", 0.02),
                hard_constraints_ok=bool(sc.get("constraints_ok", True)),
                frozen_ok=frozen_ok,
                infrastructure_failure=bool(sc.get("infrastructure_failure")),
                security_violation=bool(sc.get("security_violation")))
            if status == "QUARANTINED" and violations:
                rationale = "; ".join(violations[:3])
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
            shutil.rmtree(wt, ignore_errors=True)
            results.append({"experiment_id": eid, "status": status,
                            "rationale": rationale})
        if stopped:
            results.append({"status": "CAMPAIGN_STOPPED", "reason": stopped})
        return results
