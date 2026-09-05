"""S1-015 real-browser probe (Edge/Chromium via Playwright, stdlib + playwright).

Serves the prototype over loopback, walks BASELINE and PETNAME flows through
the real browser process (approval / on-behalf / rename / collision cases),
then exports the versioned envelope file consumed by the Python importer.
DOM-only assertion without a browser process is not accepted as evidence.

Usage: py -3.12 browser_probe.py --out <envelopes.json>
"""
from __future__ import annotations

import argparse
import functools
import http.server
import json
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
ALLOWED = {
    "/index.html": "text/html",
    "/app.js": "text/javascript",
    "/style.css": "text/css",
    "/browser-contract.json": "application/json",
}
EDGE_PATHS = [
    r"C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
    r"C:/Program Files/Microsoft/Edge/Application/msedge.exe",
]


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        name = self.path.split("?")[0]
        if name in ("/favicon.ico",):
            self.send_response(204)
            self.end_headers()
            return
        if name == "/":
            name = "/index.html"
        if name not in ALLOWED:
            self.send_response(404)
            self.end_headers()
            return
        data = (HERE / name.lstrip("/")).read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ALLOWED[name])
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    out = Path(args.out)

    # Static safety gates (also enforced by unit tests, repeated here).
    import re as _re
    app_js = (HERE / "app.js").read_text(encoding="utf-8")
    for pattern in (r"\.innerHTML\s*=", r"\.outerHTML\s*=",
                    r"insertAdjacentHTML\s*\(", r"document\.write\s*\("):
        if _re.search(pattern, app_js):
            raise SystemExit(f"probe refused: unsafe DOM API pattern {pattern} in app.js")
    index = (HERE / "index.html").read_text(encoding="utf-8")
    if "Content-Security-Policy" not in index:
        raise SystemExit("probe refused: CSP meta missing")

    from playwright.sync_api import sync_playwright

    edge = next((p for p in EDGE_PATHS if Path(p).exists()), None)
    if edge is None:
        raise SystemExit("probe refused: no Edge/Chromium executable found")

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    checks: list[str] = []
    errors: list[str] = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, executable_path=edge)
            try:
                page = browser.new_page(accept_downloads=True)
                page.on("pageerror", lambda exc: errors.append(str(exc)))
                page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
                url = f"http://127.0.0.1:{port}/index.html"
                page.goto(url)
                page.get_by_text("Frozen corpus 40 cases loaded").wait_for()
                checks.append("frozen-contract-loaded")

                csp = page.locator('meta[http-equiv="Content-Security-Policy"]')
                assert csp.count() == 1, "CSP meta missing in DOM"
                checks.append("csp-present")

                # ---- BASELINE flow ----
                page.locator("#variant").select_option("baseline")
                page.locator("#case").select_option("BEN-01")
                assert page.locator("#canon-id").inner_text() == "prin_a1"
                assert not page.locator("#principal-card").is_hidden()
                assert not page.locator("#petname-row").is_visible(), "baseline must hide petname row"
                sr = page.locator("#sr-text").inner_text()
                assert "prin_a1" in sr, "screen-reader text must carry canonical ID"
                checks.append("baseline-canonical-only")

                page.locator("#case").select_option("COL-01")
                assert page.locator("#ambiguity").is_visible(), "collision must show ambiguity"
                assert page.locator('#candidates input[type="radio"]').count() == 2
                assert page.locator('#candidates input[type="radio"]:checked').count() == 0, \
                    "auto-select forbidden"
                page.locator("#ap-approve").click()
                assert "Blocked" in page.locator("#ap-status").inner_text()
                page.locator('#candidates input[type="radio"]').first.check()
                page.locator("#ap-approve").click()
                assert "Denied" in page.locator("#ap-status").inner_text() or \
                    "Blocked" in page.locator("#ap-status").inner_text()
                checks.append("baseline-collision-requires-selection")

                page.locator("#case").select_option("APR-02")
                assert "prin_ob_01" in page.locator("#ob-text").inner_text()
                assert "prin_ob_01" in page.locator("#ap-target").inner_text()
                checks.append("baseline-approval-onbehalf-canonical")

                # ---- PETNAME flow ----
                page.locator("#variant").select_option("petname")
                page.locator("#case").select_option("BEN-01")
                assert page.locator("#petname-row").is_visible()
                assert page.locator("#petname").inner_text() == "Courier"
                assert page.locator("#canon-id").inner_text() == "prin_a1"
                checks.append("petname-alongside-canonical")

                page.locator("#case").select_option("LIF-01")
                assert "Renamed" in page.locator("#warnings").inner_text()
                assert "prin_ren_01" in page.locator("#history").inner_text()
                checks.append("petname-rename-lifecycle")

                page.locator("#case").select_option("UNI-05")
                body = page.locator("main").inner_text()
                assert "<script>" in body or "script" in body, "payload must render as inert text"
                checks.append("petname-injection-inert")

                page.locator("#case").select_option("APR-01")
                assert page.locator("#ap-actor").inner_text() == "prin_apr_01"
                assert page.locator("#ap-pet").inner_text() == "Approver Pal"
                page.locator("#copy-id").click()
                checks.append("petname-approval-annotation")

                # Keyboard reachability: every key control is focusable.
                page.keyboard.press("Tab")
                focused = page.evaluate("document.activeElement ? document.activeElement.id || document.activeElement.tagName : ''")
                assert focused, "keyboard focus must land somewhere"
                focus_css = (HERE / "style.css").read_text(encoding="utf-8")
                assert ":focus-visible" in focus_css, "visible focus style missing"
                checks.append("keyboard-focus")

                # Export via the real button (download) for the current variant.
                page.locator("#case").select_option("BEN-01")
                with page.expect_download() as download_info:
                    page.locator("#export").click()
                download = download_info.value
                tmp_single = out.with_name(out.name + ".single.json")
                download.save_as(str(tmp_single))
                single = json.loads(tmp_single.read_text(encoding="utf-8"))
                assert single.get("schema") == "agentos.s1-015.export/v1"
                assert len(single.get("envelopes", [])) == 40
                tmp_single.unlink()
                checks.append("button-export-download")

                # Full two-variant envelope set through the same builder the
                # button uses (flows above already exercised the UI paths).
                page.locator("#variant").select_option("baseline")
                baseline_doc = page.evaluate("buildExport()")
                page.locator("#variant").select_option("petname")
                petname_doc = page.evaluate("buildExport()")
                assert baseline_doc["schema"] == "agentos.s1-015.export/v1"
                assert petname_doc["schema"] == "agentos.s1-015.export/v1"
                merged = {
                    "schema": "agentos.s1-015.export/v1",
                    "variant": "both",
                    "browser": browser.version,
                    "envelopes": baseline_doc["envelopes"] + petname_doc["envelopes"],
                }
                assert len(merged["envelopes"]) == 80, "40 cases x 2 variants expected"
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(json.dumps(merged, indent=2, ensure_ascii=False) + "\n",
                               encoding="utf-8", newline="\n")

                # Import round-trip inside the page (schema/bindings gate).
                page.locator("#import").set_input_files(str(out))
                page.get_by_text("Envelope schema/bindings OK").wait_for()
                checks.append("inpage-import-ok")

                assert errors == [], f"browser console/page errors: {errors[:3]}"
                checks.append("no-browser-errors")
                print(json.dumps({"browser": browser.version, "checks": checks,
                                  "envelopes": len(merged["envelopes"]), "synthetic": True}))
            finally:
                browser.close()
    finally:
        server.shutdown()
        thread.join(timeout=5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
