"""Phase 2 tests: run every stage check over the frozen corpora and verify
expected outcomes; per-stage failing and passing cases exist; evaluator
quality corpus measures FPR/FNR of the deterministic checks."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from agentos.stage_checks import CHECKS  # noqa: E402
from evals.gen_fixtures import build_corpus  # noqa: E402


def _run_case(rec: dict) -> list[tuple[str, bool]]:
    """Run every check registered for the case; returns [(metric, ok)]."""
    doc = json.loads((ROOT / rec["input_ref"]).read_bytes()
                     .decode("utf-8"))
    fake_case = {"id": rec["id"], "input_ref": rec["input_ref"]}
    out = []
    for suffix in rec["_checks"]:
        fn = CHECKS[f"{rec['stage']}.{suffix}"]
        ok, _detail = fn(fake_case)
        out.append((suffix, ok))
    return out


class TestStageCorpus(unittest.TestCase):
    def setUp(self):
        self.cases = build_corpus()
        self.stage_cases = [c for c in self.cases
                            if c[0]["corpus_version"] == "stage-v1"]
        self.eq_cases = [c for c in self.cases
                         if c[0]["corpus_version"] == "eq-v1"]

    def test_corpus_sizes(self):
        self.assertEqual(len(self.stage_cases), 48)
        self.assertEqual(len(self.eq_cases), 30)

    def test_each_stage_has_all_required_set_classes(self):
        need = {"gold": 2, "incomplete": 2, "near_miss": 2,
                "alternative_correct": 1, "adversarial": 1}
        by_stage: dict[str, dict] = {}
        for rec, _ in self.stage_cases:
            by_stage.setdefault(rec["stage"], {}).setdefault(
                rec["set_class"], 0)
            by_stage[rec["stage"]][rec["set_class"]] += 1
        for stage, got in by_stage.items():
            for cls, n in need.items():
                self.assertEqual(got.get(cls, 0), n,
                                 f"{stage}/{cls}: {got.get(cls, 0)} != {n}")

    def test_all_stage_cases_match_expected_outcome(self):
        mismatches = []
        for rec, _ in self.stage_cases:
            results = _run_case(rec)
            ok = all(ok for _, ok in results)
            if ok != rec["_expect_all_pass"]:
                mismatches.append((rec["id"], ok, rec["expected_outcome"],
                                   [m for m, o in results if not o]))
        self.assertEqual(mismatches, [],
                         f"cases disagreeing with expectation: {mismatches}")

    def test_each_stage_has_failing_and_passing_case(self):
        by_stage: dict[str, list[bool]] = {}
        for rec, _ in self.stage_cases:
            ok = all(ok for _, ok in _run_case(rec))
            by_stage.setdefault(rec["stage"], []).append(ok)
        for stage, outcomes in by_stage.items():
            self.assertIn(True, outcomes, f"{stage}: no passing case")
            self.assertIn(False, outcomes, f"{stage}: no failing case")


class TestEvaluatorQuality(unittest.TestCase):
    """Roadmap corpus: 10 gold + 10 near-miss + 10 alternative-correct.
    FPR = gold wrongly failed; FNR = near-miss wrongly passed."""

    def setUp(self):
        self.cases = [c for c in build_corpus()
                      if c[0]["corpus_version"] == "eq-v1"]

    def _all_pass(self, rec) -> bool:
        return all(ok for _, ok in self._run(rec))

    @staticmethod
    def _run(rec) -> list[tuple[str, bool]]:
        return _run_case(rec)

    def test_no_false_accepts_on_near_miss(self):
        """Every near-miss artifact must be rejected: FNR = 0."""
        near = [r for r, _ in self.cases if r["set_class"] == "near_miss"]
        fn = [r["id"] for r in near if self._all_pass(r)]
        self.assertEqual(fn, [], f"near-miss cases wrongly passed: {fn}")

    def test_gold_and_alternative_correct_all_pass(self):
        """FPR = 0: gold and alternative-correct must pass."""
        good = [r for r, _ in self.cases
                if r["set_class"] in ("gold", "alternative_correct")]
        fp = [r["id"] for r in good if not self._all_pass(r)]
        self.assertEqual(fp, [], "gold/alt cases wrongly failed: {fp}")


if __name__ == "__main__":
    unittest.main()
