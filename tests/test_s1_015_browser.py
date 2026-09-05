"""S1-015 browser test: real Edge/Chromium process via Playwright (stdlib + playwright).

Runs the ticket's browser_probe.py into a D:-backed temp dir (system TEMP may
be small), then imports the exported envelopes through the ticket importer.
DOM-only assertions without a browser process are not evidence.

Run: $env:PYTHONPATH="src"; py -3.12 -m unittest tests.test_s1_015_browser -v
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
S1015 = ROOT / "research" / "tickets" / "stage-1" / "S1-015"


def _writable_tmp() -> Path:
    for candidate in (os.environ.get("S1015_TMPDIR"), r"D:\Temp-opencode",
                      tempfile.gettempdir()):
        if candidate and Path(candidate).is_dir():
            return Path(candidate)
    return Path(tempfile.gettempdir())


class TestBrowserProbe(unittest.TestCase):
    def test_real_browser_flow_and_import(self):
        tmp = Path(tempfile.mkdtemp(prefix="s1015-bt-", dir=str(_writable_tmp())))
        envelopes = tmp / "envelopes.json"
        env = dict(os.environ, TEMP=str(_writable_tmp()), TMP=str(_writable_tmp()))
        proc = subprocess.run(
            [sys.executable, str(S1015 / "prototype" / "browser_probe.py"),
             "--out", str(envelopes)],
            cwd=str(ROOT), capture_output=True, text=True, env=env, timeout=240)
        self.assertEqual(proc.returncode, 0, msg=proc.stderr[-2000:])
        summary = json.loads(proc.stdout.strip().splitlines()[-1])
        self.assertTrue(summary.get("synthetic"))
        self.assertEqual(summary.get("envelopes"), 80)
        self.assertIn("button-export-download", summary.get("checks", []))
        doc = json.loads(envelopes.read_text(encoding="utf-8"))
        self.assertEqual(doc.get("schema"), "agentos.s1-015.export/v1")
        self.assertEqual(len(doc.get("envelopes", [])), 80)
        variants = {e.get("variant") for e in doc["envelopes"]}
        self.assertEqual(variants, {"baseline", "petname"})
        # Every exported envelope passes the authoritative contract.
        sys.path.insert(0, str(S1015))
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "s1015_contract_bt", S1015 / "contract.py")
            contract = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(contract)
            for envelope in doc["envelopes"]:
                contract.validate_envelope(envelope)
                self.assertIn(envelope["principal_id"], envelope["canonical_display"])
                self.assertIn(envelope["principal_id"], envelope["accessibility_text"])
        finally:
            sys.path.remove(str(S1015))


if __name__ == "__main__":
    unittest.main()
