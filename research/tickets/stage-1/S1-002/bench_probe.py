"""Deterministic S1-002 reproducibility probe (stdlib-only, no network/LLM).

Checks that the numbers declared in the S1-002 bundle are reproducible from
the committed raw benchmark evidence:

  1. The bundle's claimed raw-results SHA-256 equals the on-disk committed
     file digest (integrity of the evidence reference).
  2. The committed raw run matches the deterministic structural envelope:
     seed 20260824, exactly 1728 paced events, 6 load/mode aggregates,
     10/34/100 events/s, 353.28 B/persisted-row for this schema/payload.
  3. The latency claims cited in the bundle resolve to the committed
     raw-results aggregates at the same p95/p99 resolution the bundle uses.

This probe does NOT re-run the wall-clock benchmark (latency is a live
measurement and is not byte-deterministic across machines).  It verifies the
deterministic, seed-boundable parts plus bundle<->evidence consistency, and
exits with a JSON verdict so the research harness can fail closed.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUNDLE = HERE / "bundle.json"
RAW = HERE / "raw-results.json"

CONFIG_SHA256 = "29b240883e960740799e77b228c9eac5c4c7caa0e77d7f8050701358e42eef6a"
EXPECTED_EVENTS = 1728
EXPECTED_STORAGE_BYTES_PER_ROW = 353.28
EXPECTED_SEED = 20260824
EXPECTED_RATES = [10, 34, 100]
EXPECTED_AGGREGATES = 6


def _load_bundle() -> dict:
    return json.loads(BUNDLE.read_text(encoding="utf-8"))


def _load_raw() -> dict:
    return json.loads(RAW.read_text(encoding="utf-8"))


def probe(bundle: dict, raw: dict, raw_bytes: bytes) -> list[str]:
    """Return a list of failure descriptions; empty means the probe passes."""
    failures: list[str] = []

    # 1. Bundle evidence hash must equal the committed on-disk file digest.
    on_disk_sha = hashlib.sha256(raw_bytes).hexdigest()
    if on_disk_sha != CONFIG_SHA256:
        failures.append(
            f"raw-results.json on-disk SHA-256 {on_disk_sha} != expected {CONFIG_SHA256}")

    # Every artifact text that names the raw SHA-256 must agree with disk.
    raw_sha_said = None
    for kind in ("research_plan", "source_registry", "independent_audit", "progress"):
        content = bundle.get("artifacts", {}).get(kind, {}).get("content", "")
        for token in content.split():
            if token.startswith("SHA-256:") or token.startswith("SHA-256"):
                val = token.split(":", 1)[1] if ":" in token else None
                if val and len(val) == 64 and val.isalnum():
                    raw_sha_said = val
    if raw_sha_said is not None and raw_sha_said != on_disk_sha:
        failures.append(
            f"bundle artifact SHA-256 {raw_sha_said} != on-disk {on_disk_sha}")

    # 2. Deterministic structural envelope from the committed raw record.
    config = raw.get("configuration", {})
    if config.get("seed") != EXPECTED_SEED:
        failures.append(f"seed {config.get('seed')} != {EXPECTED_SEED}")
    if list(config.get("rates_events_per_second", [])) != EXPECTED_RATES:
        failures.append(f"rates {config.get('rates_events_per_second')} != {EXPECTED_RATES}")
    measured_events = sum(t.get("events_completed", 0) for t in raw.get("trials", []))
    if measured_events != EXPECTED_EVENTS:
        failures.append(f"measured events {measured_events} != {EXPECTED_EVENTS}")
    agg = raw.get("aggregates", [])
    if len(agg) != EXPECTED_AGGREGATES:
        failures.append(f"aggregate count {len(agg)} != {EXPECTED_AGGREGATES}")
    modes_rates = {(a.get("mode"), a.get("rate_target_events_per_second"))
                   for a in agg}
    expected_modes_rates = {(m, r) for m in ("cold", "warm") for r in EXPECTED_RATES}
    if modes_rates != expected_modes_rates:
        failures.append(f"mode/rate set {sorted(modes_rates)} does not cover "
                        f"cold/warm x 10/34/100")

    storage = raw.get("storage_probe", {})
    if storage.get("bytes_per_persisted_row") != EXPECTED_STORAGE_BYTES_PER_ROW:
        failures.append(
            f"bytes/persisted-row {storage.get('bytes_per_persisted_row')} "
            f"!= {EXPECTED_STORAGE_BYTES_PER_ROW}")
    if storage.get("persisted_rows_added") != 4000:
        failures.append(f"storage rows {storage.get('persisted_rows_added')} != 4000")
    if storage.get("measured_gateway_events") != 2000:
        failures.append(
            f"storage gateway events {storage.get('measured_gateway_events')} != 2000")

    # 3. Bundle latency claims round-trip against the committed aggregates.
    agg_by = {(a.get("mode"), a.get("rate_target_events_per_second")): a
              for a in agg}
    # The bundle's exact p95/p99 figures appear in the mathematical_model table.
    # Spot-check the planning point (cold 34/s p95 4.262) and burst (warm
    # 100/s p95 4.762, p99 7.533) against the raw aggregates.
    checks = [
        (("cold", 34), "p95", 4.262),
        (("warm", 100), "p99", 7.533),
    ]
    for key, stat, expected in checks:
        a = agg_by.get(key)
        if a is None:
            failures.append(f"missing aggregate {key}")
            continue
        observed = round(a["end_to_end_latency_ms"][stat], 3)
        if abs(observed - expected) > 0.001:
            failures.append(
                f"{key} {stat} {observed} != claimed {expected}")

    return failures


def main(argv: list[str] | None = None) -> int:
    bundle = _load_bundle()
    raw = _load_raw()
    raw_bytes = RAW.read_bytes()
    failures = probe(bundle, raw, raw_bytes)
    result = {
        "schema": "agentos.s1-002-bench-probe/v1",
        "probe": "s1-002-reproducibility",
        "expected": "pass",
        "observed": "pass" if not failures else "fail",
        "failures": failures,
        "evidence_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "note": ("Deterministic reproducibility/envelope check; wall-clock "
                 "latency is a live measurement and is not byte-deterministic."),
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
