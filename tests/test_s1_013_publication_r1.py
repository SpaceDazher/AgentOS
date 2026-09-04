"""Focused publication-boundary regressions for S1-013 R1."""
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TICKET = ROOT / "research" / "tickets" / "stage-1" / "S1-013"
SPEC = importlib.util.spec_from_file_location("s1013_publication", TICKET / "make_bundle.py")
make_bundle = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(make_bundle)


def _write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8", newline="\n")


def _write_json(path: Path, value: object) -> None:
    _write(path, json.dumps(value, sort_keys=True) + "\n")


def _minimal_frozen_ticket(base: Path) -> None:
    files = {
        "analysis-plan.md": "analysis\n",
        "runner.py": "# importer\n",
        "evaluator.py": "# scorer\n",
        "replicate.py": "# replication\n",
        "pilot-protocol.json": {"protocol_version": "test-v1"},
        "scenario-manifest.json": {"approval_blocks": []},
        "rubric.json": {"synthetic_answer_oracle": {}},
        "schemas/session.schema.json": {},
        "schemas/events.schema.json": {},
        "schemas/answers.schema.json": {},
        "prototype/index.html": "<!doctype html>\n",
        "synthetic/sessions/fixture.json": "{}\n",
    }
    for rel, value in files.items():
        _write_json(base / rel, value) if isinstance(value, dict) else _write(base / rel, value)
    hashes = {
        rel: make_bundle.sha((base / rel).read_bytes())
        for rel in sorted(make_bundle._ticket_relative_files(base))
    }
    _write_json(base / "frozen-manifest.json", {
        "schema": "agentos.s1-013.frozen-manifest/v1",
        "ticket": "S1-013",
        "protocol_version": "test-v1",
        "hashes": hashes,
    })


class TestS1013PublicationR1(unittest.TestCase):
    def test_manifest_is_exact_and_detects_new_fixture(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            _minimal_frozen_ticket(base)
            problems, _ = make_bundle.verify_frozen_manifest(base)
            self.assertEqual(problems, [])
            _write(base / "synthetic/sessions/new.json", "{}\n")
            problems, _ = make_bundle.verify_frozen_manifest(base)
            self.assertIn("frozen manifest missing input: synthetic/sessions/new.json",
                          problems)

    def test_saved_comparison_without_source_binding_is_rejected(self):
        old = {
            "schema": "agentos.s1-013.comparison/v1",
            "replicated": True,
            "distinct_processes": True,
            "digests": {
                key: {"a": "0" * 64, "b": "0" * 64, "match": True}
                for key in ("metrics", "probes", "observations")
            },
        }
        with self.assertRaises(ValueError):
            make_bundle._stable_comparison(old)

    def test_failed_main_removes_stale_ready_outputs_even_with_forged_flag(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            (base / "results").mkdir()
            for name in ("bundle.json", "candidate-record.json"):
                _write(base / name, "stale\n")
            _write_json(base / "dependency-gate.json", {
                "all_proven": True,
                "dependencies": [{"status": "PROVEN"}],
            })
            self.assertEqual(make_bundle.main(["--here", str(base),
                                               "--results", str(base / "results")]), 1)
            self.assertFalse((base / "bundle.json").exists())
            self.assertFalse((base / "candidate-record.json").exists())

    def test_measure_denominator_must_match_frozen_presentations(self):
        blockers: list[str] = []
        make_bundle._validate_counts(
            "C1", {"n": 1, "correct": 1, "missing": 0, "rate": 1.0,
                    "wilson": [0.2, 1.0]}, 2, blockers)
        self.assertTrue(any("denominator" in item for item in blockers))


if __name__ == "__main__":
    unittest.main()
