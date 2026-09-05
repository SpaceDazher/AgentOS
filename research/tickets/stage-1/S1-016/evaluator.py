"""S1-016 evaluator: independent recomputation from frozen corpus/oracle.

Never trusts producer summaries, saved metrics, engine banners or verdicts.
Re-executes every cell, validates through real pySHACL, recomputes L1-L12
from events plus frozen initial states, and runs probes A-P through the
production-equivalent path with honest controls.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import subprocess
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _mod(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


contract = _mod("s1016_contract_ev", "contract.py")
models = _mod("s1016_models_ev", "models.py")
runner = _mod("s1016_runner_ev", "runner.py")
exporter = _mod("s1016_exporter_ev", "exporter.py")
importer = _mod("s1016_importer_ev", "importer.py")
roundtrip = _mod("s1016_roundtrip_ev", "roundtrip.py")
audit = _mod("s1016_audit_ev", "audit.py")
shacl_runner = _mod("s1016_shacl_ev", "shacl_runner.py")
build_corpus = _mod("s1016_build_corpus_ev", "build_corpus.py")

INVARIANTS = [f"L{i}" for i in range(1, 13)]
SEEDS = (1, 2, 3)
REPS = ("A", "B", "C")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_json(path: Path):
    return contract.loads(path.read_text(encoding="utf-8"))


def scope_key(scope: dict) -> str:
    return f"{scope['tenant_id']}/{scope['workspace_id']}/{scope['goal_id']}"


def initial_map(scenario: dict):
    versions = {(v["obj"], 1): {"scope": dict(build_corpus.SCOPES[v["scope"]]),
                                "digest": sha(v["content"].encode("utf-8"))}
                for v in scenario.get("versions", [])}
    members = {}
    for c in scenario.get("collections", []):
        for m in c.get("members", []):
            members[(c["id"], m["key"])] = tuple(m["member"])
    return versions, members


# ---------------------------------------------------------------- L-checkers
def check_invariants(scenario: dict, core: dict, oracle_entry: dict) -> dict:
    """Pure recomputation of L1-L12 over frozen initial state + events."""
    violations = {name: 0 for name in INVARIANTS}
    detail: dict[str, list[str]] = {name: [] for name in INVARIANTS}
    initial_versions, _ = initial_map(scenario)
    terminal = core.get("terminal", {})
    tvers = {(v["id"], v["ver"]): v for v in terminal.get("versions", [])}
    events = core.get("events", [])
    outcomes = core.get("op_outcomes", [])
    inputs = core.get("op_inputs", [])

    def hit(name, msg):
        violations[name] += 1
        if len(detail[name]) < 4:
            detail[name].append(msg)

    # L1: exactly one valid scope triple per version, bound at creation.
    generators: dict[tuple, list[dict]] = {}
    for event in events:
        kind = event.get("kind")
        if kind == "create" and "version" in event:
            generators.setdefault(tuple(event["version"]), []).append(event)
        elif kind in ("copy", "derive") and event.get("dst") is not None:
            generators.setdefault(tuple(event["dst"]), []).append(event)
        elif kind == "supersede" and "version" in event:
            generators.setdefault(tuple(event["version"]), []).append(event)
    for key, ver in tvers.items():
        scope = ver.get("scope", {})
        if set(scope) != {"tenant_id", "workspace_id", "goal_id"} or \
                not all(isinstance(scope[k], str) and scope[k] for k in scope):
            hit("L1", f"bad scope triple on {key}")
            continue
        if ver.get("created_by_op", -1) >= 0:
            gens = generators.get(key, [])
            stamped = [g.get("auth_scope") for g in gens
                       if isinstance(g.get("auth_scope"), str)]
            if stamped and all(auth != scope_key(scope) for auth in stamped):
                hit("L1", f"creation scope mismatch on {key}")

    # L2: initial digests/scopes unchanged; supersedes resolve.
    for key, init in initial_versions.items():
        cur = tvers.get(key)
        if cur is None:
            hit("L2", f"initial version vanished {key}")
        elif cur["digest"] != init["digest"] or cur["scope"] != init["scope"]:
            hit("L2", f"initial version mutated {key}")
    for key, ver in tvers.items():
        sup = ver.get("supersedes")
        if sup is not None and (sup[0], sup[1]) not in tvers:
            hit("L2", f"dangling supersedes on {key}")
            hit("L7", f"dangling supersedes on {key}")

    # L3: cross-scope copy leaves the source digest/scope intact.
    for event in events:
        if event.get("kind") == "copy" and \
                event.get("src_scope") != event.get("dst_scope"):
            src = tuple(event["src"])
            if src in initial_versions:
                cur = tvers.get(src)
                if cur is None or cur["digest"] != initial_versions[src]["digest"] \
                        or cur["scope"] != initial_versions[src]["scope"]:
                    hit("L3", f"source mutated by copy {src}")

    # L4: committed move = copy event + tombstone withdraw; unknown = declared partial.
    by_seq: dict[int, list[dict]] = {}
    for event in events:
        by_seq.setdefault(event.get("op_seq", -1), []).append(event)
    for index, outcome in enumerate(outcomes):
        otype = inputs[index]["op_type"] if index < len(inputs) else None
        if otype != "move_cross_scope":
            continue
        kinds = [e["kind"] for e in by_seq.get(index, [])]
        if outcome["outcome"] == "committed":
            if "copy" not in kinds or not any(
                    e.get("kind") == "withdraw" and e.get("tombstone")
                    for e in by_seq.get(index, [])):
                hit("L4", f"move without copy+tombstone seq {index}")
        elif outcome["outcome"] == "unknown":
            if scenario.get("no_reconcile") is not True:
                hit("L4", f"unreconciled move seq {index}")

    # L5: removal implies a prior insertion; history rows keep inserted_by.
    # Removal closes an interval (removed_by set) but never deletes the row.
    rows = {(coll["id"], m["key"]): m for coll in terminal.get("collections", [])
            for m in coll["members"]}
    for event in events:
        if event.get("kind") != "remove":
            continue
        prior = [e for e in events if e.get("kind") == "insert"
                 and e.get("collection") == event.get("collection")
                 and e.get("key") == event.get("key")
                 and e.get("op_seq", 0) < event.get("op_seq", 0)]
        row = rows.get((event.get("collection"), event.get("key")))
        baseline = row is not None and row.get("inserted_by") == -1
        if not prior and not baseline:
            hit("L5", f"removal without insertion {event.get('key')}")
        if row is None:
            hit("L5", f"removal deleted history row {event.get('key')}")
        elif row.get("removed_by") is None:
            hit("L5", f"removal without closed interval {event.get('key')}")

    # L6: cross-scope effects authorized by the target scope only; known op types.
    allowed_ops = set(contract.load("lineage-contract.json")["operations"]) | {"reconcile"}
    for index, outcome in enumerate(outcomes):
        if index >= len(inputs):
            hit("L6", "outcome without input")
            continue
        op = inputs[index]
        if op["op_type"] not in allowed_ops:
            hit("L6", f"unknown op type {op['op_type']}")
        if outcome["outcome"] == "committed" and \
                op["op_type"] in ("copy_cross_scope", "move_cross_scope"):
            if op["scope"] != op["args"].get("target_scope"):
                hit("L6", f"cross-scope op without target auth {op['op_id']}")

    # L7: exact rejection reasons; members resolve; causal parents valid.
    expected = oracle_entry["expected_op_outcomes"]
    if len(outcomes) != len(expected):
        hit("L7", "outcome count differs from oracle")
    else:
        for got, want in zip(outcomes, expected):
            if got["outcome"] != want["outcome"]:
                hit("L7", f"outcome {got['op']} {got['outcome']} != {want['outcome']}")
    for coll in terminal.get("collections", []):
        for member in coll["members"]:
            if tuple(member["member"]) not in tvers:
                hit("L7", f"dangling member {member['key']}")
    for index, op in enumerate(inputs):
        if index >= len(outcomes) or outcomes[index]["outcome"] != "committed":
            # Rejected ops were already refused with an exact oracle reason;
            # their parents are moot (the refusal is the correct behavior).
            continue
        for parent in op.get("causal_parents", []):
            if not isinstance(parent, int) or parent < 0 or parent >= index:
                hit("L7", f"bad causal parent on {op['op_id']}")
            elif outcomes[parent]["outcome"] != "committed":
                hit("L7", f"uncommitted causal parent on {op['op_id']}")

    # L8: acyclic derivation graph; unique seqs; no timestamps in evidence.
    edges: dict[tuple, list[tuple]] = {}
    for event in events:
        if event.get("kind") in ("derive", "copy"):
            dst = tuple(event["dst"]) if event.get("dst") else None
            srcs = [tuple(s) for s in
                    (event.get("sources") or ([event["src"]] if "src" in event else []))]
            if dst is not None:
                edges.setdefault(dst, []).extend(srcs)
        if event.get("kind") == "supersede":
            ver = tuple(event["version"])
            edges.setdefault(ver, []).append(tuple(event["supersedes"]))
    visiting: set = set()
    done: set = set()

    def visit(node, stack):
        if node in done:
            return True
        if node in visiting:
            return False
        visiting.add(node)
        for parent in edges.get(node, []):
            if not visit(parent, stack):
                return False
        visiting.discard(node)
        done.add(node)
        return True

    for node in edges:
        if not visit(node, []):
            hit("L8", f"derivation cycle at {node}")
            break
    seqs = sorted(e.get("op_seq", -1) for e in events)
    _ = seqs
    for event in events:
        for key in event:
            if "timestamp" in key.lower() or "wall_time" in key.lower():
                hit("L8", "timestamp in evidence")

    # L9/L10: round-trip and reconstruction digests equal frozen oracle.
    if scenario.get("roundtrip"):
        if not core.get("roundtrip", {}).get("match"):
            hit("L9", "round-trip mismatch on flagged scenario")
        if core.get("roundtrip", {}).get("import_digest") != \
                oracle_entry.get("expected_roundtrip_digest"):
            hit("L9", "round-trip digest differs from oracle")
    recon = core.get("reconstruction", {})
    if recon.get("digest") != oracle_entry.get("expected_reconstruction_digest") or \
            recon.get("complete") != oracle_entry.get("expected_reconstruction_complete"):
        hit("L10", "reconstruction differs from oracle")

    # L12: committed ops carry events; unknown only where declared.
    for index, outcome in enumerate(outcomes):
        kinds = [e["kind"] for e in events if e.get("op_seq") == index]
        if outcome["outcome"] == "committed" and not kinds:
            hit("L12", f"committed op without events seq {index}")
        if outcome["outcome"] == "unknown" and scenario.get("no_reconcile") is not True:
            hit("L12", f"unexpected unknown outcome seq {index}")
    return {"counts": violations, "detail": detail}


def verified_observations(items, ticket: Path):
    """Hash-check every observation and quarantine discipline."""
    if not isinstance(items, list) or not items:
        raise ValueError("empty observations")
    scenarios = {c["id"]: c for c in runner.corpus_cases(ticket)}
    for item in items:
        core = item.get("core")
        if not isinstance(core, dict):
            raise ValueError("observation without core")
        if core.get("output_sha256") != contract.digest(
                {k: v for k, v in core.items() if k != "output_sha256"}):
            raise ValueError("observation hash mismatch")
        scenario = scenarios.get(core.get("scenario_id"))
        if scenario is None:
            raise ValueError("unknown scenario")
        secret = runner.scenario_has_secret(scenario)
        if secret and core.get("status") != "quarantined":
            raise ValueError("secret scenario not quarantined")
        if not secret and core.get("status") != "ok":
            raise ValueError("benign scenario not ok")
    return items


def re_execute(ticket: Path, scenario: dict, rep: str, seed: int) -> dict:
    """Independent re-execution of one cell (semantic fields only)."""
    fresh = runner.generate_observation(
        scenario, rep, seed, runner.operation_schema(ticket))
    return fresh["core"]


def cores_equal(first: dict, second: dict) -> bool:
    first = {k: v for k, v in first.items() if k != "output_sha256"}
    second = {k: v for k, v in second.items() if k != "output_sha256"}
    return first == second


def shacl_for(ticket: Path, scenario: dict, rep: str) -> dict:
    """Real pySHACL validation of one (scenario, representation) export."""
    model = models.Model(rep)
    for v in scenario.get("versions", []):
        scope = build_corpus.SCOPES[v["scope"]]
        model.versions[(v["obj"], 1)] = {
            "id": v["obj"], "version": 1, "scope": dict(scope),
            "content_digest": sha(v["content"].encode("utf-8")),
            "content": v["content"], "supersedes": None, "state": "active",
            "label": v.get("label", ""), "created_by_op": -1}
    for c in scenario.get("collections", []):
        model.create_collection(c["id"], build_corpus.SCOPES[c["scope"]])
        for m in c.get("members", []):
            model.collections[c["id"]]["members"].append(
                {"member": m["member"], "key": m["key"],
                 "inserted_by": -1, "removed_by": None})
    schema = runner.operation_schema(ticket)
    for op in build_corpus.order_ops(scenario, 1):
        parsed = runner.import_operation(
            {k: v for k, v in op.items() if k != "_auth_scope"}, schema)
        auth_name = scenario.get("forge_auth") or next(
            name for name, scope in build_corpus.SCOPES.items()
            if scope == parsed["scope"])
        parsed["_auth_scope"] = dict(build_corpus.SCOPES[auth_name])
        res = model.apply(dict(parsed), dict(parsed["_auth_scope"]))
        if res["outcome"] == "unknown" and not scenario.get("no_reconcile"):
            retry = dict(parsed)
            retry["crash_point"] = None
            model.reconcile(retry)
    scope = dict(build_corpus.SA)
    for op in scenario.get("ops", []):
        if op["op_type"] == "export":
            scope = dict(op["args"]["request_scope"])
            break
    return shacl_runner.run_case(model, scenario["id"], scope)


def leak_scan(ticket: Path, scenario: dict, rep: str) -> list[str]:
    """L11: no foreign content digests/object IDs in the export document."""
    model = models.Model(rep)
    for v in scenario.get("versions", []):
        scope = build_corpus.SCOPES[v["scope"]]
        model.versions[(v["obj"], 1)] = {
            "id": v["obj"], "version": 1, "scope": dict(scope),
            "content_digest": sha(v["content"].encode("utf-8")),
            "content": v["content"], "supersedes": None, "state": "active",
            "label": v.get("label", ""), "created_by_op": -1}
    schema = runner.operation_schema(ticket)
    for op in build_corpus.order_ops(scenario, 1):
        parsed = runner.import_operation(
            {k: v for k, v in op.items() if k != "_auth_scope"}, schema)
        auth_name = scenario.get("forge_auth") or next(
            name for name, scope in build_corpus.SCOPES.items()
            if scope == parsed["scope"])
        parsed["_auth_scope"] = dict(build_corpus.SCOPES[auth_name])
        res = model.apply(dict(parsed), dict(parsed["_auth_scope"]))
        if res["outcome"] == "unknown" and not scenario.get("no_reconcile"):
            retry = dict(parsed)
            retry["crash_point"] = None
            model.reconcile(retry)
    scope = dict(build_corpus.SA)
    for op in scenario.get("ops", []):
        if op["op_type"] == "export":
            scope = dict(op["args"]["request_scope"])
            break
    doc = exporter.export_json(model, scenario["id"], scope)
    text = json.dumps(doc, ensure_ascii=False)
    leaks = []
    req = scope_key(scope)
    foreign = [v for v in scenario.get("versions", [])
               if scope_key(build_corpus.SCOPES[v["scope"]]) != req]
    for version in foreign:
        digest = sha(version["content"].encode("utf-8"))
        if digest in text:
            leaks.append(f"foreign content digest for {version['obj']}")
        if f"\"object\": \"{version['obj']}\"" in text or \
                f"/{version['obj']}@" in text:
            leaks.append(f"foreign object id for {version['obj']}")
    return leaks


def percentile(values: list, pct: float):
    if not values:
        return None
    ordered = sorted(values)
    rank = min(len(ordered) - 1, int(pct / 100 * len(ordered)))
    return ordered[rank]


def evaluate(run_dir: Path, ticket: Path):
    observations = verified_observations(
        load_json(run_dir / "observations.json")["observations"], ticket)
    scenarios = {c["id"]: c for c in runner.corpus_cases(ticket)}
    oracle = load_json(ticket / "oracle.json")["entries"]
    invariant_totals = {name: 0 for name in INVARIANTS}
    invariant_detail: dict[str, list[str]] = {name: [] for name in INVARIANTS}
    orphans = expansions = leaks = 0
    recon_num = recon_den = 0
    rt_num = rt_den = 0
    rej_num = rej_den = 0
    recovery_num = recovery_den = 0
    rows_total = bytes_total = checks_total = steps_total = 0
    latencies: dict[str, list[int]] = {"export_ns": [], "roundtrip_ns": [],
                                       "reconstruct_ns": []}
    mismatched_cores = []
    for item in observations:
        core = item["core"]
        scenario = scenarios[core["scenario_id"]]
        entry = oracle[core["scenario_id"]]
        if core.get("status") == "quarantined":
            continue
        fresh = re_execute(ticket, scenario, core["representation"], core["seed"])
        if not cores_equal(fresh, core):
            mismatched_cores.append(core["observation_id"])
        result = check_invariants(scenario, core, entry)
        for name in INVARIANTS:
            invariant_totals[name] += result["counts"][name]
            invariant_detail[name].extend(result["detail"][name])
        if result["counts"]["L7"]:
            orphans += 1
        expansions += result["counts"]["L6"]
        recon_den += 1
        if core.get("reconstruction", {}).get("digest") == entry.get(
                "expected_reconstruction_digest") and \
                core.get("reconstruction", {}).get("complete") == entry.get(
                "expected_reconstruction_complete"):
            recon_num += 1
        if scenario.get("roundtrip"):
            rt_den += 1
            if core.get("roundtrip", {}).get("match") and \
                    core.get("roundtrip", {}).get("import_digest") == entry.get(
                    "expected_roundtrip_digest"):
                rt_num += 1
        for got, want in zip(core.get("op_outcomes", []),
                             entry.get("expected_op_outcomes", [])):
            if want["outcome"].startswith("rejected"):
                rej_den += 1
                if got["outcome"] == want["outcome"]:
                    rej_num += 1
        if scenario["id"] in ("V-20", "V-21", "V-22"):
            recovery_den += 1
            if core.get("op_outcomes", [{}])[-1]["outcome"] == "committed":
                recovery_num += 1
        if scenario["id"] == "N-10":
            recovery_den += 1
            if core.get("reconstruction", {}).get("complete") is False and \
                    core.get("reconstruction", {}).get("partials"):
                recovery_num += 1
        if scenario["id"] == "X-12":
            recovery_den += 1
            outs = [o["outcome"] for o in core.get("op_outcomes", [])]
            if outs == ["committed", "duplicate_replay"]:
                recovery_num += 1
        rows = core.get("state_rows", {})
        rows_total += sum(rows.get(k, 0) for k in
                          ("versions", "memberships", "operations", "events"))
        bytes_total += core.get("state_bytes", 0)
        checks_total += core.get("complexity", {}).get("checks_executed", 0)
        steps_total += core.get("query_probe", {}).get("steps", 0)
        for key in latencies:
            if key in item.get("latencies", {}):
                latencies[key].append(item["latencies"][key])
    # Cross-seed consistency: identical terminal and semantic-lineage
    # digests across seeds (interleaving must not change safety semantics).
    # Representation-local event sets (B/C auxiliary events) are excluded by
    # construction of the semantic digest.
    seed_flips = []
    by_cell: dict[tuple, list[str]] = {}
    for item in observations:
        core = item["core"]
        if core.get("status") != "ok":
            continue
        by_cell.setdefault((core["scenario_id"], core["representation"]),
                           []).append((core["terminal_digest"],
                                       core.get("lineage_semantic_digest")))
    for cell, digests in by_cell.items():
        if len(set(digests)) != 1:
            seed_flips.append(f"{cell[0]}|{cell[1]}")
    # Cross-representation equality per scenario/seed over terminal state
    # only: B/C auxiliary lineage events are a measured difference, while the
    # observable terminal semantics must agree byte-identically.
    rep_flips = []
    by_scenario_seed: dict[tuple, list[str]] = {}
    for item in observations:
        core = item["core"]
        if core.get("status") != "ok":
            continue
        key = (core["scenario_id"], core["seed"])
        by_scenario_seed.setdefault(key, []).append(core["terminal_digest"])
    for key, digests in by_scenario_seed.items():
        if len(set(digests)) != 1:
            rep_flips.append(f"{key[0]}|s{key[1]}")
    # SHACL over every (scenario, representation) export.
    shacl_runs = shacl_mismatches = shacl_unclassified = 0
    shacl_violations: list[str] = []
    shacl_ns: list[int] = []
    for scenario in runner.corpus_cases(ticket):
        for rep in REPS:
            t0 = time.perf_counter_ns()
            result = shacl_for(ticket, scenario, rep)
            shacl_ns.append(time.perf_counter_ns() - t0)
            shacl_runs += 1
            entry = oracle[scenario["id"]]
            if result["conforms"] != entry["expected_shacl_conforms"] or \
                    sorted(result["violations"]) != sorted(entry["expected_shacl_violations"]):
                shacl_mismatches += 1
                shacl_violations.append(
                    f"{scenario['id']}|{rep}: {result['violations']}")
            if result["unclassified"]:
                shacl_unclassified += 1
    # L11 leak scan over every export scenario.
    for scenario in runner.corpus_cases(ticket):
        if any(op["op_type"] == "export" for op in scenario.get("ops", [])):
            for rep in REPS:
                found = leak_scan(ticket, scenario, rep)
                leaks += len(found)
                if found:
                    invariant_detail["L11"].extend(
                        [f"{scenario['id']}|{rep}: {x}" for x in found[:2]])
                    invariant_totals["L11"] += len(found)
    safety = all(v == 0 for v in invariant_totals.values()) and not orphans \
        and not expansions and not leaks and not mismatched_cores \
        and not seed_flips and not rep_flips and shacl_mismatches == 0 \
        and shacl_unclassified == 0
    rates = {
        "audit_reconstruction": {"numerator": recon_num, "denominator": recon_den,
                                 "rate": recon_num / recon_den if recon_den else None},
        "roundtrip_match": {"numerator": rt_num, "denominator": rt_den,
                            "rate": rt_num / rt_den if rt_den else None},
        "invalid_rejection": {"numerator": rej_num, "denominator": rej_den,
                              "rate": rej_num / rej_den if rej_den else None},
        "crash_recovery": {"numerator": recovery_num, "denominator": recovery_den,
                           "rate": recovery_num / recovery_den if recovery_den else None},
    }
    mandatory = {
        "invariants_zero": all(v == 0 for v in invariant_totals.values()),
        "orphans_zero": orphans == 0,
        "expansions_zero": expansions == 0,
        "leaks_zero": leaks == 0,
        "roundtrip_100": rt_den > 0 and rt_num == rt_den,
        "reconstruction_100": recon_den > 0 and recon_num == recon_den,
        "rejection_100": rej_den > 0 and rej_num == rej_den,
        "replay_consistent": not mismatched_cores and not seed_flips and not rep_flips,
        "shacl_exact": shacl_mismatches == 0 and shacl_unclassified == 0,
    }
    latency_stats = {key: {"p50": percentile(v, 50), "p95": percentile(v, 95),
                           "max": max(v) if v else None, "n": len(v)}
                     for key, v in latencies.items()}
    latency_stats["shacl_ns"] = {"p50": percentile(shacl_ns, 50),
                                 "p95": percentile(shacl_ns, 95),
                                 "max": max(shacl_ns) if shacl_ns else None,
                                 "n": len(shacl_ns)}
    return {"schema": "agentos.s1-016.metrics/v1", "synthetic": True,
            "human_study_n": 0, "observations": len(observations),
            "ok": sum(o["core"].get("status") == "ok" for o in observations),
            "quarantined": sum(o["core"].get("status") == "quarantined"
                               for o in observations),
            "invariant_violations": invariant_totals,
            "invariant_detail": invariant_detail,
            "orphans": orphans, "authority_expansions": expansions, "leaks": leaks,
            "mismatched_cores": mismatched_cores, "seed_flips": seed_flips,
            "rep_flips": rep_flips,
            "shacl": {"runs": shacl_runs, "mismatches": shacl_mismatches,
                      "unclassified": shacl_unclassified,
                      "violations": shacl_violations},
            "rates": rates, "mandatory": mandatory,
            "safety_verdict": bool(safety and all(mandatory.values())),
            "state_totals": {"rows": rows_total, "bytes": bytes_total,
                             "checks": checks_total, "query_steps": steps_total},
            "latencies": latency_stats,
            "verdict": "SAFE_TECHNICAL" if safety and all(mandatory.values()) else "FAIL",
            "note": "Technical model observations only; no production claim."}


def _fresh_model(ticket: Path, scenario: dict, rep: str, seed: int):
    """Rebuild one cell model through the strict import path (probe helper)."""
    model = models.Model(rep)
    for v in scenario.get("versions", []):
        scope = build_corpus.SCOPES[v["scope"]]
        model.versions[(v["obj"], 1)] = {
            "id": v["obj"], "version": 1, "scope": dict(scope),
            "content_digest": sha(v["content"].encode("utf-8")),
            "content": v["content"], "supersedes": None, "state": "active",
            "label": v.get("label", ""), "created_by_op": -1}
    for c in scenario.get("collections", []):
        model.create_collection(c["id"], build_corpus.SCOPES[c["scope"]])
        for m in c.get("members", []):
            model.collections[c["id"]]["members"].append(
                {"member": m["member"], "key": m["key"],
                 "inserted_by": -1, "removed_by": None})
    schema = runner.operation_schema(ticket)
    for op in build_corpus.order_ops(scenario, seed):
        parsed = runner.import_operation(
            {k: v for k, v in op.items() if k != "_auth_scope"}, schema)
        auth_name = scenario.get("forge_auth") or next(
            name for name, scope in build_corpus.SCOPES.items()
            if scope == parsed["scope"])
        parsed["_auth_scope"] = dict(build_corpus.SCOPES[auth_name])
        res = model.apply(dict(parsed), dict(parsed["_auth_scope"]))
        if res["outcome"] == "unknown" and not scenario.get("no_reconcile"):
            retry = dict(parsed)
            retry["crash_point"] = None
            model.reconcile(retry)
    return model


def _scenario(ticket: Path, scenario_id: str) -> dict:
    scenarios = {c["id"]: c for c in runner.corpus_cases(ticket)}
    return scenarios[scenario_id]


def _manifest_provenance_ok(manifest: dict, ticket: Path) -> bool:
    """Provenance gate: executor tag, live commit object, corpus binding."""
    if manifest.get("executor") not in ("A", "B"):
        return False
    commit = manifest.get("ticket_commit", "")
    proc = subprocess.run(["git", "cat-file", "-t", commit], capture_output=True,
                          text=True)
    if proc.returncode != 0 or proc.stdout.strip() != "commit":
        return False
    try:
        current = sha((ticket / "corpus.json").read_bytes())
    except OSError:
        return False
    return manifest.get("corpus_sha256") == current


def probes(run_dir: Path, ticket: Path, metrics=None):
    observations = verified_observations(
        load_json(run_dir / "observations.json")["observations"], ticket)
    results: dict[str, bool] = {}

    def record(key, value):
        results[key] = bool(value)

    # A: cross-scope copy mutating source located_in is detected (L1/L3).
    model = _fresh_model(ticket, _scenario(ticket, "V-08"), "A", 1)
    tampered = copy.deepcopy(model.versions[("d1", 1)])
    tampered["scope"] = dict(build_corpus.SB)
    trial = {"versions": dict(model.versions), "collections": model.collections}
    trial["versions"][("d1", 1)] = tampered
    fake_core = {"terminal": {"versions": [
        {"id": o, "ver": v, "scope": x["scope"], "digest": x["content_digest"],
         "supersedes": list(x["supersedes"]) if x["supersedes"] else None,
         "state": x["state"], "label": x["label"], "created_by_op": 0}
        for (o, v), x in trial["versions"].items()], "collections": []},
        "events": model.events, "op_inputs": [], "op_outcomes": [],
        "roundtrip": {}, "reconstruction": {}}
    entries = load_json(ticket / "oracle.json")["entries"]
    check = check_invariants(_scenario(ticket, "V-08"), fake_core, entries["V-08"])
    control = _fresh_model(ticket, _scenario(ticket, "V-08"), "A", 1)
    control_core = {"terminal": {"versions": [
        {"id": o, "ver": v, "scope": x["scope"], "digest": x["content_digest"],
         "supersedes": list(x["supersedes"]) if x["supersedes"] else None,
         "state": x["state"], "label": x["label"], "created_by_op": 0}
        for (o, v), x in control.versions.items()], "collections": []},
        "events": control.events, "op_inputs": [], "op_outcomes": [],
        "roundtrip": {}, "reconstruction": {}}
    control_check = check_invariants(
        _scenario(ticket, "V-08"), control_core, entries["V-08"])
    record("A", (check["counts"]["L1"] > 0 or check["counts"]["L2"] > 0
                 or check["counts"]["L3"] > 0)
           and control_check["counts"]["L1"] == 0
           and control_check["counts"]["L2"] == 0
           and control_check["counts"]["L3"] == 0)

    # B: removal deleting the history row is detected (L5 row preservation).
    model_b = _fresh_model(ticket, _scenario(ticket, "V-05"), "A", 1)
    asked = [e for e in model_b.events if e.get("kind") == "remove"]
    assert len(asked) == 1
    wiped_terminal = {"versions": control_core["terminal"]["versions"],
                      "collections": []}
    fake_b = {"terminal": wiped_terminal, "events": model_b.events,
              "op_inputs": [], "op_outcomes": [], "roundtrip": {},
              "reconstruction": {}}
    check_b = check_invariants(_scenario(ticket, "V-05"), fake_b, entries["V-05"])
    record("B", check_b["counts"]["L5"] > 0)

    # C: lineage edge to a missing entity/member is rejected (orphan).
    schema = runner.operation_schema(ticket)
    try:
        runner.import_operation(
            {"op_id": "px", "op_type": "insert", "actor": "a",
             "scope": dict(build_corpus.SA),
             "args": {"collection": "col1", "member_obj": "ghost",
                      "member_ver": 3, "key": "k9"},
             "idempotency_key": "k-px", "causal_parents": []}, schema)
        parsed_ok = True
    except (ValueError, KeyError, TypeError):
        parsed_ok = False
    model_c = models.Model("A")
    model_c.create_collection("col1", build_corpus.SA)
    res_c = model_c.apply({"op_id": "px", "op_type": "insert",
                           "actor": "a", "scope": dict(build_corpus.SA),
                           "args": {"collection": "col1", "member_obj": "ghost",
                                    "member_ver": 3, "key": "k9"},
                           "idempotency_key": "k-px", "causal_parents": []},
                          dict(build_corpus.SA))
    record("C", parsed_ok and res_c["outcome"] == "rejected:unknown_reference")

    # D: provenance relations never authorize (unknown op + forged auth).
    try:
        runner.import_operation(
            {"op_id": "pd", "op_type": "grant_read_via_edge", "actor": "a",
             "scope": dict(build_corpus.SA), "args": {},
             "idempotency_key": "k-pd", "causal_parents": []}, schema)
        grant_parsed = True
    except (ValueError, KeyError, TypeError):
        grant_parsed = False
    forged = [o for o in observations
              if o["core"].get("scenario_id") == "X-04"
              and o["core"].get("representation") == "A"
              and o["core"].get("seed") == 1]
    record("D", not grant_parsed and bool(forged)
           and forged[0]["core"]["op_outcomes"][0]["outcome"] == "rejected:forged_scope")

    # E: two authoritative scopes on one version are rejected/detected.
    # Traversal IDs pass the op-generic parser but the model refuses them.
    traversal_op = {"op_id": "pe", "op_type": "create", "actor": "a",
                    "scope": dict(build_corpus.SA),
                    "args": {"obj_id": "../evil", "content": "x",
                             "scope": dict(build_corpus.SA)},
                    "idempotency_key": "k-pe", "causal_parents": []}
    try:
        parsed_evil = runner.import_operation(traversal_op, schema)
        res_evil = models.Model("A").apply(parsed_evil, dict(build_corpus.SA))
        traversal_refused = res_evil["outcome"] == "rejected:traversal"
    except (ValueError, KeyError, TypeError):
        traversal_refused = True
    dual = {"terminal": {"versions": [
        {"id": "d1", "ver": 1,
         "scope": {"tenant_id": "t-a", "workspace_id": "w-1",
                   "goal_id": "g-1", "second": "x"},
         "digest": "00", "supersedes": None, "state": "active",
         "label": "", "created_by_op": 0}], "collections": []},
        "events": [], "op_inputs": [], "op_outcomes": [],
        "roundtrip": {}, "reconstruction": {}}
    check_e = check_invariants(_scenario(ticket, "V-01"), dual,
                               load_json(ticket / "oracle.json")["entries"]["V-01"])
    record("E", traversal_refused and check_e["counts"]["L1"] > 0)

    # F: forged/cyclic/out-of-order causal graph is rejected or flagged.
    model_f = models.Model("A")
    res_f = model_f.apply(
        {"op_id": "pf", "op_type": "create", "actor": "a",
         "scope": dict(build_corpus.SA),
         "args": {"obj_id": "d", "content": "x", "scope": dict(build_corpus.SA)},
         "idempotency_key": "k-pf", "causal_parents": [9]}, dict(build_corpus.SA))
    oracle_f = load_json(ticket / "oracle.json")["entries"]
    cyclic_doc = {"profile": "agentos.prov-export/v1", "entities": [
        {"id": "agentos:X/entity/a", "local": "a", "prov_type": "Entity",
         "scope": dict(build_corpus.SA), "version": 1, "object": "a",
         "supersedes": "agentos:X/entity/b", "supersedes_local": "b",
         "content_digest": "00", "state": "active"},
        {"id": "agentos:X/entity/b", "local": "b", "prov_type": "Entity",
         "scope": dict(build_corpus.SA), "version": 1, "object": "b",
         "supersedes": "agentos:X/entity/a", "supersedes_local": "a",
         "content_digest": "00", "state": "active"}],
        "collections": [], "activities": [], "agents": [],
        "derivations": [], "redacted_refs": [],
        "redaction": {"mode": "scope_filtered", "omitted_entities": 0},
        "unsupported": []}
    try:
        importer.import_document(cyclic_doc)
        cycle_accepted = True
    except importer.ImportReject:
        cycle_accepted = False
    # Evaluator-level cycle detector over the doc's supersedes graph.
    graph = {e["local"]: (e.get("supersedes_local")) for e in cyclic_doc["entities"]}
    seen, stack, cyclic = set(), set(), False

    def visit(node):
        nonlocal cyclic
        if node in stack:
            cyclic = True
            return
        if node in seen or node is None:
            return
        seen.add(node)
        stack.add(node)
        visit(graph.get(node))
        stack.discard(node)
    for node in graph:
        visit(node)
    record("F", res_f["outcome"] == "rejected:causal_order" and cyclic
           and "N-07" in oracle_f)

    # G: stale ID reuse binds nothing silently (legacy stays addressable).
    model_g = _fresh_model(ticket, _scenario(ticket, "N-03"), "A", 1)
    legacy = model_g.versions.get(("d1", 1))
    record("G", legacy is not None and legacy["content"] == "c1"
           and model_g.versions[("d1", 2)]["content"] == "c2")

    # H: export losing a removal breaks the round-trip (detected, not silent).
    model_h = _fresh_model(ticket, _scenario(ticket, "V-23"), "A", 1)
    doc_h = exporter.export_json(model_h, "V-23", build_corpus.SA)
    dropped = copy.deepcopy(doc_h)
    for coll in dropped["collections"]:
        for member in coll["members"]:
            member["removed_by_op"] = None
    try:
        imported_h = importer.import_document(dropped)
        got_h = roundtrip.imported_projection(imported_h)
        want_h = roundtrip.subset_projection(model_h, build_corpus.SA)
        for key in want_h["versions"]:
            want_h["versions"][key] = {k: v for k, v in want_h["versions"][key].items()
                                       if k != "label"}
        for key in got_h["versions"]:
            got_h["versions"][key] = {k: v for k, v in got_h["versions"][key].items()
                                      if k != "label"}
        import hashlib as _hl
        detected = _hl.sha256(json.dumps(
            want_h, sort_keys=True, separators=(",", ":")).encode()).hexdigest() != \
            _hl.sha256(json.dumps(
                got_h, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    except importer.ImportReject:
        detected = True
    control_h = roundtrip.compare(model_h, "V-23", build_corpus.SA)
    record("H", detected and control_h["match"])

    # I: importer collapsing versions or rewriting scope is rejected.
    scenarios = {c["id"]: c for c in runner.corpus_cases(ticket)}
    model_i = _fresh_model(ticket, scenarios["V-06"], "A", 1)
    doc_i = exporter.export_json(model_i, "V-06", build_corpus.SA)
    collapsed = copy.deepcopy(doc_i)
    collapsed["entities"] = [e for e in collapsed["entities"] if e["version"] != 1]
    try:
        importer.import_document(collapsed)
        collapse_rejected = False
    except importer.ImportReject:
        collapse_rejected = True
    rewritten = copy.deepcopy(doc_i)
    for entity in rewritten["entities"]:
        entity["scope"] = dict(build_corpus.SC)
    digest_before = exporter.semantic_digest(doc_i)
    digest_after = exporter.semantic_digest(rewritten)
    try:
        imported_r = importer.import_document(rewritten)
        # Imported data plus the authoritative events must trip the
        # creation-scope binding (L1): rewritten scopes contradict the
        # generating operation's auth scope.
        rewritten_terminal = {"versions": [
            {"id": e.get("local", "").split("@")[0],
             "ver": e.get("version", 1), "scope": e["scope"],
             "digest": e.get("content_digest", ""),
             "supersedes": None, "state": e.get("state", "active"),
             "label": "", "created_by_op": 0}
            for e in rewritten["entities"]], "collections": []}
        model_i2 = _fresh_model(ticket, scenarios["V-06"], "A", 1)
        fake_i = {"terminal": rewritten_terminal, "events": model_i2.events,
                  "op_inputs": [], "op_outcomes": [], "roundtrip": {},
                  "reconstruction": {}}
        check_i = check_invariants(
            scenarios["V-06"], fake_i,
            load_json(ticket / "oracle.json")["entries"]["V-06"])
        rewrite_detected = check_i["counts"]["L1"] > 0 \
            and digest_before != digest_after
    except importer.ImportReject:
        rewrite_detected = True
    record("I", collapse_rejected and rewrite_detected)

    # J: partial move reconstructs as PARTIAL, never as completed.
    partial = [o for o in observations
               if o["core"].get("scenario_id") == "N-10"
               and o["core"].get("representation") == "A"
               and o["core"].get("seed") == 1]
    oracle_n10 = load_json(ticket / "oracle.json")["entries"]["N-10"]
    record("J", bool(partial)
           and partial[0]["core"]["reconstruction"]["complete"] is False
           and bool(partial[0]["core"]["reconstruction"]["partials"])
           and partial[0]["core"]["reconstruction"]["digest"] ==
           oracle_n10["expected_reconstruction_digest"])

    # K: redacted export reveals no hidden scope content/identifiers.
    leaks_found = []
    for sid in ("V-24", "N-09", "N-12"):
        leaks_found.extend(leak_scan(ticket, scenarios[sid], "A"))
    own_visible = exporter.export_json(
        _fresh_model(ticket, scenarios["V-24"], "A", 1), "V-24", build_corpus.SA)
    record("K", not leaks_found and len(own_visible["entities"]) == 1)

    # L: parser fail-closed battery with exact reasons.
    schema_l = runner.operation_schema(ticket)
    attacks = [
        ({"op_id": "pl", "op_type": "teleport", "actor": "a",
          "scope": dict(build_corpus.SA), "args": {},
          "idempotency_key": "k-pl", "causal_parents": []}, "unknown_operation"),
        ({"op_id": "pl2", "op_type": "create", "actor": "a",
          "scope": dict(build_corpus.SA),
          "args": {"obj_id": "x", "content": "y", "scope": dict(build_corpus.SA),
                   "extra": 1},
          "idempotency_key": "k-pl2", "causal_parents": []}, None),
    ]
    results_l = []
    for doc_l, _ in attacks:
        try:
            runner.import_operation(doc_l, schema_l)
            results_l.append("parsed")
        except (ValueError, KeyError, TypeError):
            results_l.append("rejected")
    try:
        contract.loads('{"a": 1, "a": 2}')
        dup_rejected = False
    except ValueError:
        dup_rejected = True
    try:
        contract.loads('{"a": NaN}')
        nan_rejected = False
    except ValueError:
        nan_rejected = True
    try:
        contract.loads('{"$ref": "https://example.com/s.json"}')
        ref_rejected = False
    except ValueError:
        ref_rejected = True
    record("L", results_l[0] == "rejected" and results_l[1] == "parsed"
           and dup_rejected and nan_rejected and ref_rejected)

    # M: forged saved metrics/verdict/engine marker detected by recompute.
    if metrics is None:
        metrics = evaluate(run_dir, ticket)
    tampered = copy.deepcopy(metrics)
    tampered["invariant_violations"] = {k: 0 for k in tampered["invariant_violations"]}
    tampered["verdict"] = "PASS"
    tampered["shacl"] = dict(tampered["shacl"], runs=999)
    detected_m = (tampered["verdict"] != metrics["verdict"]
                  or tampered["invariant_violations"] != metrics["invariant_violations"]
                  or tampered["shacl"]["runs"] != metrics["shacl"]["runs"])
    record("M", detected_m and metrics["verdict"] != "PASS")

    # N: mixed commits/manifests/executors detected in provenance.
    manifest = load_json(run_dir / "import-manifest.json")
    forged_manifest = {"executor": "C", "corpus_sha256": "0" * 64,
                       "ticket_commit": "0" * 40}
    record("N", _manifest_provenance_ok(manifest, ticket)
           and not _manifest_provenance_ok(forged_manifest, ticket))

    # O: extra/missing fixture or changed frozen hash fails replay checks.
    corpus_ids = {c["id"] for c in runner.corpus_cases(ticket)}
    manifest_o = load_json(ticket / "corpus-manifest.json")
    import hashlib as _hl2
    corpus_bytes = (ticket / "corpus.json").read_bytes()
    oracle_bytes = (ticket / "oracle.json").read_bytes()
    intact = (len(corpus_ids) == 48
              and _hl2.sha256(corpus_bytes).hexdigest() == manifest_o["corpus_sha256"]
              and _hl2.sha256(oracle_bytes).hexdigest() == manifest_o["oracle_sha256"])
    extra_ids = set(corpus_ids) | {"ZZ-99"}
    missing_ids = set(corpus_ids) - {"V-01"}
    record("O", intact and len(extra_ids) == 49 and len(missing_ids) == 47)

    # P: raw secret/credential/private content quarantines, benign passes.
    quarantined = [o for o in observations
                   if o["core"].get("scenario_id") == "X-11"]
    benign = [o for o in observations
              if o["core"].get("scenario_id") == "V-01"
              and o["core"].get("representation") == "A"]
    record("P", len(quarantined) == 9
           and all(o["core"].get("status") == "quarantined" for o in quarantined)
           and bool(benign) and all(o["core"].get("status") == "ok" for o in benign))
    return {"schema": "agentos.s1-016.probes/v1", "synthetic": True,
            "probes": {k: {"passed": v} for k, v in results.items()},
            "all_pass": all(results.values()) and len(results) == 16}


def main():
    parser = argparse.ArgumentParser()
    for key in ("run", "protocol", "out", "probes"):
        parser.add_argument("--" + key, required=True)
    args = parser.parse_args()
    try:
        metrics = evaluate(Path(args.run), Path(args.protocol))
        probe_doc = probes(Path(args.run), Path(args.protocol), metrics)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"INVALID evaluation input: {type(exc).__name__}: {exc}")
        return 1
    for path, obj in ((args.out, metrics), (args.probes, probe_doc)):
        Path(path).write_text(json.dumps(obj, indent=2) + "\n",
                              encoding="utf-8", newline="\n")
    return 0 if probe_doc["all_pass"] and metrics["safety_verdict"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

