"""Adversarial regression tests for S1-004 (formal + seeded simulation).

Evidence under test (research/tickets/stage-1/S1-004):

1. The recorded acceptance manifest (3 seeds x 1,000,000 operations) is
   intact: verdict PASS, complete invariant counters, all-zero violations,
   rerun digests reproduced, and every recorded SHA-256 matches the file on
   disk (tamper detection).
2. Both adversarial probes pass (crash-after-commit-before-publish replay;
   reserve-child-budget -> revoke -> retry interleaving).
3. Every contract mutation is DETECTED by the simulator detectors
   (negative tests): INV1..INV6, SAF1..SAF4, LIVE1, LIVE2. A deliberately
   broken invariant must be reported, never silently accepted.
4. The same crafted sequences WITHOUT mutations complete cleanly (the
   detectors have no false positives on the valid path).
5. Determinism: the same seed reproduces the exact trace digest; a
   different seed produces a different trace.
6. The formal evidence summary (Alloy + TLC) recorded in results/ is
   present and consistent (verdict PASS on both engines).

The full 1M-operation acceptance runs are NOT re-executed here (they take
minutes); this suite verifies their recorded, hash-locked evidence and
exercises the identical simulator machinery on a small envelope.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from unittest import TestCase

ROOT = Path(__file__).resolve().parent.parent
S1004 = ROOT / "research" / "tickets" / "stage-1" / "S1-004"
SIM_DIR = S1004 / "simulator"
sys.path.insert(0, str(SIM_DIR))

import invariant_simulator as isim  # noqa: E402
from invariant_simulator import INVARIANT_IDS, Simulator, Violation, simulate  # noqa: E402,E501


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _activate(sim: Simulator, *grants: int) -> None:
    """Deterministically activate grants (bypassing rng approval choice)."""
    for g in grants:
        sim.g_approved_tick[g] = sim.tick
        sim._pending_activation.append(g)
    sim.op_tick()


# --------------------------------------------------------------------------
# 1. Recorded acceptance evidence is intact
# --------------------------------------------------------------------------

class AcceptanceEvidenceTests(TestCase):
    def test_manifest_declares_pass_envelope(self):
        manifest = json.loads(
            (S1004 / "results" / "simulation" / "manifest.json")
            .read_text(encoding="utf-8"))
        acc = manifest["acceptance"]
        self.assertEqual(acc["verdict"], "PASS")
        self.assertEqual(acc["violation_count_total"], 0)
        self.assertGreaterEqual(len(acc["seeds"]), 3)
        self.assertGreaterEqual(acc["operations_per_seed"], 1_000_000)
        for run in manifest["runs"]:
            self.assertEqual(run["operations"], acc["operations_per_seed"])
            self.assertEqual(run["verdict"], "PASS")
            for inv in INVARIANT_IDS:
                self.assertIn(inv, run["invariant_counters"])
                self.assertEqual(run["invariant_counters"][inv], 0)
        reproduced = {r["seed"]: r["digest_match"] for r in manifest["reruns"]}
        for run in manifest["runs"]:
            self.assertTrue(reproduced[run["seed"]],
                            f"rerun did not reproduce seed {run['seed']}")

    def test_manifest_hashes_match_disk(self):
        manifest = json.loads(
            (S1004 / "results" / "simulation" / "manifest.json")
            .read_text(encoding="utf-8"))
        base = S1004 / "results" / "simulation"
        for run in manifest["runs"]:
            seed_dir = base / f"seed-{run['seed']}"
            self.assertEqual(_sha(seed_dir / "config.json"),
                             run["config_sha256"])
            self.assertEqual(_sha(seed_dir / "result.json"),
                             run["result_sha256"])
            digest_file = (seed_dir / "trace_digest.txt").read_text(
                encoding="ascii").strip()
            self.assertEqual(digest_file, run["trace_digest"])
            result = json.loads((seed_dir / "result.json")
                                .read_text(encoding="utf-8"))
            self.assertEqual(result["trace_digest"], run["trace_digest"])
            self.assertEqual(result["operations"], run["operations"])
        for name, expected in manifest["module_sha256"].items():
            self.assertEqual(_sha(SIM_DIR / name), expected,
                             f"{name} changed after the recorded run")

    def test_formal_summary_both_engines_pass(self):
        summary = json.loads(
            (S1004 / "results" / "formal_summary.json").read_text(
                encoding="utf-8"))
        self.assertEqual(summary["alloy"]["verdict"], "PASS")
        self.assertEqual(summary["alloy"]["expectation_problems"], [])
        self.assertEqual(summary["tla"]["verdict"], "PASS")
        self.assertTrue(summary["tla"]["completed_no_error"])
        self.assertTrue(summary["tla"]["temporal_properties_checked"])
        self.assertGreater(summary["tla"]["distinct_states"], 0)
        alloy_commands = {c["command"]: c["verdict"]
                          for c in summary["alloy"]["commands"]}
        self.assertEqual(len(alloy_commands), 12)
        for name, verdict in alloy_commands.items():
            if name.startswith("Run Valid"):
                self.assertEqual(verdict, "SAT", name)
            elif name.startswith("Run NearMiss"):
                self.assertEqual(verdict, "UNSAT", name)
            elif name.startswith("Run Mutant"):
                self.assertEqual(verdict, "SAT", name)


# --------------------------------------------------------------------------
# 2. Small-envelope live runs of the same machinery
# --------------------------------------------------------------------------

class SmallEnvelopeTests(TestCase):
    def test_three_seeds_small_envelope_clean(self):
        for seed in (7, 8, 9):
            sim, result = simulate(seed, 20_000)
            self.assertEqual(result["operations"], 20_000)
            for inv in INVARIANT_IDS:
                self.assertIn(inv, result["invariant_counters"])
                self.assertEqual(result["invariant_counters"][inv], 0,
                                 f"seed {seed}: {inv} counter not zero")
            self.assertTrue(result["op_counts"])

    def test_determinism_same_and_different_seed(self):
        _, r1 = simulate(2026, 5_000)
        _, r2 = simulate(2026, 5_000)
        _, r3 = simulate(2027, 5_000)
        self.assertEqual(r1["trace_digest"], r2["trace_digest"])
        self.assertNotEqual(r1["trace_digest"], r3["trace_digest"])


# --------------------------------------------------------------------------
# 3. Adversarial probes
# --------------------------------------------------------------------------

class ProbeTests(TestCase):
    def test_probe_a_crash_after_commit_before_publish(self):
        probe = isim.probe_crash_replay()
        self.assertTrue(probe["passed"], probe)
        checks = probe["checks"]
        self.assertEqual(checks["outbox_events"], 1)
        self.assertEqual(checks["receipts_at_crash"], 0)
        self.assertEqual(checks["publishes_at_crash"], 0)
        self.assertTrue(checks["crash_cleared_by_replay"])
        self.assertEqual(checks["receipts_after_ack"], 1)
        self.assertEqual(checks["receipts_after_duplicate_acks"], 1)

    def test_probe_b_reserve_revoke_retry(self):
        probe = isim.probe_reserve_revoke_retry()
        self.assertTrue(probe["passed"], probe)
        checks = probe["checks"]
        self.assertFalse(checks["over_allocation_before_revoke"])
        self.assertTrue(checks["reservations_released_on_revoke"])
        self.assertTrue(checks["allow_denied_after_revoke"])
        self.assertFalse(checks["reservation_retry_accepted_after_revoke"])
        self.assertFalse(checks["over_allocation_after_retry"])
        self.assertTrue(checks["blind_retry_blocked"])
        self.assertTrue(checks["retry_legal_after_reconciliation"])


# --------------------------------------------------------------------------
# 4. Negative mutation tests: broken invariants MUST be detected
# --------------------------------------------------------------------------

def _mutation_sequence(invariant: str):
    """Crafted deterministic sequences that trigger each mutation exactly."""
    def seq(sim: Simulator):
        if invariant == "INV1":
            for _ in range(10):
                sim.op_identity_join()
                if sim.class_of:
                    break
            for _ in range(5):
                sim.op_identity_join_conflict()
        elif invariant == "INV2":
            sim.op_co_create()
            sim.op_co_move()
            sim.op_co_move()
        elif invariant == "INV3":
            _activate(sim, 0, 8)
            sim._set_grant_state(8, "revoked")     # free the child slot
            for _ in range(30):
                sim.op_grant_propose()
        elif invariant == "INV4":
            sim.op_ka_propose()
            sim.op_ka_promote()
        elif invariant == "INV5":
            _activate(sim, 0)
            sim.op_grant_revoke()                  # revoke the only chain
            for _ in range(5):
                sim.op_allow()
        elif invariant == "INV6":
            _activate(sim, 0, 8)
            for _ in range(10):
                sim.op_reserve_child()
        elif invariant == "SAF1":
            for _ in range(20):
                _activate(sim, 0)
                sim.op_allow()
        elif invariant == "SAF2":
            _activate(sim, 0)
            sim.op_allow()
            sim.op_publish()
            d = sim._next_decision - 1
            rec = sim.decisions[d]
            sim._apply_ack(d, rec, rec["inflight_token"])
            sim._apply_ack(d, rec, rec["inflight_token"])
        elif invariant == "SAF3":
            _activate(sim, 0)
            sim.op_allow()
            sim.op_publish()
            sim.op_delivery_timeout()
            sim.op_publish()                        # blind retry attempt
        elif invariant == "SAF4":
            sim.op_grant_revoke()                   # illegal state revoke
        elif invariant == "LIVE1":
            sim.op_grant_approve()                  # mutant loses activation
            sim.op_tick()
            sim.op_tick()
            sim.audit()
        elif invariant == "LIVE2":
            _activate(sim, 0)
            sim.fault_probs["crash_commit_publish"] = 1.0
            sim.op_allow()                          # crash before publish
            sim.op_tick()                           # mutant forgets replay
            sim.op_tick()
            sim.audit()
        else:  # pragma: no cover
            raise AssertionError(f"unknown mutation {invariant}")
    return seq


class MutationDetectionTests(TestCase):
    def test_every_broken_invariant_is_detected(self):
        for invariant in INVARIANT_IDS:
            with self.subTest(invariant=invariant):
                sim = Simulator(11, mutations=(invariant,))
                with self.assertRaises(Violation) as ctx:
                    _mutation_sequence(invariant)(sim)
                self.assertEqual(ctx.exception.invariant, invariant)

    def test_valid_paths_have_no_false_positives(self):
        for invariant in INVARIANT_IDS:
            with self.subTest(invariant=invariant):
                sim = Simulator(11)          # no mutations
                _mutation_sequence(invariant)(sim)  # must not raise
                for inv in INVARIANT_IDS:
                    self.assertEqual(sim.counters[inv], 0)

    def test_counterexample_replay_is_deterministic(self):
        witness = isim.replay_violation(11, 400, ("INV1",))
        self.assertEqual(witness["invariant"], "INV1")
        self.assertLessEqual(len(witness["trace_window"]), 256)
        # a second replay of the same witness reproduces identically
        again = isim.replay_violation(11, 400, ("INV1",))
        self.assertEqual(again["step"], witness["step"])
        self.assertEqual(again["detail"], witness["detail"])
        self.assertEqual(again["trace_digest_at_violation"],
                         witness["trace_digest_at_violation"])

    def test_random_mutation_run_is_caught(self):
        """A long random run under a mutation must fail closed."""
        sim = Simulator(5, mutations=("INV2",))
        with self.assertRaises(Violation) as ctx:
            sim.run(50_000)
        self.assertEqual(ctx.exception.invariant, "INV2")


# --------------------------------------------------------------------------
# 5. Simulator library hygiene
# --------------------------------------------------------------------------

class SimulatorHygieneTests(TestCase):
    def test_simulator_is_stdlib_only(self):
        source = (SIM_DIR / "invariant_simulator.py").read_text(
            encoding="utf-8")
        banned = ("import numpy", "import pandas", "import z3", "import sqlalchemy")
        for needle in banned:
            self.assertNotIn(needle, source)

    def test_empty_series_fails_closed(self):
        sim = Simulator(1)
        with self.assertRaises(RuntimeError):
            sim.run(0)


if __name__ == "__main__":  # pragma: no cover
    from unittest import main
    main()
