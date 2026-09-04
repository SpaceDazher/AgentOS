"""Independent negative controls for R1; synthetic fixtures only."""
import copy
import importlib.util
import json
import unittest
from pathlib import Path

T = Path(__file__).resolve().parents[1] / "research/tickets/stage-1/S1-013"


def module(name):
    spec = importlib.util.spec_from_file_location("s1013_r1_" + name, T / (name + ".py"))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


runner, evaluator = module("runner"), module("evaluator")


class BoundaryR1(unittest.TestCase):
    def setUp(self):
        self.docs = {k: json.loads((T / "synthetic/sessions" / ("happy-owner." + k + ".json")).read_text()) for k in ("session", "events", "answers")}

    def imported(self):
        return runner.import_session(self.docs["session"], self.docs["events"], self.docs["answers"], set())

    def test_valid_envelope(self):
        self.assertEqual(runner.import_export({"schema": "agentos.s1-013.export/v1", **self.docs}, set())["status"], "ok")

    def test_unknown_envelope_rejected(self):
        self.assertEqual(runner.import_export({"schema": "bogus", **self.docs}, set())["status"], "rejected")

    def test_versions_and_digest_fail_closed(self):
        for key in ("protocol_version", "contract_sha256"):
            with self.subTest(key=key):
                self.setUp(); self.docs["session"][key] = "f" * 64
                self.assertEqual(self.imported()["status"], "rejected")
        self.setUp(); self.docs["session"]["consent"]["version"] = "wrong"
        self.assertEqual(self.imported()["status"], "rejected")

    def test_unknown_field_and_wrong_type(self):
        for value in ("yes", 1, None):
            with self.subTest(value=value):
                self.docs["session"]["synthetic"] = value
                self.assertEqual(self.imported()["status"], "rejected")
        self.setUp(); self.docs["events"]["events"][0]["invented"] = True
        self.assertEqual(self.imported()["status"], "rejected")

    def test_privacy_all_documents(self):
        for doc in ("session", "events", "answers"):
            with self.subTest(doc=doc):
                self.setUp(); self.docs[doc]["contact"] = "synthetic@example.test"
                result = self.imported()
                self.assertEqual(result["status"], "quarantined")
                self.assertNotIn("synthetic@example.test", json.dumps(result))

    def test_non_monotonic_and_gapped_sequence(self):
        self.docs["events"]["events"][2]["t_ms"] = 0
        self.assertEqual(self.imported()["status"], "rejected")
        self.setUp(); self.docs["events"]["events"][0]["seq"] = 1
        self.assertEqual(self.imported()["status"], "rejected")

    def test_twenty_copies_never_twenty_participants(self):
        self.docs["answers"]["responses"] = [self.docs["answers"]["responses"][0]] * 20
        self.assertEqual(self.imported()["status"], "rejected")

    def test_forged_adjudication_cannot_override_oracle(self):
        response = self.docs["answers"]["responses"][2]
        response["primary"]["value"] = "yes"
        response["primary"]["explanation"] = "everyone reads private notes"
        response["rater2"] = {"value": "yes", "agree": True}
        response["adjudicated"] = "correct"
        result = evaluator.score_measures([self.imported()], T / "synthetic/sessions")
        self.assertEqual(result["C4"]["correct"], 0)

    def test_presented_missing_stays_in_denominator(self):
        self.docs["answers"]["responses"] = []
        events = self.docs["events"]["events"]
        events[:] = [e for e in events if e["type"] != "answer"]
        for i, event in enumerate(events): event["seq"] = i
        result = evaluator.score_measures([self.imported()], T / "synthetic/sessions")
        self.assertEqual(result["C4"]["n"], 1)
        self.assertEqual(result["C4"]["missing"], 1)

    def test_no_mock_ack_cannot_confirm(self):
        stop = next(e for e in self.docs["events"]["events"] if e["type"] == "stop_confirmed")
        stop["acknowledgements"] = [{"agent_id": "A-1", "state": "stopped"}]
        self.assertEqual(self.imported()["status"], "rejected")

    def test_rate_excludes_comprehension_and_time_origin(self):
        first = evaluator.prompt_rate([self.imported()], T / "synthetic/sessions")
        for event in self.docs["events"]["events"]: event["t_ms"] += 3_600_000
        second = evaluator.prompt_rate([self.imported()], T / "synthetic/sessions")
        self.assertEqual(first, second)
        self.assertEqual(first["by_role"]["owner"]["prompts"], 2)

    def test_real_human_is_refused(self):
        self.docs["session"]["synthetic"] = False
        self.docs["session"]["cohort"] = "human"
        self.assertEqual(self.imported()["status"], "rejected")

    def test_duplicate_session_cannot_change_participant(self):
        seen = set()
        first = runner.import_export({"schema": "agentos.s1-013.export/v1", **self.docs}, seen)
        self.assertEqual(first["status"], "ok")
        self.docs["session"]["participant_id"] = "P-ZZZZZZ"
        second = runner.import_export({"schema": "agentos.s1-013.export/v1", **self.docs}, seen)
        self.assertEqual(second["status"], "rejected")

    def test_displayed_actor_must_match_frozen_prompt(self):
        event = next(e for e in self.docs["events"]["events"] if e["type"] == "prompt_displayed" and e.get("prompt_id") == "AP-01")
        event["actor_shown"] = "different-agent"
        self.assertEqual(self.imported()["status"], "rejected")

    def test_duplicate_json_and_nonfinite_refused(self):
        for text in ('{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}'):
            with self.assertRaises(ValueError): runner.contract.loads(text)

    def test_raw_binding_and_empty_rejected(self):
        record = self.imported()
        record["output_sha256"] = runner.contract.digest(record)
        self.assertEqual(evaluator.verified_observations([record]), [record])
        record["record"]["session"]["role"] = "reviewer"
        with self.assertRaises(ValueError): evaluator.verified_observations([record])
        with self.assertRaises(ValueError): evaluator.verified_observations([])


if __name__ == "__main__": unittest.main()
