#!/usr/bin/env python3
"""Fetch and freeze byte snapshots of official sources for S1-010.

Network is required ONLY when this script is run by the researcher during
Phase A preparation. Evaluation code and tests never touch the network; they
verify the frozen snapshots recorded in source-registry.json.

Each snapshot records: canonical URI, version/date, retrieval timestamp,
repo-relative snapshot path, byte length, and SHA-256.
"""
from __future__ import annotations

import hashlib
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

TICKET_ROOT = Path(__file__).resolve().parent
REPO_ROOT = TICKET_ROOT.parents[3]
SNAPSHOT_DIR = TICKET_ROOT / "snapshots"
REGISTRY_PATH = TICKET_ROOT / "source-registry.json"

SOURCES = [
    {
        "id": "src_mitre_atlas_taxonomy",
        "role": "threat_taxonomy",
        "canonical_uri": "https://github.com/mitre-atlas/atlas-data (dist/ATLAS.yaml)",
        "version": "MITRE ATLAS adversarial-ML taxonomy, atlas-data commit "
                   "41d4f5ca4112f0e492ffaa3ebff07dc80a75afa5",
        "urls": [],
        "internal_files": [],
        "external_file_imports": [
            ["/tmp/atlas-data/dist/ATLAS.yaml", "mitre-atlas-ATLAS.yaml"]
        ],
        "notes": "Primary adversarial-ML threat taxonomy maintained by MITRE: "
                 "includes LLM prompt injection (AML.T0051), poisoned training "
                 "data (AML.T0020), and agentic techniques used to derive the "
                 "S1-010 threat model classes.",
    },
    {
        "id": "src_cwe_74_injection",
        "role": "threat_taxonomy",
        "canonical_uri": "https://cwe.mitre.org/data/definitions/74.html",
        "version": "CWE 4.15 (weakness taxonomy entry CWE-74)",
        "urls": [("https://cwe.mitre.org/data/definitions/74.html",
                  "cwe-74-injection.html")],
        "notes": "Official weakness taxonomy entry for injection: improper "
                 "neutralization of special elements in output used by others; "
                 "grounds the output-injection and delimiting case classes.",
    },
    {
        "id": "src_slsa_v1_1",
        "role": "supply_chain_guidance",
        "canonical_uri": "https://slsa.dev/spec/v1.1/",
        "version": "SLSA v1.1",
        "urls": [("https://slsa.dev/spec/v1.1/", "slsa-v1.1-spec.html")],
        "notes": "Primary supply-chain integrity framework: provenance, "
                 "verification levels, and artifact attestation semantics.",
    },
    {
        "id": "src_nist_ssdf_sp800_218",
        "role": "supply_chain_guidance",
        "canonical_uri": "https://csrc.nist.gov/pubs/sp/800/218/final",
        "version": "NIST SP 800-218 (SSDF v1.1, 2022-02)",
        "urls": [("https://csrc.nist.gov/pubs/sp/800/218/final",
                  "nist-sp-800-218-landing.html")],
        "notes": "Primary software supply-chain guidance: provenance of build "
                 "inputs and verification of component integrity (PO tasks).",
    },
    {
        "id": "src_agentos_gateway_spec",
        "role": "gateway_architecture",
        "canonical_uri": "repo://AgentOS/src/agentos/gateway.py",
        "version": "branch codex/s1-010-tool-poisoning @ a0116167e0351beb1eef804d83845890be7253c9",
        "urls": [],
        "internal_files": [
            ["src/agentos/gateway.py", "agentos-gateway.py"],
            ["spec/SPEC.md", "agentos-spec.md"]
        ],
        "notes": "Internal primary source: ToolContract, capability checks, "
                 "exact-action approvals, effect classes "
                 "(read|write_local|write_external|dangerous), idempotency, "
                 "fencing. Snapshot is the tracked repo file itself.",
    },
    {
        "id": "src_wilson_ci_nist_handbook",
        "role": "statistical_method",
        "canonical_uri": "https://www.itl.nist.gov/div898/handbook/prc/section2/prc241.htm",
        "version": "NIST/SEMATECH e-Handbook of Statistical Methods, §7.2.2.1",
        "urls": [("https://www.itl.nist.gov/div898/handbook/prc/section2/prc241.htm",
                  "nist-handbook-prc241.html")],
        "notes": "Primary statistical method reference for confidence intervals "
                 "on a binomial proportion (Wilson score interval implementation "
                 "in evaluator is validated against this method family).",
    },
]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(url: str, dest: Path) -> dict:
    req = urllib.request.Request(
        url, headers={"User-Agent": "AgentOS-S1-010-research/1.0 (+repo-internal)"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = resp.read()
    if not data:
        raise RuntimeError(f"empty snapshot body for {url}")
    dest.write_bytes(data)
    return {
        "snapshot_path": str(dest.relative_to(REPO_ROOT)).replace("\\", "/"),
        "byte_length": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds")
                          .replace("+00:00", "Z"),
        "content_type": resp.headers.get("Content-Type", ""),
    }


def internal_snapshots(source: dict) -> list[dict]:
    out = []
    for repo_path, snap_name in source.get("internal_files", []):
        src = REPO_ROOT / repo_path
        if not src.is_file():
            raise RuntimeError(f"internal source missing: {repo_path}")
        dest = SNAPSHOT_DIR / snap_name
        dest.write_bytes(src.read_bytes())
        out.append({
            "repo_relative_source": repo_path,
            "snapshot_path": str(dest.relative_to(REPO_ROOT)).replace("\\", "/"),
            "byte_length": dest.stat().st_size,
            "sha256": sha256_file(dest),
            "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds")
                              .replace("+00:00", "Z"),
            "content_type": "text/x-python; repo-tracked",
        })
    return out


def import_external_files(source: dict) -> list[dict]:
    """Import byte-frozen files obtained from a pinned git clone (network was
    used once by the researcher; the imported file is hash-bound here)."""
    out = []
    for src_path, snap_name in source.get("external_file_imports", []):
        src = Path(src_path)
        if not src.is_file():
            raise RuntimeError(f"pinned external file missing: {src_path}")
        dest = SNAPSHOT_DIR / snap_name
        dest.write_bytes(src.read_bytes())
        out.append({
            "imported_from": src_path,
            "snapshot_path": str(dest.relative_to(REPO_ROOT)).replace("\\", "/"),
            "byte_length": dest.stat().st_size,
            "sha256": sha256_file(dest),
            "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds")
                              .replace("+00:00", "Z"),
            "content_type": "application/yaml; pinned git export",
        })
    return out


def main() -> int:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    registry = {"schema": "agentos.s1-010.source-registry/v1",
                "ticket": "S1-010", "sources": []}
    failures = []
    for source in SOURCES:
        entry = dict(source)
        entry.pop("urls", None)
        entry.pop("internal_files", None)
        entry.pop("external_file_imports", None)
        snaps = []
        for url, name in source.get("urls", []):
            try:
                snaps.append(fetch(url, SNAPSHOT_DIR / name))
                snaps[-1]["fetched_uri"] = url
            except Exception as exc:  # noqa: BLE001 - fail-closed collection
                failures.append(f"{source['id']}: {url}: {exc}")
        try:
            snaps.extend(internal_snapshots(source))
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{source['id']}: internal: {exc}")
        try:
            snaps.extend(import_external_files(source))
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{source['id']}: import: {exc}")
        entry["snapshots"] = snaps
        registry["sources"].append(entry)
    registry["retrieval_note"] = (
        "Snapshots are frozen byte copies; tests and evaluation are offline and "
        "verify sha256 against this registry only.")
    REGISTRY_PATH.write_text(
        json.dumps(registry, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8")
    print(f"sources: {len(registry['sources'])}, snapshots: "
          f"{sum(len(s['snapshots']) for s in registry['sources'])}")
    if failures:
        print("FAILURES:", file=sys.stderr)
        for f in failures:
            print(" -", f, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
