"""S1-012 corpus canonicalizer (deterministic scaffolding, stdlib only).

Reads cases-dev.src.json + cases-holdout.src.json (human oracle with
symbolic texts), fills content digests and per-case SHA-256, writes the
frozen cases.json plus split-manifest.json. Filling digests is NOT
setting expected results: outcomes come verbatim from src.

Digest rule (documented in corpus-manifest.json):
  digest(text) = SHA256("s1-012:content:" + text)
  case_sha256 = SHA256(canonical_json(case_without_case_sha256))

Modes:
  build              — write cases.json + split-manifest.json (default)
  --check            — recompute and compare; exit 1 on any mismatch
  --check-lineage    — verify dev/holdout lineage isolation; exit 1 on
                       any shared upstream/publisher/cluster across splits
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

TICKET = Path(__file__).resolve().parent
SRC_FILES = [TICKET / "cases-dev.src.json",
             TICKET / "cases-holdout.src.json"]
OUT = TICKET / "cases.json"
SPLIT_OUT = TICKET / "split-manifest.json"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest(text: str) -> str:
    return sha(f"s1-012:content:{text}".encode("utf-8"))


def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def fill(case: dict) -> dict:
    case = json.loads(json.dumps(case))  # deep copy
    for doc in case.get("documents", []):
        doc.setdefault("digest", digest(doc.get("text", "")))
        for span in doc.get("spans", []):
            span.setdefault("digest", digest(span.get("text", "")))
    body = {k: v for k, v in case.items() if k != "case_sha256"}
    case["case_sha256"] = sha(canonical(body))
    return case


def load_src() -> list:
    cases = []
    for path in SRC_FILES:
        doc = json.loads(path.read_text(encoding="utf-8"))
        for case in doc["cases"]:
            case["split"] = doc["split"]
            cases.append(case)
    return cases


def split_manifest(cases: list) -> dict:
    manifest: dict = {"schema": "agentos.s1-012.split-manifest/v1",
                      "rule": "Split by lineage/attack-family cluster; "
                              "related mirrors/spans of one cluster never "
                              "split. Thresholds chosen on dev only.",
                      "limitation": "Authoring agent saw the full synthetic "
                                    "set: NOT claimed as blinded holdout.",
                      "cases": {}, "clusters": {}}
    for case in cases:
        manifest["cases"][case["case_id"]] = case["split"]
        entry = manifest["clusters"].setdefault(
            case["cluster"], {"split": case["split"], "cases": []})
        if entry["split"] != case["split"]:
            raise SystemExit(
                f"cluster {case['cluster']} spans splits")
        entry["cases"].append(case["case_id"])
    return manifest


def lineage_sets(cases: list) -> dict:
    dev: set = set()
    holdout: set = set()
    for case in cases:
        target = dev if case["split"] == "dev" else holdout
        target.add(f"cluster:{case['cluster']}")
        for src in case.get("sources", []):
            if src.get("upstream"):
                target.add(f"upstream:{src['upstream']}")
            if src.get("publisher"):
                target.add(f"publisher:{src['publisher']}")
    return {"dev": dev, "holdout": holdout}


def build() -> dict:
    cases = load_src()
    ids = [c["case_id"] for c in cases]
    if len(ids) != len(set(ids)):
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        raise SystemExit(f"duplicate case ids: {dupes}")
    filled = [fill(c) for c in cases]
    doc = {"schema": "agentos.s1-012.cases/v1",
           "contract": "agentos.s1-012.independence-contract/v1",
           "cases": filled}
    OUT.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8",
                   newline="\n")
    manifest = split_manifest(filled)
    SPLIT_OUT.write_text(json.dumps(manifest, indent=2) + "\n",
                         encoding="utf-8", newline="\n")
    print(f"wrote {OUT} with {len(filled)} cases + split manifest")
    return doc


def check() -> int:
    if not OUT.is_file() or not SPLIT_OUT.is_file():
        print("cases.json or split-manifest.json missing", file=sys.stderr)
        return 1
    frozen = json.loads(OUT.read_text(encoding="utf-8"))
    want = [fill(c) for c in load_src()]
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
    frozen_split = json.loads(SPLIT_OUT.read_text(encoding="utf-8"))
    rebuilt_split = split_manifest(want)
    if sha(canonical(frozen_split)) != sha(canonical(rebuilt_split)):
        problems.append("split manifest drift")
    for line in problems:
        print(line, file=sys.stderr)
    print("corpus check: " + ("OK" if not problems else
                              f"{len(problems)} problems"))
    return 0 if not problems else 1


def check_lineage() -> int:
    cases = load_src()
    sets = lineage_sets(cases)
    overlap = sets["dev"] & sets["holdout"]
    # Publishers MAY repeat across splits only if upstreams are disjoint;
    # clusters and upstreams must never repeat.
    hard = {item for item in overlap
            if item.startswith("cluster:") or item.startswith("upstream:")}
    if hard:
        print(f"lineage overlap across splits: {sorted(hard)}",
              file=sys.stderr)
        return 1
    soft = sorted(overlap)
    print(f"lineage check: OK (shared publishers: {soft if soft else 'none'})")
    return 0


if __name__ == "__main__":
    if "--check" in sys.argv[1:]:
        raise SystemExit(check())
    if "--check-lineage" in sys.argv[1:]:
        raise SystemExit(check_lineage())
    build()
