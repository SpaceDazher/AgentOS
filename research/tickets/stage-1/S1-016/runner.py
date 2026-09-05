"""S1-016 matrix runner: deterministic 864-observation generation (stdlib only).

For each scenario x representation x seed: strict-parse every operation
through the production-equivalent path, simulate (with crash/reconcile
semantics), export, round-trip and audit-reconstruct while measuring
wall-clock technical latencies. SHACL is the evaluator's independent job.

Observation hashed core is executor-independent; wall-clock latencies ride
alongside as producer-measured same-host evidence (never safety proof).
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _mod(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


contract = _mod("s1016_contract_run", "contract.py")
models = _mod("s1016_models_run", "models.py")
build_corpus = _mod("s1016_build_corpus_run", "build_corpus.py")
exporter = _mod("s1016_exporter_run", "exporter.py")
importer = _mod("s1016_importer_run", "importer.py")
roundtrip = _mod("s1016_roundtrip_run", "roundtrip.py")
audit = _mod("s1016_audit_run", "audit.py")

SEEDS = (1, 2, 3)
REPS = ("A", "B", "C")
SCOPES = build_corpus.SCOPES


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_json(path: Path):
    return contract.loads(path.read_text(encoding="utf-8"))


def corpus_cases(ticket: Path):
    doc = load_json(ticket / "corpus.json")
    if doc.get("schema") != "agentos.s1-016.corpus/v1":
        raise ValueError("corpus schema mismatch")
    cases = []
    for case in doc["cases"]:
        # Flags live in a nested dict in the frozen file; merge them to the
        # top level so every consumer sees one binding (forge_auth and
        # no_reconcile must never silently default).
        merged = dict(case)
        merged.update(case.get("flags", {}))
        cases.append(merged)
    return cases


def operation_schema(ticket: Path):
    return load_json(ticket / "schemas" / "operation.schema.json")


def import_operation(raw: dict, schema: dict) -> dict:
    """Production-equivalent strict parse of one operation input."""
    text = json.dumps(raw, ensure_ascii=False)
    doc = contract.loads(text)
    contract.validate(doc, schema)
    for key in ("op_id", "actor", "idempotency_key"):
        if contract.has_traversal(doc.get(key)):
            raise ValueError(f"traversal in {key}")
    if doc["op_type"] not in contract.load("lineage-contract.json")["operations"] + ["reconcile"]:
        raise ValueError("unknown_operation")
    return doc


def scenario_has_secret(scenario: dict) -> bool:
    blob = {"v": scenario.get("versions", []), "o": scenario.get("ops", [])}
    return contract.has_private(blob)


def default_scope(scenario: dict) -> dict:
    for op in scenario.get("ops", []):
        if op["op_type"] == "export":
            return dict(op["args"]["request_scope"])
    return dict(build_corpus.SA)


def baseline_of(scenario: dict) -> dict:
    return {"versions": {
        (v["obj"], 1): sha(v["content"].encode("utf-8"))
        for v in scenario.get("versions", [])}, "members": {}}


def generate_observation(scenario: dict, rep: str, seed: int, schema: dict) -> dict:
    """Simulate one cell; return the observation (core + latencies)."""
    if scenario_has_secret(scenario):
        core = {"scenario_id": scenario["id"], "representation": rep,
                "seed": seed,
                "observation_id": f"{scenario['id']}|{rep}|s{seed}",
                "status": "quarantined", "reason": "secret_or_private_content"}
        core["output_sha256"] = contract.digest(core)
        return {"core": core, "latencies": {}}
    model = models.Model(rep)
    for v in scenario.get("versions", []):
        scope = SCOPES[v["scope"]]
        model.versions[(v["obj"], 1)] = {
            "id": v["obj"], "version": 1, "scope": dict(scope),
            "content_digest": sha(v["content"].encode("utf-8")),
            "content": v["content"], "supersedes": None, "state": "active",
            "label": v.get("label", ""), "created_by_op": -1}
    for c in scenario.get("collections", []):
        model.create_collection(c["id"], SCOPES[c["scope"]])
        for m in c.get("members", []):
            model.collections[c["id"]]["members"].append(
                {"member": m["member"], "key": m["key"],
                 "inserted_by": -1, "removed_by": None})
    op_inputs = []
    for op in build_corpus.order_ops(scenario, seed):
        parsed = import_operation({k: v for k, v in op.items() if k != "_auth_scope"},
                                  schema)
        auth_name = scenario.get("forge_auth") or next(
            name for name, scope in SCOPES.items() if scope == parsed["scope"])
        parsed["_auth_scope"] = dict(SCOPES[auth_name])
        op_inputs.append(parsed)
    outcomes = []
    for op in op_inputs:
        res = model.apply(dict(op), dict(op["_auth_scope"]))
        if res["outcome"] == "unknown" and not scenario.get("no_reconcile"):
            retry = dict(op)
            retry["crash_point"] = None
            res = model.reconcile(retry)
            outcomes.append({"op": op["op_id"], "outcome": res["outcome"],
                             "reason": res.get("reason"), "reconciled": True})
        else:
            outcomes.append({"op": op["op_id"], "outcome": res["outcome"],
                             "reason": res.get("reason"), "reconciled": False})
    scope = default_scope(scenario)
    t0 = time.perf_counter_ns()
    doc = exporter.export_json(model, scenario["id"], scope)
    export_digest = exporter.semantic_digest(doc)
    t1 = time.perf_counter_ns()
    rt = roundtrip.compare(model, scenario["id"], scope)
    t2 = time.perf_counter_ns()
    reconstruction = audit.reconstruct(model, baseline_of(scenario))
    t3 = time.perf_counter_ns()
    # Query probe: identical member lookups (+ one miss) on every model;
    # C additionally rebuilds its droppable graph cache around the queries.
    queries = 0
    for cid in sorted(model.collections):
        for member in model.collections[cid]["members"]:
            model.member_at(cid, member["key"])
            queries += 1
        model.member_at(cid, "missing-key")
        queries += 1
    cache_verdict = None
    if rep == "C":
        before = model.state_digest()
        model.materialized_graph()
        model.drop_cache()
        model.materialized_graph()
        cache_verdict = (model.state_digest() == before)
    rows = model.state_rows()
    complexity = model.complexity()
    terminal = {
        "versions": sorted(
            [{"id": o, "ver": v, "scope": dict(x["scope"]),
              "digest": x["content_digest"],
              "supersedes": list(x["supersedes"]) if x["supersedes"] else None,
              "state": x["state"], "label": x["label"],
              "created_by_op": x["created_by_op"]}
             for (o, v), x in model.versions.items()],
            key=lambda d: (d["id"], d["ver"])),
        "collections": sorted(
            [{"id": cid,
              "members": sorted(
                  [{"key": m["key"], "member": list(m["member"]),
                    "inserted_by": m["inserted_by"], "removed_by": m["removed_by"]}
                   for m in model.collections[cid]["members"]],
                  key=lambda m: (m["key"], str(m["member"])))}
             for cid in model.collections],
            key=lambda d: d["id"]),
    }
    core = {
        "scenario_id": scenario["id"], "representation": rep, "seed": seed,
        "observation_id": f"{scenario['id']}|{rep}|s{seed}",
        "status": "ok",
        "op_inputs": [{k: v for k, v in op.items() if k != "_auth_scope"}
                      for op in op_inputs],
        "op_outcomes": outcomes,
        "terminal_digest": model.state_digest(),
        "lineage_digest": model.lineage_digest(),
        "lineage_semantic_digest": model.lineage_semantic_digest(),
        "events": model.events,
        "export_scope": scope,
        "export_digest": export_digest,
        "roundtrip": {"match": rt["match"], "reason": rt["reason"],
                      "import_digest": rt["import_digest"],
                      "unsupported": rt["unsupported"]},
        "reconstruction": {"digest": reconstruction["digest"],
                           "complete": reconstruction["complete"],
                           "partials": reconstruction["partials"],
                           "baseline_ok": reconstruction["baseline_ok"]},
        "state_rows": rows,
        "state_bytes": model.state_bytes(),
        "complexity": complexity,
        "terminal": terminal,
        "query_probe": {"queries": queries, "steps": model.query_steps,
                        "cache_verdict": cache_verdict},
    }
    core["output_sha256"] = contract.digest(core)
    latencies = {"export_ns": t1 - t0, "roundtrip_ns": t2 - t1,
                 "reconstruct_ns": t3 - t2}
    return {"core": core, "latencies": latencies}


def generate_matrix(ticket: Path, executor: str):
    cases = corpus_cases(ticket)
    schema = operation_schema(ticket)
    observations = []
    for case in cases:
        for rep in REPS:
            for seed in SEEDS:
                observations.append(generate_observation(case, rep, seed, schema))
    observations.sort(key=lambda o: o["core"]["observation_id"])
    return observations


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticket", required=False)
    parser.add_argument("--out", required=True)
    parser.add_argument("--generate", action="store_true")
    parser.add_argument("--executor", required=False, default="A")
    args = parser.parse_args()
    ticket = Path(args.ticket).resolve() if args.ticket else HERE
    target = Path(args.out)
    target.mkdir(parents=True, exist_ok=True)
    if not args.generate:
        print("only --generate is supported", file=sys.stderr)
        return 1
    if args.executor not in ("A", "B"):
        print("unknown executor", file=sys.stderr)
        return 1
    observations = generate_matrix(ticket, args.executor)
    cores = [o["core"] for o in observations]
    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                            text=True, cwd=str(ticket.parents[3])).stdout.strip()
    manifest = {"schema": "agentos.s1-016.import-manifest/v1",
                "observations": len(cores), "executor": args.executor,
                "corpus_sha256": sha((ticket / "corpus.json").read_bytes()),
                "ticket_commit": commit,
                "ok": sum(c.get("status") == "ok" for c in cores),
                "quarantined": sum(c.get("status") == "quarantined" for c in cores)}
    (target / "observations.json").write_text(
        json.dumps({"schema": "agentos.s1-016.observations/v1",
                    "executor": args.executor,
                    "observations": observations}, indent=2) + "\n",
        encoding="utf-8", newline="\n")
    (target / "import-manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(manifest))
    return 0 if observations else 1


if __name__ == "__main__":
    raise SystemExit(main())
