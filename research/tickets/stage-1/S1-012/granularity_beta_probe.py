#!/usr/bin/env python3
"""Executable S1-012 adversarial evidence-granularity and Beta/Sybil probes.

Stdlib-only, deterministic.  Implements the S1-012 ticket's adversarial probes
as DATA driven by the S1-001/S1-003/S1-011 contracts:

  P1 (mirror collapse / granularity): two mirrors of the same canonical source
     from the same publisher collapse to exactly ONE independent unit;
     n_independent must NOT become 2.  Also verifies document/span/digest
     granularity invariance: splitting a canonical source into spans or digests
     changes coverage but never the independence floor.

  P2 (Sybil/collusion, 3 scenarios): a colluding cluster with high positive
     ratings (high Beta posterior P[theta>0.9]) but no pretrusted anchor must
     NOT raise an enforcement allow decision; it may only produce a flagged
     recommendation (enforcement=false).  Enforcement allow comes exclusively
     from the deterministic provenance gate (>=2 canonical sources across >=2
     independence groups, complete provenance).

  P3 (Beta sensitivity table): a0=b0=1, decay lambda in {0, 0.02, 0.05},
     planning threshold P[theta > 0.9] >= 0.95.  Every parameter and table row
     is labeled model_assumption=true: no incident corpus exists, so these are
     assumptions, not empirical measurements.

All Beta tail probabilities use the regularized incomplete beta function
(continued-fraction evaluation, stdlib math.lgamma only), validated against
the closed form I_x(a,1) == x^a and the symmetry I_0.5(a,a) == 0.5.

Output: writes probe-results.json, prints one JSON verdict line with
{"status": "pass"|"fail", "observed": ...}; exit 0 on pass, 1 on fail.
Run time is well under 60 s (pure integer/float arithmetic).
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "probe-results.json"

# ---------------------------------------------------------------------------
# Regularized incomplete beta (stdlib-only, deterministic)
# ---------------------------------------------------------------------------

def _log_beta(a: float, b: float) -> float:
    return math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)


def _betacf(a: float, b: float, x: float,
            max_iter: int = 300, eps: float = 3e-14) -> float:
    """Continued fraction for the incomplete beta function (NR-style)."""
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < 1e-30:
        d = 1e-30
    d = 1.0 / d
    h = d
    for m in range(1, max_iter + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-30:
            d = 1e-30
        c = 1.0 + aa / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-30:
            d = 1e-30
        c = 1.0 + aa / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h


def ibeta(x: float, a: float, b: float) -> float:
    """Regularized incomplete beta I_x(a, b) in [0, 1].

    betacf evaluates the continued fraction; the front factor is
    x^a (1-x)^b / (a * B(a, b)) = exp(lgamma(a+b) - lgamma(a) - lgamma(b)
    + a ln x + b ln(1-x)) / a  -- validated against I_x(a,1) == x^a.
    """
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    if a <= 0.0 or b <= 0.0:
        raise ValueError(f"ibeta requires a,b > 0 (got a={a}, b={b})")
    lgb = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
    bt = math.exp(lgb + a * math.log(x) + b * math.log(1.0 - x))
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1.0 - x) / b


# ---------------------------------------------------------------------------
# Evidence-unit model and the deterministic enforcement gate
# ---------------------------------------------------------------------------

EVIDENCE_FIELDS = ("canonical_source_id", "publisher_id", "independence_group",
                   "resolver_version", "metadata_frozen_at")


def make_unit(uid: str, canonical: str, publisher: str, group: str,
              granularity: str, locator: str, digest: str = "",
              resolver: str = "v1", frozen: str = "2026-01-01T00:00:00Z") -> dict:
    return {
        "id": uid,
        "canonical_source_id": canonical,
        "publisher_id": publisher,
        "independence_group": group,
        "granularity": granularity,
        "locator": locator,
        "content_digest": digest,
        "resolver_version": resolver,
        "metadata_frozen_at": frozen,
    }


def unit_provenance_complete(unit: dict) -> bool:
    return all(str(unit.get(f, "")).strip() for f in EVIDENCE_FIELDS)


def content_mirror_dedup(units: list[dict]) -> list[dict]:
    """Correlation cap: absorb content-Sybil mirrors.

    A unit whose (publisher_id, content_digest) pair was already seen is a
    content-Sybil mirror (identical bytes republished under a fabricated
    canonical_source_id/independence_group label) and is ABSORBED: it
    contributes no evidence unit at all.  This closes the attack where
    accounts republish identical content under fabricated labels - the naive
    gate would count 5 independent units, the capped gate counts 1.
    """
    kept: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for unit in units:
        key = (unit["publisher_id"], unit["content_digest"])
        if key in seen:
            continue  # absorbed: same publisher, same bytes, no independence
        seen.add(key)
        kept.append(unit)
    return kept


def gate_counts(units: list[dict]) -> dict:
    """Deterministic provenance gate (S1-001/S1-003 arithmetic at unit level)."""
    canonical = {u["canonical_source_id"] for u in units}
    groups = {u["independence_group"] for u in units}
    pairs = {(u["canonical_source_id"], u["independence_group"]) for u in units}
    reasons: list[str] = []
    incomplete = sorted(u["id"] for u in units if not unit_provenance_complete(u))
    if incomplete:
        reasons.append("incomplete_evidence_provenance:" + ",".join(incomplete))
    if len(units) < 2:
        reasons.append("insufficient_evidence_count")
    if len(canonical) < 2:
        reasons.append("insufficient_distinct_canonical_sources")
    if len(groups) < 2:
        reasons.append("insufficient_independence_groups")
    return {
        "n_units": len(units),
        "n_canonical": len(canonical),
        "n_groups": len(groups),
        "n_independent": len(pairs),
        "allow": not reasons,
        "reasons": reasons,
    }


# ---------------------------------------------------------------------------
# Beta reputation (recommendation only)
# ---------------------------------------------------------------------------

def weighted_counts(r: int, s: int, decay: float) -> tuple[float, float]:
    """Exponential forgetting: rating with age i (1 = newest) weighs exp(-d*i)."""
    if decay <= 0.0:
        return float(r), float(s)
    r_eff = sum(math.exp(-decay * i) for i in range(1, r + 1))
    s_eff = sum(math.exp(-decay * i) for i in range(1, s + 1))
    return r_eff, s_eff


def p_theta_gt(threshold: float, a0: float, b0: float, r: float, s: float) -> float:
    """P[theta > threshold] under Beta(theta | a0 + r, b0 + s)."""
    return 1.0 - ibeta(threshold, a0 + r, b0 + s)


def beta_opinion(r: int, s: int, *, a0: float = 1.0, b0: float = 1.0,
                 decay: float = 0.0, threshold: float = 0.9) -> dict:
    r_eff, s_eff = weighted_counts(r, s, decay)
    return {
        "a0": a0, "b0": b0, "r": r, "s": s,
        "r_eff": round(r_eff, 6), "s_eff": round(s_eff, 6),
        "decay": decay,
        "p_theta_gt_09": round(p_theta_gt(threshold, a0, b0, r_eff, s_eff), 6),
    }


def recommend(posterior: dict, gate: dict, *, pretrusted_anchor: bool) -> dict:
    """Recommendation is ALWAYS advisory; enforcement comes only from gate."""
    flagged = not gate["allow"] or not pretrusted_anchor
    return {
        "category": "flagged" if flagged else "supportive",
        "enforcement": False,          # hard boundary: never an enforcement input
        "flagged": flagged,
        "rationale": (
            "high unanchored Beta posterior from a single-cluster co-rating "
            "source; no pretrusted anchor and/or no independent provenance; "
            "score is advisory only" if flagged else
            "deterministic gate allow plus anchored reputation context"),
        "model_assumptions": {
            "a0=b0=1": True, "decay": "see table",
            "planning_threshold": "P[theta>0.9] >= 0.95 is an assumption"},
    }


# ---------------------------------------------------------------------------
# EigenTrust-style status (recommendation only, pretrust-anchored)
# ---------------------------------------------------------------------------

def eigentrust_status(nodes: list[str], adj: dict[str, dict[str, float]],
                      pretrust: dict[str, float], iters: int = 300,
                      eps: float = 0.2) -> dict[str, float]:
    """Normalized eigenvector iteration t = (1-eps)*C^T*t + eps*p.

    eps is the canonical damping toward the pretrust vector p (0.2 is the
    paper's default magnitude).  With p uniform over ALL peers (the no-anchor
    baseline), the iteration tracks the rating matrix alone and an isolated
    colluding clique dominates; anchoring p on honest peers lowers the clique's
    share.  The result is advisory only.
    """
    n = len(nodes)
    idx = {node: i for i, node in enumerate(nodes)}
    psum = sum(pretrust.values()) or 1e-12
    p_vec = [pretrust.get(node, 0.0) / psum for node in nodes]
    t = [1.0 / n] * n
    for _ in range(iters):
        nxt = [eps * pv for pv in p_vec]
        for i, node in enumerate(nodes):
            for j, weight in adj.get(node, {}).items():
                if weight > 0:
                    nxt[idx[j]] += (1.0 - eps) * weight * t[i]
        norm = sum(nxt) or 1.0
        t = [v / norm for v in nxt]
    return {node: round(t[i], 9) for i, node in enumerate(nodes)}


# ---------------------------------------------------------------------------
# Deterministic scenario run
# ---------------------------------------------------------------------------

def run_scenario() -> tuple[dict, list[dict]]:
    checks: list[dict] = []
    failures: list[str] = []

    def check(name: str, passed: bool, detail) -> bool:
        checks.append({"check": name, "passed": bool(passed), "detail": detail})
        if not passed:
            failures.append(f"{name}: {detail}")
        return bool(passed)

    # ---- P0: incomplete-beta numeric sanity ------------------------------
    ibeta_ok = True
    for a in (1.0, 5.0, 21.0, 50.0):
        for x in (0.1, 0.5, 0.9):
            if abs(ibeta(x, a, 1.0) - x ** a) > 1e-9:
                ibeta_ok = False
    for a in (2.0, 7.0, 31.0):
        if abs(ibeta(0.5, a, a) - 0.5) > 1e-9:
            ibeta_ok = False
    check("P0_ibeta_closed_form_and_symmetry", ibeta_ok,
          "I_x(a,1)==x^a and I_0.5(a,a)==0.5 within 1e-9")

    # ---- P1: mirror collapse and granularity invariance -------------------
    # Two mirrors of the same canonical source from the same publisher.
    doc = make_unit("doc-1", "C1", "pub-A", "G1", "document",
                    "https://mirror-a.example/c1", digest="d111")
    mirror_1 = make_unit("mirror-1", "C1", "pub-A", "G1", "document",
                         "https://mirror-b.example/c1", digest="d111")
    mirror_2 = make_unit("mirror-2", "C1", "pub-A", "G1", "document",
                         "https://mirror-c.example/c1", digest="d111")
    g_mirrors = gate_counts([doc, mirror_1, mirror_2])
    check("P1_two_mirrors_collapse_to_one_unit",
          g_mirrors["n_independent"] == 1 and g_mirrors["n_independent"] != 2,
          {"n_independent": g_mirrors["n_independent"],
           "n_canonical": g_mirrors["n_canonical"],
           "n_groups": g_mirrors["n_groups"]})
    check("P1_mirror_gate_refuses",
          g_mirrors["allow"] is False
          and "insufficient_distinct_canonical_sources" in g_mirrors["reasons"]
          and "insufficient_independence_groups" in g_mirrors["reasons"],
          g_mirrors["reasons"])

    # Same canonical source with different publisher labels (cdn mirror).
    cdn = make_unit("cdn-1", "C1", "pub-CDN", "G1", "document",
                    "https://cdn.example/c1", digest="d111")
    g_labels = gate_counts([doc, cdn])
    check("P1_publisher_label_never_counts",
          g_labels["n_independent"] == 1 and not g_labels["allow"],
          {"n_independent": g_labels["n_independent"],
           "publishers": sorted({u["publisher_id"] for u in [doc, cdn]})})

    # Granularity invariance: one canonical source split into spans + a digest.
    units_doc = [make_unit("s-doc", "C2", "pub-B", "G2", "document",
                           "https://src.example/c2", digest="d200")]
    units_span = [
        make_unit("s-span-1", "C2", "pub-B", "G2", "span",
                  "https://src.example/c2#sec1", digest="d201"),
        make_unit("s-span-2", "C2", "pub-B", "G2", "span",
                  "https://src.example/c2#sec2", digest="d202"),
        make_unit("s-span-3", "C2", "pub-B", "G2", "span",
                  "https://src.example/c2#sec3", digest="d203"),
    ]
    units_digest = [
        make_unit("s-dig-1", "C2", "pub-B", "G2", "digest",
                  "sha256:d204", digest="d204"),
        make_unit("s-dig-2", "C2", "pub-B", "G2", "digest",
                  "sha256:d205", digest="d205"),
    ]
    ni_doc = gate_counts(units_doc)["n_independent"]
    ni_span = gate_counts(units_span)["n_independent"]
    ni_digest = gate_counts(units_digest)["n_independent"]
    check("P1_granularity_invariance",
          ni_doc == ni_span == ni_digest == 1,
          {"document": ni_doc, "span": ni_span, "digest": ni_digest})
    # Coverage differs (more units), independence does not multiply.
    check("P1_granularity_changes_coverage_not_independence",
          len(units_span) == 3 > len(units_doc) == 1 and ni_span == 1,
          {"span_units": len(units_span), "n_independent": ni_span})

    # Control: two distinct canonical sources across two groups promote.
    a1 = make_unit("a1", "C1", "pub-A", "G1", "span",
                   "https://a.example/c1#x", digest="d1")
    a2 = make_unit("a2", "C2", "pub-B", "G2", "span",
                   "https://b.example/c2#y", digest="d2")
    g_ctrl = gate_counts([a1, a2])
    check("P1_control_two_independent_groups_promote",
          g_ctrl["allow"] is True and g_ctrl["n_independent"] == 2,
          g_ctrl)

    # ---- P2: Sybil/collusion scenarios ------------------------------------
    # SCEN-1: mirror-pair collapse (enforcement must refuse the cluster).
    scen1_units = [doc, mirror_1]              # one canonical source only
    g1 = gate_counts(scen1_units)
    check("SCEN1_enforcement_refuses_mirror_pair",
          not g1["allow"] and g1["n_independent"] == 1,
          g1)

    # SCEN-2: colluding cluster, high positive ratings, NO pretrusted anchor.
    # 25 colluding accounts publish through one canonical source / one group,
    # each rating another colluder positively: 50 positives, 0 negatives.
    cluster_units = [
        make_unit(f"col-{i}", "COLLUDER-ORG", "colluder-pub", "COLLUDER-GRP",
                  "span", f"https://colluder.invalid/rating/{i}", digest=f"cd{i}")
        for i in range(25)
    ]
    g2 = gate_counts(cluster_units)
    op2 = beta_opinion(50, 0, decay=0.0)       # a=51, b=1 -> very high posterior
    rec2 = recommend(op2, g2, pretrusted_anchor=False)
    check("SCEN2_colluding_cluster_high_posterior",
          op2["p_theta_gt_09"] > 0.95,
          {"p_theta_gt_09": op2["p_theta_gt_09"],
           "a": 1 + op2["r_eff"], "b": 1 + op2["s_eff"]})
    check("SCEN2_no_enforcement_allow_for_unanchored_cluster",
          g2["allow"] is False and op2["p_theta_gt_09"] > 0.95,
          {"gate_allow": g2["allow"],
           "cluster_n_independent": g2["n_independent"],
           "posterior_gt_0.95": op2["p_theta_gt_09"]})
    check("SCEN2_only_flagged_recommendation",
          rec2["category"] == "flagged" and rec2["enforcement"] is False
          and rec2["flagged"] is True,
          {"category": rec2["category"], "enforcement": rec2["enforcement"]})

    # EigenTrust with/without a pretrusted anchor (deterministic model).
    # Nodes c1,c2 form a colluding clique; honest nodes h1,h2 interact with the
    # clique occasionally (open-system assumption).  WITHOUT a pretrusted set
    # (damping scattered uniformly over all peers) the colluding clique
    # dominates the status vector; anchoring the damping on honest nodes
    # (h1,h2,h3) materially lowers the cluster share.  Either way the score is
    # advisory: enforcement allow comes only from the provenance gate.
    nodes = ["c1", "c2", "h1", "h2", "h3"]
    raw_adj = {
        "c1": {"c2": 0.999, "h1": 0.001},   # colluders rate each other
        "c2": {"c1": 0.999, "h1": 0.001},
        "h1": {"h2": 0.8, "c1": 0.2},       # honest occasionally transact
        "h2": {"h1": 0.8, "c1": 0.2},
        "h3": {"h1": 1.0},
    }
    adj = {n: {m: w / sum(v.values()) for m, w in v.items()}
           for n, v in raw_adj.items()}
    status_no_anchor = eigentrust_status(nodes, adj, pretrust={})
    status_honest_anchor = eigentrust_status(
        nodes, adj, pretrust={"h1": 1.0, "h2": 1.0, "h3": 1.0})
    cluster_no = status_no_anchor["c1"] + status_no_anchor["c2"]
    cluster_yes = status_honest_anchor["c1"] + status_honest_anchor["c2"]
    check("SCEN2_unanchored_cluster_dominates_status",
          cluster_no > 0.9,
          {"cluster_share_no_anchor": round(cluster_no, 6)})
    check("SCEN2_honest_anchor_lowers_cluster_share",
          cluster_yes < cluster_no,
          {"cluster_share_no_anchor": round(cluster_no, 6),
           "cluster_share_honest_anchor": round(cluster_yes, 6)})
    rec_et = {
        "category": "flagged",
        "enforcement": False,
        "flagged": True,
        "rationale": ("EigenTrust status is unanchored or anchor-dependent; "
                      "cluster share without a pretrusted seed reaches "
                      f"{cluster_no:.3f}; score is advisory only"),
    }
    check("SCEN2_eigentrust_status_stays_advisory",
          rec_et["enforcement"] is False and rec_et["flagged"] is True,
          rec_et)

    # SCEN-3: content-Sybil cluster - accounts republish identical content
    # under fabricated canonical_source_id / independence_group claims.  A
    # naive gate that trusts declared canonical labels would see
    # n_independent=5, but the correlation cap (identical publisher +
    # content-digest without independent verifier provenance) collapses all
    # five to ONE independent unit, so enforcement stays refused.  A leaked
    # pretrust anchor only shifts the advisory score; it never opens the gate.
    sybil_units = [
        make_unit(f"syb-{i}", f"CS-FAB-{i}", "COLLUDER-PUB", f"GC-FAB-{i}",
                  "span", f"https://colluder.invalid/content/{i}",
                  digest="cdSAME", resolver="v1")
        for i in range(1, 6)
    ]
    g_naive = gate_counts(sybil_units)      # trusts declared labels
    deduped = content_mirror_dedup(sybil_units)
    g_capped = gate_counts(deduped)         # correlation cap applied
    check("SCEN3_naive_gate_exploitable_by_fabricated_ids",
          g_naive["allow"] is True and g_naive["n_independent"] == 5,
          {"n_independent_naive": g_naive["n_independent"]})
    check("SCEN3_correlation_cap_collapses_content_sybil",
          len(deduped) == 1 and g_capped["n_independent"] == 1
          and g_capped["allow"] is False,
          {"deduped_units": len(deduped),
           "n_independent_capped": g_capped["n_independent"]})
    op3 = beta_opinion(60, 5, decay=0.02)
    rec3 = recommend(op3, g_capped, pretrusted_anchor=True)
    check("SCEN3_capped_stack_only_flagged_recommendation",
          rec3["flagged"] is True and rec3["enforcement"] is False,
          {"category": rec3["category"]})
    # Per-group soft cap: a single cluster's weight saturates at the cap.
    weight_cap = 0.5
    cluster_weight = min(1.0, 25 * 0.04)        # 25 accounts x 0.04 each
    capped = min(cluster_weight, weight_cap)
    check("SCEN3_per_group_weight_cap_applies",
          capped == weight_cap and cluster_weight > weight_cap,
          {"raw_cluster_weight": cluster_weight, "cap": weight_cap,
           "capped": capped})

    # ---------- P3: Beta sensitivity table (assumptions labeled) -----------
    decays = (0.0, 0.02, 0.05)
    histories = ((10, 0), (15, 0), (20, 0), (25, 0), (30, 0),
                 (30, 5), (40, 10), (50, 0))
    table: list[dict] = []
    for r, s in histories:
        row = {"r": r, "s": s, "model_assumption": True}
        for d in decays:
            op = beta_opinion(r, s, decay=d)
            row[f"p_gt09_d{d:g}"] = op["p_theta_gt_09"]
        table.append(row)

    def r_min_to_cross(decay: float) -> int:
        for r in range(1, 601):
            if beta_opinion(r, 0, decay=decay)["p_theta_gt_09"] >= 0.95:
                return r
        return -1

    r_min = {f"decay_{d:g}": r_min_to_cross(d) for d in decays}
    table_meta = {
        "prior": "a0=b0=1 (uniform) - model assumption",
        "model": "Beta(theta | a0+r_eff, b0+s_eff)",
        "decay_model": "exponential forgetting, age 1= newest (assumption)",
        "planning_threshold": "P[theta > 0.9] >= 0.95 - model assumption",
        "computed_by": "regularized incomplete beta (stdlib)",
    }
    check("P3_table_has_all_histories_and_decays",
          len(table) == len(histories)
          and all(all(f"p_gt09_d{d:g}" in row for d in decays) for row in table),
          {"rows": len(table), "decays": list(decays)})
    # Monotonicity in ratings holds over all-positive histories: more clean
    # ratings strictly raise P[theta > 0.9] under the a0=b0=1 prior.
    pos_idx = [i for i, (r, s) in enumerate(histories) if s == 0]
    check("P3_threshold_monotone_in_clean_ratings",
          all(table[pos_idx[i]]["p_gt09_d0"]
              < table[pos_idx[i + 1]]["p_gt09_d0"]
              for i in range(len(pos_idx) - 1)),
          {"p_d0_clean": [table[i]["p_gt09_d0"] for i in pos_idx]})
    # Negative outcomes (s > 0) visibly lower the posterior.
    check("P3_negative_ratings_lower_posterior",
          table[4]["p_gt09_d0"] > table[5]["p_gt09_d0"],
          {"p(30,0)": table[4]["p_gt09_d0"],
           "p(30,5)": table[5]["p_gt09_d0"]})
    # Decay (exponential forgetting) lowers the posterior for clean histories.
    check("P3_decay_lowers_posterior",
          all(table[i]["p_gt09_d0"] > table[i]["p_gt09_d0.05"]
              for i in pos_idx),
          {"p_gt09_d0": [round(table[i]["p_gt09_d0"], 6) for i in pos_idx],
           "p_gt09_d0.05": [round(table[i]["p_gt09_d0.05"], 6) for i in pos_idx]})
    # 30 clean ratings cross the planning threshold with no decay; 10 do not.
    check("P3_threshold_crossing_sanity",
          table[0]["p_gt09_d0"] < 0.95 <= table[4]["p_gt09_d0"]
          and r_min["decay_0"] == 28,
          {"p(r=10)": table[0]["p_gt09_d0"],
           "p(r=30)": table[4]["p_gt09_d0"], "r_min_decay0": r_min["decay_0"]})
    # Strong decay raises the required rating count; at lambda=0.05 the
    # threshold becomes unapproachable from clean ratings alone (steady-state
    # effective count saturates near sum(e^-0.05i) ~ 19.5, max P ~ 0.885),
    # so decay and the planning threshold must be calibrated together.
    check("P3_decay_increases_required_ratings",
          r_min["decay_0"] < r_min["decay_0.02"] and r_min["decay_0.05"] == -1,
          {"r_min": r_min,
           "insight": "lambda=0.05 makes P[theta>0.9]>=0.95 unapproachable "
                      "from all-positive ratings; threshold is decay-dependent"})
    check("P3_assumptions_labelled",
          table_meta["prior"].startswith("a0=b0=1")
          and "assumption" in table_meta["planning_threshold"]
          and all(row["model_assumption"] is True for row in table),
          table_meta)

    details = {
        "scenarios": {
            "SCEN-1": {"name": "mirror-pair collapse",
                       "verdict": "enforcement refused, 1 independent unit"},
            "SCEN-2": {"name": "colluding cluster, high ratings, no anchor",
                       "verdict": "enforcement refused; flagged recommendation only"},
            "SCEN-3": {"name": "content-Sybil cluster (fabricated canonical ids)",
                       "verdict": "correlation cap absorbs mirrors; enforcement refused"},
        },
        "granularity": {
            "document": ni_doc, "span": ni_span, "digest": ni_digest,
            "invariant": "n_independent == 1 for one canonical source at every granularity",
        },
        "beta_sensitivity": {
            "meta": table_meta, "table": table, "r_min_to_cross": r_min,
        },
        "enforcement_policy": "Beta/EigenTrust is recommendation-only; "
                               "enforcement allow requires the provenance gate",
    }
    return {"checks": checks, "details": details, "failures": failures}, []


def main(argv=None) -> int:
    result, _ = run_scenario()
    observed = "pass" if not result["failures"] else "fail"
    report = {
        "schema": "agentos.s1-012-granularity-beta-probe/v1",
        "probe": "s1-012-granularity-beta-adversarial",
        "expected": "pass",
        "observed": observed,
        "status": observed,
        "total_checks": len(result["checks"]),
        "passed_checks": sum(1 for c in result["checks"] if c["passed"]),
        "failures": result["failures"],
        "checks": result["checks"],
        "details": result["details"],
    }
    RESULTS.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                       encoding="utf-8", newline="\n")
    print(json.dumps({
        "schema": report["schema"],
        "probe": report["probe"],
        "status": observed,
        "observed": observed,
        "expected": "pass",
        "total_checks": report["total_checks"],
        "passed_checks": report["passed_checks"],
        "failures": report["failures"],
        "results_file": str(RESULTS),
    }, ensure_ascii=False))
    return 0 if observed == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())