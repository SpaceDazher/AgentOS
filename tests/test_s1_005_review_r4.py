"""Fail-closed regression probes for the S1-005 review R4 findings."""
from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import TestCase, mock


ROOT = Path(__file__).resolve().parent.parent
S1005 = ROOT / "research" / "tickets" / "stage-1" / "S1-005"
sys.path.insert(0, str(S1005))
sys.path.insert(0, str(ROOT / "src"))

import experiments as exp  # noqa: E402
import make_bundle  # noqa: E402
from agentos import autoresearch  # noqa: E402


def _recorded_experiments() -> dict:
    return json.loads(
        (S1005 / "results" / "boundary-experiments.json")
        .read_text(encoding="utf-8")
    )


def _seal(data: dict) -> None:
    payload = {k: v for k, v in data.items() if k != "output_sha256"}
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    data["output_sha256"] = hashlib.sha256(canonical).hexdigest()


class ExperimentProvenanceTests(TestCase):
    def _assert_rejected(self, mutate, pattern: str, *,
                         verify_script_hashes: bool = False) -> None:
        data = copy.deepcopy(_recorded_experiments())
        mutate(data)
        _seal(data)
        with self.assertRaisesRegex(ValueError, pattern):
            exp.validate_experiment_result(
                data,
                expected_commit=data["commit"],
                verify_script_hashes=verify_script_hashes,
            )

    def test_fabricated_tree_sha_is_rejected(self):
        self._assert_rejected(
            lambda data: data.__setitem__("tree_sha", "0" * 40),
            "tree_sha does not match",
        )

    def test_partial_script_hash_manifest_is_rejected(self):
        def mutate(data):
            data["script_hashes"] = {
                "experiments.py": data["script_hashes"]["experiments.py"]
            }

        self._assert_rejected(
            mutate,
            "script_hashes must contain exactly",
            verify_script_hashes=True,
        )

    def test_malformed_script_digest_is_rejected(self):
        def mutate(data):
            data["script_hashes"]["experiments.py"] = "0" * 63

        self._assert_rejected(
            mutate,
            "is not a 64-hex sha256",
            verify_script_hashes=True,
        )

    def test_transport_count_keys_must_be_exact(self):
        def mutate(data):
            for name in ("small_512b", "large_16kb"):
                rounds = data["experiments"][name]["rounds"]
                data["experiments"][name]["validated_counts"] = {
                    "x": rounds,
                    "y": rounds,
                    "z": rounds,
                }

        self._assert_rejected(mutate, "validated_counts keys")

    def test_git_head_failure_aborts_bundle_validation(self):
        failed = subprocess.CompletedProcess(
            ["git", "rev-parse", "HEAD"], 128, stdout="", stderr="fatal"
        )
        with mock.patch("subprocess.run", return_value=failed):
            with self.assertRaises(SystemExit):
                make_bundle.validate_experiments_data(_recorded_experiments())

    def test_run_experiments_returns_the_schema_valid_artifact_unchanged(self):
        recorded = _recorded_experiments()

        def fake_run(command, **_kwargs):
            output = Path(command[-1])
            output.write_text(
                json.dumps(recorded, indent=2) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "boundary-experiments.json"
            with mock.patch.object(make_bundle.subprocess, "run", side_effect=fake_run), \
                    mock.patch.object(
                        make_bundle, "validate_experiments_data", return_value=recorded
                    ):
                result = make_bundle.run_experiments(out_path=output)

            self.assertEqual(result, recorded)
            self.assertEqual(result["output_sha256"], recorded["output_sha256"])


class AutoresearchWorktreeCopyTests(TestCase):
    def test_only_explicit_generated_entries_are_ignored(self):
        ignored = autoresearch._ignore_generated_entries(
            "unused",
            [".agentos-demo", "__pycache__", "module.pyc", "evals", "critical.py"],
        )
        self.assertEqual(
            set(ignored), {".agentos-demo", "__pycache__", "module.pyc"}
        )

    def test_copy_failure_is_not_silently_downgraded(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            (repo / "src" / "agentos").mkdir(parents=True, exist_ok=True)
            for name in ("evals", "spec"):
                (repo / name).mkdir(parents=True, exist_ok=True)
            runner = autoresearch.Autoresearch(
                db=None, root_dir=Path(tmp) / "root", stage_evals=None,
                repo_source=repo,
            )
            with mock.patch.object(
                autoresearch.shutil, "copytree", side_effect=PermissionError("locked")
            ):
                with self.assertRaises(PermissionError):
                    runner._new_worktree()
