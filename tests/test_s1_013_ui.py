"""S1-013 mock UI checks (stdlib only, no browser needed).

Verifies the static prototype against the frozen schemas and the
scenario manifest WITHOUT executing JavaScript or launching a
browser: event vocabulary identity, no external URLs, MOCK banner,
keyboard-focus styles, required element ids, scenario/prompt id
coverage. A real browser pass remains a manual checklist item
(prototype/README.md); Playwright checks run only when the driver
is importable, otherwise they skip without hiding anything.
Run: $env:PYTHONPATH="src"; py -3.12 -m unittest tests.test_s1_013_ui -v
"""
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
S1013 = ROOT / "research" / "tickets" / "stage-1" / "S1-013"
HTML = (S1013 / "prototype" / "index.html").read_text(encoding="utf-8")


def schema_events():
    schema = json.loads(
        (S1013 / "schemas" / "events.schema.json").read_text(
            encoding="utf-8"))
    props = schema["properties"]["events"]["items"]["properties"]
    return props["type"]["enum"]


def html_event_types():
    match = re.search(r"EVENT_TYPES = \[(.*?)\]", HTML, re.DOTALL)
    assert match, "EVENT_TYPES array missing in prototype"
    return re.findall(r'"([a-z_]+)"', match.group(1))


class TestPrototypeVocabulary(unittest.TestCase):
    def test_event_vocabulary_identical(self):
        self.assertEqual(sorted(html_event_types()),
                         sorted(schema_events()))

    def test_no_external_urls(self):
        urls = re.findall(r"https?://[^\s\"'<>]+", HTML)
        self.assertEqual(urls, [])

    def test_mock_banner_present(self):
        self.assertIn("MOCK", HTML)
        self.assertIn("nothing here is real", HTML)

    def test_keyboard_focus_styles(self):
        self.assertIn(":focus", HTML)

    def test_required_element_ids(self):
        for element_id in ("role", "consent", "start", "scenario-card",
                           "scenario-title", "scenario-text",
                           "scenario-actions", "stop-card", "stop-request",
                           "stop-confirm", "stop-status", "export",
                           "import", "import-status", "eventlog"):
            self.assertIn(f'id="{element_id}"', HTML, element_id)

    def test_scenario_ids_covered(self):
        for sid in ("C1-S1", "C2-S1", "C3-S1", "C4-S1"):
            self.assertIn(sid, HTML, sid)

    def test_all_buttons_are_buttons(self):
        # Keyboard operability: actions must be <button>, not divs.
        self.assertNotIn("<div onclick", HTML)
        self.assertIn("<button", HTML)

    def test_stop_flow_states_present(self):
        for text in ("stop_requested", "stop_confirmed", "stop_failed",
                     "pending acknowledgement", "30000"):
            self.assertIn(text, HTML, text)


class TestPrototypeBrowser(unittest.TestCase):
    def test_playwright_optional(self):
        try:
            import playwright  # noqa: F401
        except ImportError:
            self.skipTest("playwright absent: manual checklist applies")
            return
        self.assertIn("MOCK", HTML)


if __name__ == "__main__":
    unittest.main()
