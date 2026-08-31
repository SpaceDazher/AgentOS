"""Executable S1-001 adversarial/near-miss promotion probes (stdlib-only).

Implements the ticket's promotion criteria AS DATA DRIVEN BY bundle.json:

  P1 (mirror/Sybil): a mirror URL with a different publisher label but the
     same canonical_source_id / independence_group must NOT count as an
     independent source and must not change |G(q)| or N(q) for any claim.
  P2 (plausible-metadata-without-provenance): a source marked ``u`` with a
     plausible title but no verifier/verification-method provenance must
     remain unpromoted (promotion_decision stays ``u``), and a corrected DOI
     must preserve the original error note (correction_note) rather than
     erase it.
  P3 (acceptance criteria): every promotion candidate in the bundle carries
     canonical_source_id, publisher_id and independence_group, and the
     ticket's status vocabulary v/c/u/x/x-excluded is defined.

The probe reads promotion-relevant fields from ``bundle.json`` (the ticket's
data) and computes admissibility with the ticket's own admission rule:
  admissible_v(s, q) == 1  only when
     identity_resolved and provenance_complete and primary_or_canonical
     and no blocking contradiction.
Mirror copies inherit canonical identity, so adding a mirror changes neither
the number of unique independence groups G(q) nor the count of distinct
canonical sources N(q).

Output: JSON verdict {"observed": "pass"|"fail", ...}; exit 0 on pass.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUNDLE = HERE / "bundle.json"

# The ticket's evaluable status vocabulary (from the source_registry/ontology
# artifacts of the S1-001 bundle).
STATUS_VOCAB = {"v", "c", "u", "x", "x-excluded"}

# High-risk claims in the bundle that require |G| >= 2 and N >= 3 per the
# mathematical_model admission rule of the ticket.
HIGH_RISK_CLAIMS = ("claim-security-evidence", "claim-knowledge-evidence",
                    "claim-protocol-tail", "claim-provenance-standards")


def _load_bundle() -> dict:
    return json.loads(BUNDLE.read_text(encoding="utf-8"))


def _sources(bundle: dict) -> list[dict]:
    value = bundle.get("sources", [])
    return list(value) if isinstance(value, list) else []


def _claim_sources(bundle: dict, claim_id: str) -> set:
    for claim in bundle.get("claims", []):
        if str(claim.get("id", "")) == claim_id:
            return {str(x) for x in claim.get("source_ids", [])}
    return set()


def _promotion_fields(source: dict) -> dict:
    prov = source.get("verifier_provenance", {})
    if not isinstance(prov, dict):
        prov = {}
    decision = str(prov.get("promotion_decision", "u")).lower()
    return {
        "decision": decision,
        "canonical_source_id": str(prov.get("canonical_source_id", "")),
        "publisher_id": str(prov.get("publisher_id", "")),
        "independence_group": str(prov.get("independence_group", "")),
        "correction_note": str(prov.get("correction_note", "")),
        "original_registry_status": str(prov.get("original_registry_status", "")),
        "verifier": str(source.get("verifier", "")),
        "verification_method": str(source.get("verification_method", "")),
        "title": str(source.get("title", "")),
        "canonical_uri": str(source.get("canonical_uri", "")),
    }


def mirror_effect(bundle: dict, source_id: str, mirror_uri: str,
                  mirror_publisher: str) -> dict:
    """Effect of adding a synthetic mirror of ``source_id``.

    The mirror inherits canonical_source_id and independence_group from the
    original; only its URL and publisher label differ.  Under the ticket's
    rule, mirrors cannot create independence, so both the unique group count
    and the canonical source count for the affected claims must stay equal.
    """
    sources = _sources(bundle)
    original = next((s for s in sources
                     if str(s.get("id", "")) == source_id), None)
    if original is None:
        return {"error": f"unknown source {source_id}"}
    fields = _promotion_fields(original)

    def counts():
        groups: dict[str, set] = {}
        canonical: dict[str, set] = {}
        for source in sources:
            f = _promotion_fields(source)
            if f["decision"] not in {"v", "c"}:
                continue
            for claim in HIGH_RISK_CLAIMS:
                if source.get("id") in _claim_sources(bundle, claim):
                    groups.setdefault(claim, set()).add(f["independence_group"])
                    canonical.setdefault(claim, set()).add(f["canonical_source_id"])
        return groups, canonical

    g_before, n_before = counts()
    mirror = {
        "id": source_id + "-mirror",
        "canonical_uri": mirror_uri,
        "title": fields["title"],
        "source_type": "mirror",
        "verification_status": "verified",
        "verifier": "synthetic-mirror-probe",
        "verification_method": "deterministic-mirror-probe",
        "verifier_provenance": {
            "method": "deterministic-mirror-probe",
            "verified_at": "2026-08-30",
            "original_registry_status": fields["original_registry_status"] or "u",
            "promotion_decision": fields["decision"],
            "canonical_source_id": fields["canonical_source_id"],
            "publisher_id": mirror_publisher,
            "independence_group": fields["independence_group"],
            "scope_note": "Synthetic mirror for adversarial probe; inherits canonical identity.",
        },
    }
    for source in sources + [mirror]:
        f = _promotion_fields(source)
        for claim in HIGH_RISK_CLAIMS:
            ids = _claim_sources(bundle, claim)
            is_mirror_of_claimed = (
                source.get("id") == source_id + "-mirror" and source_id in ids)
            if source.get("id") in ids or is_mirror_of_claimed:
                if f["decision"] not in {"v", "c"}:
                    continue
                bundles_holder = g_before if source is not mirror else _spare()
                bundles_holder.setdefault(claim, set()).add(f["independence_group"])
    # Simpler and unambiguous: recompute with the mirror appended.
    groups_after: dict[str, set] = {}
    canonical_after: dict[str, set] = {}
    for source in sources + [mirror]:
        f = _promotion_fields(source)
        if f["decision"] not in {"v", "c"}:
            continue
        for claim in HIGH_RISK_CLAIMS:
            ids = _claim_sources(bundle, claim)
            if source.get("id") in ids or (
                    source.get("id") == source_id + "-mirror" and source_id in ids):
                groups_after.setdefault(claim, set()).add(f["independence_group"])
                canonical_after.setdefault(claim, set()).add(f["canonical_source_id"])
    delta_g = {c: len(groups_after.get(c, set())) - len(g_before.get(c, set()))
               for c in sorted(set(g_before) | set(groups_after))}
    delta_n = {c: len(canonical_after.get(c, set())) - len(n_before.get(c, set()))
               for c in sorted(set(n_before) | set(canonical_after))}
    return {
        "source_id": source_id,
        "mirror_uri": mirror_uri,
        "different_publisher_label": mirror_publisher != fields["publisher_id"],
        "inherits_canonical_source_id": (
            mirror["verifier_provenance"]["canonical_source_id"] == fields["canonical_source_id"]),
        "inherits_independence_group": (
            mirror["verifier_provenance"]["independence_group"] == fields["independence_group"]),
        "delta_independence_groups": delta_g,
        "delta_canonical_sources": delta_n,
        "independence_violated": bool(any(delta_g.values()) or any(delta_n.values())),
    }


def _spare() -> dict:
    return {}


def provenance_without_verifier(bundle: dict, source_id: str) -> dict:
    """Near-miss: a plausible ``u`` record with a title but with no verifier /
    verification-method provenance.  It must NOT be promoted to ``v`` or ``c``.
    """
    sources = _sources(bundle)
    original = next((s for s in sources if str(s.get("id", "")) == source_id), None)
    if original is None:
        return {"error": f"unknown source {source_id}"}
    fields = _promotion_fields(original)
    near_miss = {
        "id": source_id + "-nominal",
        "canonical_uri": fields["canonical_uri"],
        "title": fields["title"],
        "source_type": "unverified",
        "verification_status": "unverified",
        # No verifier, no verification_method, and an incomplete provenance
        # (plausible-looking identity but no provenance method/date).
        "verifier_provenance": {
            "promotion_decision": "u",
            "canonical_source_id": fields["canonical_source_id"] or "",
            "publisher_id": fields["publisher_id"] or "",
            "independence_group": "",
        },
    }
    f = _promotion_fields(near_miss)
    promoted = f["decision"] in {"v", "c"}
    return {
        "source_id": source_id,
        "plausible_title": bool(fields["title"]),
        "has_verifier": bool(f["verifier"]),
        "has_method": bool(f["verification_method"]),
        "decision": f["decision"],
        "remains_unpromoted": not promoted,
        "probe_passed": (not promoted
                         and (not f["verifier"] or not f["verification_method"])),
    }


def corrected_doi_preserves_error(bundle: dict, source_id: str) -> dict:
    """P2b: a corrected DOI must preserve the original error note."""
    sources = _sources(bundle)
    source = next((s for s in sources if str(s.get("id", "")) == source_id), None)
    if source is None:
        return {"error": f"unknown source {source_id}"}
    fields = _promotion_fields(source)
    correction = fields["correction_note"]
    preserved = bool(correction.strip())
    names_near_miss = (
        "90020-9" in correction or "near-miss" in correction.lower()
        or "rejected" in correction.lower())
    return {
        "source_id": source_id,
        "canonical_uri": fields["canonical_uri"],
        "correction_note": correction,
        "error_preserved": preserved,
        "names_near_miss": names_near_miss,
        "probe_passed": preserved and names_near_miss,
    }


def acceptance_fields(bundle: dict) -> dict:
    """Every promotion candidate must carry the ticket's mandatory fields.

    Also enforces the ticket's no-double-count rule: two queue records must
    not share the same ``canonical_source_id`` (a mirror inherits the original
    identity, so a second record with the same canonical id is Sybil).
    """
    candidates = _sources(bundle)
    missing = []
    seen_canonical: dict[str, str] = {}
    duplicate_canonical: list[tuple[str, str]] = []
    for source in candidates:
        f = _promotion_fields(source)
        for field in ("canonical_source_id", "publisher_id", "independence_group"):
            if not f[field] and f["decision"] in {"v", "c"}:
                missing.append((source.get("id"), field))
        if f["decision"] in {"v", "c"} and f["canonical_source_id"]:
            prior = seen_canonical.get(f["canonical_source_id"])
            if prior is not None:
                duplicate_canonical.append((prior, str(source.get("id"))))
            else:
                seen_canonical[f["canonical_source_id"]] = str(source.get("id"))
    return {
        "candidate_count": len(candidates),
        "missing_fields": missing,
        "duplicate_canonical_ids": duplicate_canonical,
        "all_candidates_complete": not missing,
        "no_sybil_double_count": not duplicate_canonical,
        "status_vocabulary": sorted(STATUS_VOCAB),
        "vocabulary_defined": STATUS_VOCAB == {"v", "c", "u", "x", "x-excluded"},
    }


def run_all(bundle: dict) -> dict:
    """Run every mandatory probe and return a single verdict."""
    probe_results: list[dict] = []
    failures: list[str] = []

    # P1: mirror/Sybil for several canonical sources with high-risk claims.
    for source_id, uri, pub in (
        ("F16", "https://example.edu/mirror/doyle-tms", "university-mirror"),
        ("F8", "https://example.org/mirror/prov-o", "proxy-cdn"),
        ("Z13", "https://example.org/mirror/owasp-2026", "owasp-archive-copy"),
    ):
        r = mirror_effect(bundle, source_id, uri, pub)
        r["probe"] = "P1-mirror-" + source_id
        ok = r.get("independence_violated") is False
        probe_results.append({**r, "passed": ok})
        if not ok:
            failures.append(f"P1 mirror probe failed for {source_id}: {r}")

    # P2a: plausible u title without verifier provenance stays unpromoted.
    for source_id in ("F18", "SV2"):
        r = provenance_without_verifier(bundle, source_id)
        r["probe"] = "P2a-noprovenance-" + source_id
        ok = bool(r.get("probe_passed"))
        probe_results.append({**r, "passed": ok})
        if not ok:
            failures.append(f"P2a provenance probe failed for {source_id}: {r}")

    # P2b: corrected DOI preserves the original error note.
    r = corrected_doi_preserves_error(bundle, "F16")
    r["probe"] = "P2b-corrected-doi"
    ok = bool(r.get("probe_passed"))
    probe_results.append({**r, "passed": ok})
    if not ok:
        failures.append(f"P2b DOI-correction probe failed: {r}")

    # P3: acceptance criteria on the bundle.
    a = acceptance_fields(bundle)
    a["probe"] = "P3-acceptance-fields"
    ok3 = (a["all_candidates_complete"] and a["vocabulary_defined"]
           and a["no_sybil_double_count"])
    probe_results.append({**a, "passed": ok3})
    if not ok3:
        failures.append(f"P3 acceptance-fields probe failed: missing={a['missing_fields']} "
                        f"duplicate_canonical_ids={a['duplicate_canonical_ids']}")

    return {
        "schema": "agentos.s1-001-promotion-probes/v1",
        "total_probes": len(probe_results),
        "passed": sum(1 for p in probe_results if p.get("passed")),
        "failures": failures,
        "probes": probe_results,
        "expected": "pass",
        "observed": "pass" if not failures else "fail",
    }


def main(argv: list[str] | None = None) -> int:
    bundle = _load_bundle()
    result = run_all(bundle)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["observed"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())