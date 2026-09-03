"""S1-011 corpus canonicalizer (deterministic scaffolding, stdlib only).

Reads cases-a.src.json + cases-b.src.json (human-authored oracle with
symbolic ids), fills record digests and per-case SHA-256, writes the frozen
cases.json. Filling digests is NOT setting expected results: decisions,
transitions, reason codes and view expectations come verbatim from src.

Digest rule (documented in corpus-manifest.json):
  digest(symbolic_id) = SHA256("s1-011:digest:" + symbolic_id)
  case_sha256 = SHA256(canonical_json(case_without_case_sha256))

Modes:
  build  — write cases.json (default)
  check  — recompute and compare against cases.json; exit 1 on any mismatch
           (used by regression tests to reject stale/tampered corpus).
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

TICKET = Path(__file__).resolve().parent
SRC_FILES = [TICKET / "cases-a.src.json", TICKET / "cases-b.src.json"]
OUT = TICKET / "cases.json"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest(sym: str) -> str:
    return sha(f"s1-011:digest:{sym}".encode("utf-8"))


def canonical(obj: dict) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def fill(case: dict) -> dict:
    case = json.loads(json.dumps(case))  # deep copy
    assertion = case.get("assertion") or {}
    if "assertion_id" in assertion:
        assertion.setdefault("text_digest", digest(assertion["assertion_id"]))
    for ev in case.get("evidence", []):
        if "evidence_id" in ev:
            ev.setdefault("digest", digest(ev["evidence_id"]))
    challenge = case.get("challenge")
    if isinstance(challenge, dict) and "challenge_id" in challenge:
        challenge.setdefault("digest", digest(challenge["challenge_id"]))
    case["assertion"] = assertion
    if challenge is not None:
        case["challenge"] = challenge
    body = {k: v for k, v in case.items() if k != "case_sha256"}
    case["case_sha256"] = sha(canonical(body))
    return case


def build() -> dict:
    cases = []
    for path in SRC_FILES:
        doc = json.loads(path.read_text(encoding="utf-8"))
        cases.extend(doc["cases"])
    ids = [c["case_id"] for c in cases]
    if len(ids) != len(set(ids)):
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        raise SystemExit(f"duplicate case ids: {dupes}")
    doc = {"schema": "agentos.s1-011.cases/v1",
           "contract": "agentos.s1-011.knowledge-gate-contract/v1",
           "cases": [fill(c) for c in cases]}
    OUT.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8",
                   newline="\n")
    print(f"wrote {OUT} with {len(doc['cases'])} cases")
    return doc


def check() -> int:
    if not OUT.is_file():
        print("cases.json missing", file=sys.stderr)
        return 1
    frozen = json.loads(OUT.read_text(encoding="utf-8"))
    # Rebuild in memory without writing: re-run fill over src files.
    cases = []
    for path in SRC_FILES:
        doc = json.loads(path.read_text(encoding="utf-8"))
        cases.extend(doc["cases"])
    want = [fill(c) for c in cases]
    got = frozen.get("cases", [])
    problems = []
    if len(want) != len(got):
        problems.append(f"case count drift: frozen={len(got)} src={len(want)}")
    by_id = {c["case_id"]: c for c in got}
    for case in want:
        other = by_id.get(case["case_id"])
        if other is None:
            problems.append(f"missing case {case['case_id']}")
        elif sha(canonical(other)) != sha(canonical(case)):
            problems.append(f"tampered case {case['case_id']}")
    for line in problems:
        print(line, file=sys.stderr)
    print("corpus check: " + ("OK" if not problems else
                              f"{len(problems)} problems"))
    return 0 if not problems else 1


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--check":
        raise SystemExit(check())
    build()
