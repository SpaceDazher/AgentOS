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
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import types
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
    """Deeply frozen manifest: attribute writes raise; returned containers are
    read-only views; the stored representation is a PRIVATE serialized copy
    and the digest is RE-VERIFIED against it on every access."""

    def __init__(self, inner: dict, hash_value: str):
        stored = json.loads(json.dumps(inner))   # private deep copy
        if _sha(json.dumps(stored, sort_keys=True)) != hash_value:
            raise AutoresearchError(
                "manifest digest mismatch at construction")
        object.__setattr__(self, "_stored",
                           json.dumps(stored, sort_keys=True))
        object.__setattr__(self, "_hash", hash_value)

    def _load(self) -> dict:
        """Re-parse from the frozen string and RE-VERIFY the digest."""
        stored = json.loads(self._stored)
        if _sha(json.dumps(stored, sort_keys=True)) != self._hash:
            raise AutoresearchError("manifest digest mismatch detected")
        return stored

    def __getattr__(self, name):
        try:
            value = self._load()[name]
        except KeyError as e:
            raise AttributeError(name) from e
        if isinstance(value, list):
            return tuple(value)
        if isinstance(value, dict):
            return types.MappingProxyType(dict(value))
        return value

    def __setattr__(self, name, value):
        raise AutoresearchError("CampaignManifest is immutable")

    @property
    def manifest_hash(self) -> str:
        return self._hash

    def to_jsonable(self) -> dict:
        return self._load()


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
    """Campaign runner.

    Production candidates use ``apply_cmd`` in a stripped-environment
    subprocess rooted at an isolated worktree. Direct ``apply(worktree)``
    callbacks are available only in explicit drill mode. A third, host-owned
    path is ``apply_host(worktree) -> dict``: a callable that runs IN THE HOST
    but is host code, not candidate code (e.g. it spawns a worker agent and
    replays its DECLARED effects into the worktree). Candidate authorship is
    still confined the same way afterwards: scope + frozen verification reads
    the worktree from disk, so whatever wrote the bytes does not matter.
    Scope and frozen integrity are verified from disk by the host afterwards;
    this is not a kernel filesystem/network sandbox.
    """

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
    def create_campaign(self, manifest: FrozenManifest, name: str,
                        goal_id: str | None = None) -> str:
        cid = new_id("campaign")
        gid = goal_id
        if not gid:
            raise AutoresearchError(
                "campaign requires goal_id — a campaign belongs to ONE goal")
        exists = self.db.conn.execute(
            "SELECT 1 FROM goal WHERE id=?", (gid,)).fetchone()
        if not exists:
            raise AutoresearchError(f"campaign goal {gid} does not exist")
        with self.db.tx() as conn:
            conn.execute(
                "INSERT INTO campaign(id, goal_id, name, manifest_json,"
                " manifest_sha256, baseline_ref, primary_metric, budget)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (cid, gid, name,
                 json.dumps(manifest.to_jsonable(), sort_keys=True),
                 manifest.manifest_hash, manifest.baseline_ref,
                 manifest.primary_metric, manifest.budget))
            conn.execute(
                "INSERT INTO experiment(id, campaign_id, hypothesis,"
                " baseline_ref, candidate_ref, mutable_scope_json,"
                " budget_json, seeds_json, primary_metric, status,"
                " frozen_hashes_json, goal_id)"
                " VALUES (?,?,?,?,?,?,?,?,?, 'proposed', ?, ?)",
                (cid, cid, f"campaign {name}", manifest.baseline_ref,
                 "(baseline)", json.dumps(list(manifest.mutable_scope)),
                 json.dumps({"experiments": manifest.budget}),
                 json.dumps(list(manifest.seeds)), manifest.primary_metric,
                 json.dumps({"manifest": manifest.manifest_hash,
                             "evals": dict(manifest.frozen_eval_hashes),
                             "corpus": manifest.corpus_hash}),
                 gid))
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
        # R7: DB-enforced scoping — the goal must match the campaign's owner.
        crow = self.db.conn.execute(
            "SELECT goal_id FROM campaign WHERE id=?", (campaign_id,)
        ).fetchone()
        if not crow:
            raise AutoresearchError(f"unknown campaign {campaign_id}")
        owner_goal = crow["goal_id"]
        if goal_id is not None and goal_id != owner_goal:
            raise AutoresearchError(
                f"experiment goal {goal_id} does not match campaign owner"
                f" {owner_goal} — cross-goal insertion refused")
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
                 json.dumps(list(mutable_scope)), "[]", "", status,
                 json.dumps(measurements_full), rationale,
                 json.dumps(frozen_hashes or {}, default=dict), owner_goal))
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
                     holdout_fn=None, *, goal_id: str | None = None,
                     drill_mode: bool = False) -> list[dict]:
        """Real pipeline (R6): per scenario create a worktree, run the
        candidate's apply SCRIPT in an ISOLATED SUBPROCESS (cwd=worktree —
        the host process is never exposed to candidate code), verify scope +
        frozen hashes from disk, then dev evals + MANDATORY holdout before
        any KEEP.

        scenarios: [{"hypothesis", "candidate_ref", "apply_cmd"(list argv
                     executed with cwd=worktree) | "apply"(callable, drill mode),
                    "measurements"? {"dev": value}, "infrastructure_failure"?,
                    "security_violation"?}]
        holdout_fn(worktree, seed) -> {"passed": bool} must be supplied;
        KEEP requires holdout passed."""
        if holdout_fn is None:
            raise AutoresearchError(
                "run_campaign requires holdout_fn — KEEP without an "
                "independent holdout evaluation is forbidden (ADR-0008)")
        if any(sc.get("apply") is not None for sc in scenarios) and not drill_mode:
            raise AutoresearchError(
                "in-process apply callbacks are drill-only; use apply_cmd"
                " or apply_host for production campaigns")
        campaign_id = self.create_campaign(manifest, "autoresearch",
                                           goal_id=goal_id)
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
            infra_fail = bool(sc.get("infrastructure_failure"))
            try:
                if sc.get("apply") is not None:
                    # Explicitly opt-in drill path.  Production campaigns
                    # must use apply_cmd so candidate code never executes in
                    # the host interpreter.
                    sc["apply"](wt)
                    apply_called = True
                elif sc.get("apply_cmd"):
                    # R7: candidate code runs in an isolated SUBPROCESS whose
                    # cwd IS the worktree and whose environment is reduced to
                    # the worktree itself — no host env, no host paths. The
                    # host never imports or calls candidate code.
                    clean_env = {
                        "PATH": "", "SYSTEMROOT": os.environ.get(
                            "SYSTEMROOT", ""),
                        "AGENTOS_WORKTREE": str(wt),
                        "PYTHONPATH": str(wt),
                    }
                    proc = subprocess.run(
                        [*sc["apply_cmd"]], cwd=str(wt), env=clean_env,
                        capture_output=True, text=True,
                        timeout=manifest.hard_constraints.get("timeout_s", 600))
                    if proc.returncode != 0:
                        infra_fail = True
                        sc["stderr_excerpt"] = (proc.stderr or "")[-300:]
                elif sc.get("apply_host"):
                    # Host-owned candidate generator (e.g. spawn a worker
                    # agent and replay its DECLARED effects into the
                    # worktree). The callable is HOST code; candidate
                    # authorship is judged afterwards by disk verification
                    # (scope + frozen pins), never by trust here.
                    sc["apply_host"](wt)
                    apply_called = True
                scope_ok, violations = self._verify_scope_and_frozen(
                    manifest, wt, before)
            except Exception as e:  # noqa: BLE001 — crash => CRASH
                infra_fail = True
                sc["stderr_excerpt"] = str(e)[:200]
                # An apply crash is an INFRASTRUCTURE failure (ADR-0008:
                # provider failures are CRASH-classed and never counted as
                # capability signal). Scope was not verified this round —
                # record that fact without inventing a scope violation.
                scope_ok, violations = False, []
            if infra_fail and not violations:
                infra_streak += 1
                spent += 1
                eid = self.record_experiment(
                    campaign_id, sc["hypothesis"], manifest.baseline_ref,
                    sc["candidate_ref"], list(manifest.mutable_scope),
                    {"error": sc.get("stderr_excerpt", "infra failure")},
                    "CRASH", "infrastructure/provider failure",
                    goal_id=goal_id)
                results.append({"experiment_id": eid, "status": "CRASH",
                                "rationale": "infrastructure failure"})
                if infra_streak >= 3:
                    stopped = "infra_failures_3"
                shutil.rmtree(wt, ignore_errors=True)
                continue
            base_val = dev_eval_fn(None, seed=manifest.seeds[0])
            cand_val = dev_eval_fn(wt, seed=manifest.seeds[0])
            # MANDATORY independent holdout before any KEEP decision
            holdout = None
            try:
                holdout = holdout_fn(wt, seed=manifest.seeds[0])
            except Exception as e:  # noqa: BLE001
                scope_ok = False
                violations = [*violations, f"holdout raised: {e}"]
            holdout_passed = bool(holdout and holdout.get("passed"))
            status, rationale = self.decide(
                base_val, cand_val,
                noise_floor=sc.get("noise_floor", 0.02),
                hard_constraints_ok=scope_ok,
                frozen_ok=scope_ok,
                security_violation=bool(sc.get("security_violation")))
            if status == "KEEP" and not holdout_passed:
                status = "QUARANTINED"
                rationale = ("holdout gate failed — KEEP requires an "
                             "independent holdout pass (ADR-0008)")
            elif status == "QUARANTINED" and violations:
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
                sc["candidate_ref"], list(manifest.mutable_scope),
                {"baseline_dev": base_val, "candidate_dev": cand_val},
                status, rationale,
                frozen_hashes={"manifest": manifest.manifest_hash},
                worktree_digest=_tree_hashes(wt), goal_id=goal_id)
            shutil.rmtree(wt, ignore_errors=True)
            results.append({"experiment_id": eid, "status": status,
                            "rationale": rationale,
                            "apply_called": apply_called})
        if stopped:
            results.append({"status": "CAMPAIGN_STOPPED", "reason": stopped})
        return results

    # -- deterministic fake campaign kept for LLM-free drills --------------------
    def run_fake_campaign(self, manifest: FrozenManifest,
                          scenarios: list[dict], dev_eval_fn,
                          goal_id: str | None = None) -> list[dict]:
        """Scripted variant used by unit tests/drills. Applies real worktree
        verification when `apply` mutates files; measurement values come from
        the scenario."""
        campaign_id = self.create_campaign(manifest, "fake",
                                           goal_id=goal_id)
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
                    sc["candidate_ref"], list(manifest.mutable_scope),
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
                sc["candidate_ref"], list(manifest.mutable_scope),
                {"baseline_dev": base_val, "candidate_dev": cand_val},
                status, rationale,
                frozen_hashes={"manifest": manifest.manifest_hash})
            shutil.rmtree(wt, ignore_errors=True)
            results.append({"experiment_id": eid, "status": status,
                            "rationale": rationale})
        if stopped:
            results.append({"status": "CAMPAIGN_STOPPED", "reason": stopped})
        return results
