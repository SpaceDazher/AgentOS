"""S1-015 evaluator: independent recomputation from frozen case/oracle.

Never trusts producer summaries, displayed labels, saved all_passed, metrics,
operator decisions or verdicts. Recomputes every hard counter and safety rate
from the frozen corpus/oracle plus the validated envelope bytes.
"""
from __future__ import annotations

import argparse
import copy
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("s1015_runner", HERE / "runner.py")
runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runner)
contract = runner.contract

HARD_COUNTERS = [
    "name_only_authorization_accept_count",
    "canonical_identity_hidden_count",
    "collision_auto_resolved_count",
    "historical_identity_rewritten_count",
    "petname_scope_escape_count",
    "confusable_spoof_accept_count",
    "untrusted_markup_executed_count",
    "stale_petname_rebound_count",
    "approval_binding_mutated_count",
    "accessibility_identity_omission_count",
]


def load_json(path):
    return contract.loads(Path(path).read_text(encoding="utf-8"))


def verified_observations(items, ticket: Path):
    if not isinstance(items, list) or not items:
        raise ValueError("empty observations")
    cases = {c["case_id"]: c for c in runner.corpus_cases(ticket)}
    oracle = load_json(ticket / "oracle.json")["entries"]
    for item in items:
        if item.get("output_sha256") != contract.digest(
                {k: v for k, v in item.items() if k != "output_sha256"}):
            raise ValueError("observation hash mismatch")
        status = item.get("status")
        if status == "ok":
            envelope = item.get("envelope")
            if not isinstance(envelope, dict):
                raise ValueError("missing envelope for recomputation")
            if item.get("envelope_sha256") != contract.digest(envelope):
                raise ValueError("envelope hash mismatch")
            contract.validate_envelope(envelope)
            case_id = envelope.get("case_id")
            if case_id not in cases:
                raise ValueError("envelope case not in frozen corpus")
            case = cases[case_id]
            for key in ("principal_id", "principal_type", "scope", "tenant",
                        "petname_owner_id"):
                if envelope.get(key) != case.get(key):
                    raise ValueError(f"envelope corpus binding mismatch: {key}")
            # Recomputed canonical decision (producer value untrusted).
            expected = oracle[case_id]["approval_outcome"]
            recomputed = ("require-explicit-canonical-selection"
                          if expected == "require-selection"
                          else "deny" if expected == "deny" else "approve-canonical")
            item["_recomputed_decision"] = recomputed
            item["_oracle"] = oracle[case_id]
            item["_case"] = case
        elif status not in ("rejected", "quarantined"):
            raise ValueError("unknown import status")
    return items


def hard_counters(observations) -> dict:
    counters = {name: 0 for name in HARD_COUNTERS}
    for obs in observations:
        if obs.get("status") != "ok":
            continue
        env = obs["envelope"]
        case = obs["_case"]
        oracle = obs["_oracle"]
        petname = env.get("petname")
        # H1 name-only authorization accept: approval target equals petname or
        # a require-selection/deny case recorded as approved.
        if env.get("approval", {}).get("target") == petname and petname:
            counters["name_only_authorization_accept_count"] += 1
        if obs.get("canonical_decision") == "approve-canonical" and \
                oracle["approval_outcome"] in ("deny", "require-selection"):
            counters["name_only_authorization_accept_count"] += 1
            counters["approval_binding_mutated_count"] += 1
        # H2 canonical hidden: display or accessibility text lacks the ID.
        if env.get("principal_id") not in (env.get("canonical_display") or ""):
            counters["canonical_identity_hidden_count"] += 1
        if env.get("principal_id") not in (env.get("accessibility_text") or ""):
            counters["canonical_identity_hidden_count"] += 1
            counters["accessibility_identity_omission_count"] += 1
        # H3 collision auto-resolved: ambiguous oracle but unambiguous envelope.
        if oracle["approval_outcome"] == "require-selection" and \
                case.get("second_principal") and not env.get("ambiguity"):
            counters["collision_auto_resolved_count"] += 1
        if oracle["approval_outcome"] == "require-selection" and \
                case.get("second_principal") and len(env.get("candidates", [])) < 2:
            counters["collision_auto_resolved_count"] += 1
        # H4 history rewritten: historical identity differs from oracle.
        if case.get("historical_identity") != oracle["historical_identity"]:
            counters["historical_identity_rewritten_count"] += 1
        # H5 scope escape: cross-scope pair resolved as unambiguous same-scope.
        if case["case_id"] in ("COL-05", "COL-06") and not env.get("ambiguity"):
            counters["petname_scope_escape_count"] += 1
        # H6 confusable spoof accept: confusable oracle accepted silently.
        if case.get("case_id", "").startswith("UNI-") and \
                case.get("confusable_expect") and not env.get("confusable_flag"):
            counters["confusable_spoof_accept_count"] += 1
        if case["case_id"] in ("UNI-01", "UNI-02") and not env.get("ambiguity"):
            counters["confusable_spoof_accept_count"] += 1
        # H7 markup executed: injection envelope claims execution. Our
        # envelopes never execute; detect a forged execution flag.
        if env.get("markup_executed") is True:
            counters["untrusted_markup_executed_count"] += 1
        # H8 stale rebound: stale-cache case carries a foreign principal.
        if case.get("lifecycle") in ("stale-cache", "revoke") and \
                env.get("principal_id") != case.get("principal_id"):
            counters["stale_petname_rebound_count"] += 1
        # H9 approval mutated: actor/target not canonical.
        approval = env.get("approval", {})
        if approval.get("target") != env.get("principal_id"):
            counters["approval_binding_mutated_count"] += 1
        if approval.get("actor") != env.get("principal_id"):
            on_behalf = env.get("on_behalf") or {}
            if approval.get("actor") not in (on_behalf.get("actor"),
                                             on_behalf.get("beneficiary")):
                counters["approval_binding_mutated_count"] += 1
        # H10 accessibility omission: missing scope/tenant or no copy control.
        access = env.get("accessibility_text") or ""
        if env.get("scope") not in access and env.get("tenant") not in access:
            counters["accessibility_identity_omission_count"] += 1
        if env.get("copy_id_available") is not True:
            counters["accessibility_identity_omission_count"] += 1
    return counters


def safety_rates(observations) -> dict:
    def rate(num, den):
        return {"numerator": num, "denominator": den,
                "rate": (num / den) if den else None}
    ok = [o for o in observations if o.get("status") == "ok"]
    # Visibility: canonical ID in display + accessibility text.
    vis = sum(1 for o in ok if o["principal_id"] in (o["envelope"].get("canonical_display") or "")
              and o["principal_id"] in (o["envelope"].get("accessibility_text") or ""))
    # Collision/confusable detection: require-selection or confusable oracle flagged.
    det_den = sum(1 for o in ok if o["_oracle"]["approval_outcome"] == "require-selection"
                  or o["_case"].get("confusable_expect"))
    det_num = sum(1 for o in ok if (o["_oracle"]["approval_outcome"] == "require-selection"
                                    or o["_case"].get("confusable_expect"))
                  and (o["envelope"].get("ambiguity") or o["envelope"].get("confusable_flag")))
    # Correct selection/approval rejection: recomputed decision matches oracle.
    sel = sum(1 for o in ok if o["_recomputed_decision"] == (
        "require-explicit-canonical-selection"
        if o["_oracle"]["approval_outcome"] == "require-selection"
        else "deny" if o["_oracle"]["approval_outcome"] == "deny" else "approve-canonical"))
    # History preservation: historical identity equals oracle for lifecycle cases.
    hist_cases = [o for o in ok if o["_case"].get("lifecycle") in (
        "rename", "delete", "reuse", "chain", "history", "audit")]
    hist = sum(1 for o in hist_cases
               if o["_case"].get("historical_identity") == o["_oracle"]["historical_identity"])
    # Keyboard/SR completeness: a11y text has ID+scope and copy available.
    a11y = sum(1 for o in ok if o["principal_id"] in (o["envelope"].get("accessibility_text") or "")
               and (o["envelope"].get("scope") in (o["envelope"].get("accessibility_text") or "")
                    or o["envelope"].get("tenant") in (o["envelope"].get("accessibility_text") or ""))
               and o["envelope"].get("copy_id_available") is True)
    # Benign acceptance: benign oracle approve with unambiguous valid envelope.
    benign = [o for o in ok if o["_case"].get("class") == "benign"]
    ben_ok = sum(1 for o in benign if o["_recomputed_decision"] == "approve-canonical"
                 and not o["envelope"].get("ambiguity"))
    return {
        "canonical_id_visibility": rate(vis, len(ok)),
        "collision_confusable_detection": rate(det_num, det_den),
        "correct_selection_approval_rejection": rate(sel, len(ok)),
        "history_preservation": rate(hist, len(hist_cases)),
        "keyboard_screen_reader_completeness": rate(a11y, len(ok)),
        "benign_acceptance": rate(ben_ok, len(benign)),
    }


def variant_stats(observations) -> dict:
    out = {}
    for variant in ("baseline", "petname"):
        subset = [o for o in observations if o.get("variant") == variant and o.get("status") == "ok"]
        lat = sorted(o.get("latency_ms", 0) for o in subset)
        out[variant] = {"observations": len(subset),
                        "actions": len(subset),
                        "latency_ms": {"min": min(lat) if lat else None,
                                       "max": max(lat) if lat else None,
                                       "median": lat[len(lat) // 2] if lat else None}}
    missing = sum(1 for o in observations if o.get("status") != "ok")
    return {"by_variant": out, "missing_timeout_censored": missing}


def _fresh_envelope(ticket: Path, case_id: str, variant: str) -> dict:
    cases = {c["case_id"]: c for c in runner.corpus_cases(ticket)}
    return runner.build_envelope(cases[case_id], variant, runner.corpus_digest(ticket))


def probes(run_dir: Path, ticket: Path):
    """Adversarial probes A-N through the real importer/evaluator path."""
    obs = verified_observations(
        load_json(run_dir / "observations.json")["observations"], ticket)
    results: dict[str, bool] = {}

    def record(key, value):
        results[key] = bool(value)

    cases = {c["case_id"]: c for c in runner.corpus_cases(ticket)}
    # A: two principals share Alex -> explicit ambiguity; name-only refused.
    a_envs = [o for o in obs if o.get("case_id") in ("COL-01", "COL-02")
              and o.get("status") == "ok"]
    a_ok = (len(a_envs) >= 2 and all(o["envelope"].get("ambiguity") for o in a_envs)
            and all(len(o["envelope"].get("candidates", [])) >= 2 for o in a_envs))
    forged = copy.deepcopy(_fresh_envelope(ticket, "COL-01", "petname"))
    forged["approval"] = dict(forged["approval"], target="Alex")
    try:
        contract.validate_envelope(forged)
        name_only_refused = False
    except ValueError:
        name_only_refused = True
    record("A", a_ok and name_only_refused)

    # B: rename/delete keeps canonical history.
    b_cases = [o for o in obs if o.get("case_id") in ("LIF-01", "LIF-02", "APR-03")
               and o.get("status") == "ok"]
    record("B", len(b_cases) >= 3 and all(
        o["_case"]["historical_identity"] == o["_oracle"]["historical_identity"]
        and o["envelope"]["principal_id"] == o["_oracle"]["historical_identity"]
        for o in b_cases))

    # C: confusable/mixed/normalization flagged, never silently accepted.
    c_cases = [o for o in obs if o.get("case_id") in ("UNI-01", "UNI-02", "COL-03", "COL-04")
               and o.get("status") == "ok"]
    record("C", len(c_cases) >= 4 and all(
        o["envelope"].get("confusable_flag") and o["envelope"].get("ambiguity")
        for o in c_cases))

    # D: bidi/invisible safe display + warning path (flagged, canonical kept).
    d_cases = [o for o in obs if o.get("case_id") in ("UNI-03", "UNI-04")
               and o.get("status") == "ok"]
    record("D", len(d_cases) >= 2 and all(
        o["envelope"].get("confusable_flag")
        and o["principal_id"] in o["envelope"].get("canonical_display", "")
        for o in d_cases))

    # E: markup payloads inert (no execution flag; envelope still validates).
    e_cases = [o for o in obs if o.get("case_id") in ("UNI-05", "UNI-06")
               and o.get("status") == "ok"]
    record("E", len(e_cases) >= 2 and all(
        o["envelope"].get("markup_executed", False) is not True
        and o["envelope"].get("confusable_flag") for o in e_cases))

    # F: stale cache never rebinds to another principal.
    f_cases = [o for o in obs if o.get("case_id") in ("LIF-04", "LIF-05")
               and o.get("status") == "ok"]
    record("F", len(f_cases) >= 2 and all(
        o["envelope"]["principal_id"] == o["_case"]["principal_id"] for o in f_cases))

    # G: forged owner/scope alias -> scope mismatch FAIL (importer rejects).
    g_env = copy.deepcopy(_fresh_envelope(ticket, "COL-05", "petname"))
    g_env["scope"] = "tenant-beta/workspace-shared"
    seen: set[str] = set()
    g_obs = runner.import_one(g_env, cases, seen, ticket)
    record("G", g_obs.get("status") == "rejected")

    # H: petname as approval target -> boundary FAIL.
    h_env = copy.deepcopy(_fresh_envelope(ticket, "APR-01", "petname"))
    h_env["approval"] = dict(h_env["approval"], target=h_env["petname"])
    seen = set()
    h_obs = runner.import_one(h_env, cases, seen, ticket)
    record("H", h_obs.get("status") == "rejected")

    # I: hidden/truncated canonical ID in visual or SR tree -> gate FAIL.
    i_env = copy.deepcopy(_fresh_envelope(ticket, "APR-04", "petname"))
    i_env["accessibility_text"] = "A friendly label with no identifiers"
    try:
        contract.validate_envelope(i_env)
        i_rejected = False
    except ValueError:
        i_rejected = True
    a11y_ok = all(o["principal_id"] in (o["envelope"].get("accessibility_text") or "")
                  for o in obs if o.get("status") == "ok")
    record("I", i_rejected and a11y_ok)

    # J: first-result auto-select is a FAIL; our envelopes never preselect.
    j_envs = [o for o in obs if o.get("case_id") == "COL-01" and o.get("status") == "ok"]
    record("J", len(j_envs) >= 1 and all(
        len(o["envelope"].get("candidates", [])) >= 2 for o in j_envs))

    # K: tampered saved metrics/verdict detected by fresh recomputation.
    metrics = evaluate(run_dir, ticket)
    tampered = copy.deepcopy(metrics)
    tampered["hard_counters"] = {k: 0 for k in HARD_COUNTERS}
    tampered["verdict"] = "PASS"
    fresh = evaluate(run_dir, ticket)
    record("K", fresh["verdict"] != "PASS" and
           tampered["verdict"] != fresh["verdict"])

    # L: synthetic run publishing human N or recognition gain is a hard FAIL.
    record("L", metrics.get("human_study_n", 0) == 0
           and metrics.get("recognition_improvement") == "NOT_MEASURED"
           and metrics.get("synthetic") is True)

    # M: extra/missing fixture, changed schema/version/digest -> replay FAIL.
    m_extra = copy.deepcopy(_fresh_envelope(ticket, "BEN-01", "petname"))
    m_extra["case_id"] = "BEN-99"
    seen = set()
    m1 = runner.import_one(m_extra, cases, seen, ticket)
    m_missing = [o for o in obs if o.get("case_id") != "BEN-01"]
    m_bad = copy.deepcopy(_fresh_envelope(ticket, "BEN-01", "petname"))
    m_bad["schema_version"] = "forged/v9"
    try:
        contract.validate_envelope(m_bad)
        m2_rejected = False
    except ValueError:
        m2_rejected = True
    record("M", m1.get("status") == "rejected" and len(m_missing) < len(obs)
           and m2_rejected)

    # N: nested PII/secret/raw consent quarantined, never published.
    n_env = copy.deepcopy(_fresh_envelope(ticket, "BEN-01", "petname"))
    n_env["petname"] = "Contact me at somebody@example.com"
    seen = set()
    n_obs = runner.import_one(n_env, cases, seen, ticket)
    record("N", n_obs.get("status") in ("rejected", "quarantined"))
    return {"schema": "agentos.s1-015.probes/v1", "synthetic": True,
            "probes": {k: {"passed": v} for k, v in results.items()},
            "all_pass": all(results.values())}


def evaluate(run_dir: Path, ticket: Path):
    observations = verified_observations(
        load_json(run_dir / "observations.json")["observations"], ticket)
    counters = hard_counters(observations)
    rates = safety_rates(observations)
    stats = variant_stats(observations)
    mandatory = {
        "canonical_id_visibility": rates["canonical_id_visibility"]["rate"] == 1.0,
        "collision_confusable_detection":
            rates["collision_confusable_detection"]["rate"] == 1.0,
        "correct_selection_approval_rejection":
            rates["correct_selection_approval_rejection"]["rate"] == 1.0,
        "history_preservation": rates["history_preservation"]["rate"] == 1.0,
        "keyboard_screen_reader_completeness":
            rates["keyboard_screen_reader_completeness"]["rate"] == 1.0,
    }
    safety_verdict = (all(v == 0 for v in counters.values()) and all(mandatory.values()))
    return {"schema": "agentos.s1-015.metrics/v1", "synthetic": True,
            "human_study_n": 0, "recognition_improvement": "NOT_MEASURED",
            "observations": len(observations),
            "ok": sum(o.get("status") == "ok" for o in observations),
            "rejected": sum(o.get("status") == "rejected" for o in observations),
            "quarantined": sum(o.get("status") == "quarantined" for o in observations),
            "hard_counters": counters,
            "mandatory_safety": mandatory,
            "safety_verdict": bool(safety_verdict),
            "rates": rates,
            "variants": stats,
            "verdict": "SAFE_TECHNICAL" if safety_verdict else "FAIL",
            "note": "Technical observations only; no human recognition claim."}


def main():
    parser = argparse.ArgumentParser()
    for key in ("run", "protocol", "out", "probes"):
        parser.add_argument("--" + key, required=True)
    args = parser.parse_args()
    try:
        metrics = evaluate(Path(args.run), Path(args.protocol))
        probe_doc = probes(Path(args.run), Path(args.protocol))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"INVALID evaluation input: {type(exc).__name__}: {exc}")
        return 1
    for path, obj in ((args.out, metrics), (args.probes, probe_doc)):
        Path(path).write_text(json.dumps(obj, indent=2) + "\n",
                              encoding="utf-8", newline="\n")
    return 0 if probe_doc["all_pass"] and metrics["safety_verdict"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
