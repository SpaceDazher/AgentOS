"""Real browser -> canonical envelope -> Python importer -> scorer regression."""
import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
T=ROOT/"research/tickets/stage-1/S1-013"
def module(n):
    spec=importlib.util.spec_from_file_location("s1013_ui_"+n,T/(n+".py"))
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

class TestPrototypeContract(unittest.TestCase):
    def test_browser_contract_matches_canonical_inputs(self):
        c=module("runner").contract
        browser=json.loads((T/"prototype/browser-contract.json").read_text())
        self.assertEqual(browser["protocol"],c.load("pilot-protocol.json"))
        self.assertEqual(browser["contract_sha256"],c.digest(browser["protocol"]))
        self.assertEqual(browser["scenarios"],c.load("scenario-manifest.json"))
        for name in ("session","events","answers"):
            self.assertEqual(browser["schemas"][name],c.load("schemas/"+name+".schema.json"))

    def test_actual_planned_prompt_counts(self):
        c=json.loads((T/"scenario-manifest.json").read_text())
        self.assertEqual([len(b["prompts"]) for b in c["approval_blocks"] if b["feasible"]],[12,24])

    def test_no_external_telemetry_or_self_grading_button(self):
        js=(T/"prototype/app.js").read_text()
        html=(T/"prototype/index.html").read_text()
        self.assertNotIn("https://",js)
        self.assertNotIn("Record correct answer",html)
        self.assertNotIn("Date.now()",js)
        self.assertIn("performance.now()",js)

    def test_real_browser_export_import_and_score(self):
        node=shutil.which("node")
        self.assertIsNotNone(node,"Install/configure Node for required real browser check")
        with tempfile.TemporaryDirectory(prefix="s1013-browser-") as td:
            out=Path(td)/"browser.export.json"
            proc=subprocess.run([node,str(T/"prototype/browser_probe.cjs"),str(out)],
                capture_output=True,text=True,timeout=90,env=dict(os.environ))
            self.assertEqual(proc.returncode,0,proc.stdout+"\n"+proc.stderr)
            evidence=json.loads(proc.stdout.strip().splitlines()[-1])
            self.assertIn("stop-failure",evidence["checks"])
            runner=module("runner")
            obs=runner.import_export(json.loads(out.read_text()),set())
            self.assertEqual(obs["status"],"ok",obs)
            obs["output_sha256"]=runner.contract.digest(obs)
            imp=Path(td)/"observations.json"
            imp.write_text(json.dumps({"schema":"agentos.s1-013.observations/v1","observations":[obs]}))
            metrics=module("evaluator").evaluate(Path(td),T)
            self.assertEqual(metrics["human_n"],0)
            self.assertEqual(metrics["measures"]["C5"]["correct"],1)
            self.assertEqual(metrics["approvals"]["n"],36)
            self.assertEqual(metrics["measures"]["C4"]["missing"],1,
                "UI cannot appoint its own independent grader")
            self.assertIn("tired",metrics["prompt_rate_by_role"]["by_role"]["owner"]["participants"][0]["fatigue"])

if __name__=="__main__": unittest.main()
