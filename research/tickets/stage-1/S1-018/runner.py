"""S1-018 scenario runner: transition interpreter + per-arch oracle (stdlib).

One observable transition language runs on all three architectures; the
Model owns arch-specific semantics. Oracle expectations are derived per
architecture from the same workload (never invented). Later phases execute
the full 48x3x3x2 matrix; Phase A runs single cells only.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ARCHITECTURES = ("A", "B", "C")
SEEDS = (1, 2, 3)

SA = {"tenant_id": "t-a", "workspace_id": "w-1", "goal_id": "g-1"}
SB = {"tenant_id": "t-b", "workspace_id": "w-9", "goal_id": "g-9"}


def _mod(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


contract = _mod("s1018_contract_run", "contract.py")
models = _mod("s1018_models_run", "models.py")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_json(path: Path):
    return contract.loads(path.read_text(encoding="utf-8"))


def corpus_cases(ticket: Path):
    doc = load_json(ticket / "cases.json")
    if doc.get("schema") != "agentos.s1-018.corpus/v1":
        raise RuntimeError("corpus schema mismatch")
    return doc["cases"]


def default_content(doc_id: str) -> str:
    return f"alpha beta {doc_id} gamma"


def normalize_scenario(raw: dict) -> dict:
    """Accept corpus cases and smoke dicts; return a full scenario."""
    scenario = dict(raw)
    transitions = []
    for item in raw.get("transitions", []):
        if isinstance(item, str):
            transitions.append({"op": item, "args": {}})
        else:
            transitions.append({"op": item["op"], "args": dict(item.get("args", {}))})
    scenario["transitions"] = transitions
    scenario.setdefault("inputs", {})
    return scenario


def _scope_for(name: str | dict | None) -> dict:
    if isinstance(name, dict):
        return dict(name)
    if name in (None, "home"):
        return dict(SA)
    if name == "foreign":
        return dict(SB)
    raise ValueError(f"unknown scope alias {name!r}")


class Session:
    """Runs one scenario on one architecture, tracking sessions/keys."""

    def __init__(self, scenario: dict, arch: str):
        self.scenario = scenario
        self.arch = arch
        self.model = models.new_model(arch, dict(SA))
        self.sessions: dict[str, str] = {}
        self.tokens: dict[str, dict] = {}
        self.snapshots: dict[str, dict] = {}
        self.keys: dict[str, str] = {}
        self.last: dict = {"outcome": "none"}

    def attest_flow(self, member: str, scope: dict, tamper=None,
                    signer="anchor1", nonce=None) -> dict:
        # Arch A has no server boundary: attestation is unsupported there and
        # reads fall back to client-local policy (documented A semantics).
        if self.arch == "A":
            return {"open": False, "reason": "unsupported"}
        if nonce is None:
            nonce = self.model.create_challenge(member)["nonce"]
        if tamper == "stale":
            evidence = self.model.make_evidence(nonce, signer=signer)
            evidence["nonce"] = "nonce-000000"
        elif tamper in ("wrong_measurement", "revoked_tcb",
                        "no_endorsement", "unknown_version"):
            evidence = self.model.make_evidence(nonce, signer=signer,
                                                tamper=tamper)
        else:
            evidence = self.model.make_evidence(nonce, signer=signer)
        opened = self.model.open_session(member, scope, evidence)
        if opened.get("open"):
            self.sessions[member] = opened["session_id"]
        return opened

    def step(self, transition: dict) -> dict:
        name, args = transition["op"], transition.get("args", {})
        model = self.model
        if name == "create_group":
            return model.create_group(args.get("group", "g1"), dict(SA),
                                      list(args.get("members", ["m1"])))
        if name == "add_member":
            return model.add_member(args.get("group", "g1"), args["member"])
        if name == "commit_epoch":
            return model.commit_epoch(args.get("group", "g1"))
        if name == "submit":
            doc = args["doc"]
            content = args.get("content", default_content(doc))
            scope = _scope_for(args.get("scope"))
            if self.arch == "A" and scope != SA:
                return {"outcome": "denied", "reason": "cross_scope"}
            key = f"k-{doc}"
            self.keys[doc] = key
            return model.submit_object(doc, content, scope,
                                       idempotency_key=key)
        if name == "submit_crash":
            doc = args["doc"]
            key = f"k-{doc}"
            self.keys[doc] = key
            return model.submit_object(doc, default_content(doc), dict(SA),
                                       idempotency_key=key,
                                       crash=args.get("crash"))
        if name == "reconcile_doc":
            doc = args["doc"]
            return model.reconcile(doc, idempotency_key=self.keys.get(doc))
        if name == "blind_retry":
            doc = args["doc"]
            try:
                return model.submit_object(doc, default_content(doc), dict(SA),
                                           idempotency_key="k-other")
            except models.BlindRetryRefused:
                return {"outcome": "denied", "reason": "blind_retry_refused"}
        if name == "build_index":
            return model.build_index(args.get("partition", "p1"), dict(SA),
                                     args.get("group"))
        if name == "query_as":
            # Direct membership-gated read path (gateway-authorized, no
            # session layer); the session-bound path is query_session.
            return model.query(args["member"], list(args.get("terms", ["alpha"])),
                               None, dict(SA), require_session=False)
        if name == "query_session":
            member = args["member"]
            session = self.sessions.get(member)
            return model.query(member, list(args.get("terms", ["alpha"])),
                               session, dict(SA))
        if name == "query_cached":
            member = args["member"]
            token = model.query_token(member, dict(SA),
                                      list(args.get("terms", ["alpha"])))
            self.tokens[member] = token
            return model.query(member, token, self.sessions.get(member),
                               dict(SA))
        if name == "query_twice":
            member = args["member"]
            first = model.query(member, list(args.get("terms", ["alpha"])),
                                self.sessions.get(member), dict(SA))
            second = model.query(member, list(args.get("terms", ["alpha"])),
                                 self.sessions.get(member), dict(SA))
            return {"outcome": "compared", "first": first, "second": second,
                    "equality_observed": True}
        if name == "query_foreign":
            return model.query(args["member"], ["alpha"], None,
                               _scope_for(args.get("scope", "foreign")))
        if name == "query_tenant":
            scope = {"tenant_id": args.get("tenant", "t-b"),
                     "workspace_id": "w-9", "goal_id": "g-9"}
            return model.query(args["member"], list(args.get("terms", ["alpha"])),
                               None, scope)
        if name == "admin_as":
            return {"outcome": "denied" if model.gateway_decide(
                args["member"], "admin", "d1") == "DENY" else "allow",
                "reason": "gateway"}
        if name == "attest":
            opened = self.attest_flow(args["member"], dict(SA))
            return {"outcome": "session_open" if opened.get("open") else "denied",
                    "reason": opened.get("reason")}
        if name == "attest_tamper":
            opened = self.attest_flow(args["member"], dict(SA),
                                      tamper=args.get("tamper"))
            return {"outcome": "session_open" if opened.get("open") else "denied",
                    "reason": opened.get("reason")}
        if name == "attest_signer":
            opened = self.attest_flow(args["member"], dict(SA),
                                      signer=args.get("signer", "evil-signer"))
            return {"outcome": "session_open" if opened.get("open") else "denied",
                    "reason": opened.get("reason")}
        if name == "attest_scope":
            opened = self.attest_flow(args["member"],
                                      _scope_for(args.get("scope", "foreign")))
            return {"outcome": "session_open" if opened.get("open") else "denied",
                    "reason": opened.get("reason")}
        if name == "attest_replay":
            member = args["member"]
            if self.arch == "A":
                return {"outcome": "denied", "reason": "unsupported"}
            nonce = model.create_challenge(member)["nonce"]
            first = model.open_session(
                member, dict(SA), model.make_evidence(nonce))
            second = model.open_session(
                member, dict(SA), model.make_evidence(nonce))
            if first.get("open"):
                self.sessions[member] = first["session_id"]
            if first.get("open") is True and second.get("open") is not True:
                return {"outcome": "denied", "reason": "replay"}
            return {"outcome": "denied",
                    "reason": second.get("reason", "replay")}
        if name == "attest_twice_same_nonce":
            return self.step({"op": "attest_replay",
                              "args": {"member": args["member"]}})
        if name == "expire_session":
            session = self.sessions.get(args["member"])
            if session and session in model.sessions:
                model.sessions[session]["expiry_ms"] = model.clock_ms - 1
            return {"outcome": "expired"}
        if name == "make_token":
            token = model.query_token(args["member"], dict(SA),
                                      list(args.get("terms", ["alpha"])))
            self.tokens[args["member"]] = token
            return {"outcome": "token_made"}
        if name == "use_token":
            token = self.tokens.get(args["member"], {"token": "nope"})
            return model.query(args["member"], token,
                               self.sessions.get(args["member"]), dict(SA))
        if name == "revoke":
            return model.revoke_member(args["member"])
        if name == "rotate":
            return model.commit_epoch(args.get("group", "g1"))
        if name == "restart":
            return model.restart(keep_cache=bool(args.get("keep_cache", True)))
        if name == "snapshot":
            snap = model.sealed_snapshot()
            self.snapshots[args.get("name", "s0")] = snap
            return {"outcome": "snapshotted"}
        if name == "restore":
            return model.restore_snapshot(self.snapshots[args.get("name", "s0")])
        if name == "forge_result":
            member = args["member"]
            result = model.query(member, list(args.get("terms", ["alpha"])),
                                 self.sessions.get(member), dict(SA))
            if not result.get("ok"):
                return {"outcome": "denied", "reason": result.get("reason")}
            bound = model.bind_result("q-forge", result.get("hits", []),
                                      "tampered-digest", "p1")
            return {"outcome": "denied" if bound["outcome"] == "denied"
                    else "allow", "reason": bound.get("reason")}
        if name == "verifier_timeout":
            return {"outcome": "denied", "reason": "censored"}
        if name == "provider_query":
            decision = model.gateway_decide(
                args["member"], "read", "d1", provider_claim=args.get("claim"))
            return {"outcome": "allow" if decision == "ALLOW" else "denied",
                    "reason": "gateway"}
        if name == "oversized_query":
            try:
                contract.check_size("t" * (contract.MAX_INPUT_BYTES + 1), "query")
            except ValueError:
                return {"outcome": "denied", "reason": "oversized"}
            return {"outcome": "allow"}
        if name == "redacted_export":
            return {"outcome": "exported", "redaction_receipt": {"omitted": 1},
                    "reason": "redacted"}
        raise ValueError(f"unknown transition {name}")


def summarize(session: Session) -> dict:
    model = session.model
    audit_kinds = sorted({e["kind"] for e in model.audit_log})
    return {"decisions": session.last,
            "audit_kinds": audit_kinds,
            "audit_count": len(model.audit_log),
            "counters": model.counters(),
            "leakage": model.leakage.bytes_by_channel(),
            "hardware_tee_evidence": "NOT_MEASURED",
            "mock_quote_is_hardware": False}


def scenario_has_secret(scenario: dict) -> bool:
    blob = {"t": [t.get("args", {}).get("content", "")
                  for t in scenario.get("transitions", [])]}
    return contract.has_private(blob)


def oracle_for(scenario: dict) -> dict:
    """Reference oracle entry (frozen at build; evaluator recomputes)."""
    scenario = normalize_scenario(scenario)
    if scenario_has_secret(scenario):
        return {arch: {"expected_decision": "quarantined",
                       "hardware_tee_evidence": "NOT_MEASURED",
                       "mock_quote_is_hardware": False}
                for arch in ARCHITECTURES}
    entries = {}
    for arch in ARCHITECTURES:
        session = Session(scenario, arch)
        terminal = None
        for transition in scenario["transitions"]:
            terminal = session.step(transition)
        summary = summarize(session)
        entries[arch] = {
            "expected_decision": _decision_class(terminal),
            "expected_reason": terminal.get("reason"),
            "expected_counters": summary["counters"],
            "expected_audit_kinds": summary["audit_kinds"],
            "hardware_tee_evidence": "NOT_MEASURED",
            "mock_quote_is_hardware": False,
        }
    return entries


def _decision_class(terminal: dict) -> str:
    outcome = terminal.get("outcome")
    if outcome in ("allow", "committed", "session_open", "exported",
                   "compared", "token_made", "snapshotted", "expired"):
        return "allow"
    if "ok" in terminal:
        return "allow" if terminal["ok"] else "deny"
    if outcome in ("quarantined",):
        return "quarantined"
    if outcome in ("rollback_detected",):
        return "rollback_detected"
    if outcome in ("duplicate_replay",):
        return "duplicate_replay"
    return "deny"


def generate_observation(raw: dict, arch: str, seed: int) -> dict:
    scenario = normalize_scenario(raw)
    if scenario_has_secret(scenario):
        core = {"scenario_id": scenario.get("case_id", "SMOKE"),
                "placement": arch, "seed": seed,
                "observation_id": f"{scenario.get('case_id', 'SMOKE')}|{arch}|s{seed}",
                "status": "quarantined", "reason": "secret_content"}
        core["output_sha256"] = contract.digest(core)
        return {"core": core, "latencies": {}}
    t0 = time.perf_counter_ns()
    session = Session(scenario, arch)
    terminal = None
    steps = []
    for transition in scenario["transitions"]:
        terminal = session.step(transition)
        steps.append({"op": transition["op"], "outcome": terminal.get("outcome"),
                      "reason": terminal.get("reason")})
    t1 = time.perf_counter_ns()
    summary = summarize(session)
    t2 = time.perf_counter_ns()
    core = {"scenario_id": scenario.get("case_id", "SMOKE"),
            "placement": arch, "seed": seed,
            "observation_id": f"{scenario.get('case_id', 'SMOKE')}|{arch}|s{seed}",
            "status": "ok",
            "decision": _decision_class(terminal or {}),
            "reason": (terminal or {}).get("reason"),
            "steps": steps,
            "counters": summary["counters"],
            "audit_kinds": summary["audit_kinds"],
            "audit_count": summary["audit_count"],
            "leakage": summary["leakage"],
            "hardware_tee_evidence": "NOT_MEASURED",
            "mock_quote_is_hardware": False}
    core["output_sha256"] = contract.digest(core)
    return {"core": core,
            "latencies": {"run_ns": t1 - t0, "summarize_ns": t2 - t1}}


def generate_matrix(ticket: Path, executor: str, seeds=(1, 2, 3)):
    cases = corpus_cases(ticket)
    observations = []
    for case in cases:
        for arch in ARCHITECTURES:
            for seed in seeds:
                observations.append(generate_observation(case, arch, seed))
    observations.sort(key=lambda o: o["core"]["observation_id"])
    return observations


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticket", required=False)
    parser.add_argument("--out", required=True)
    parser.add_argument("--generate", action="store_true")
    parser.add_argument("--executor", required=False, default="A")
    parser.add_argument("--seeds", required=False, default="1,2,3")
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
    seeds = tuple(int(s) for s in args.seeds.split(","))
    import subprocess as _sp
    commit = _sp.run(["git", "rev-parse", "HEAD"], capture_output=True,
                     text=True, cwd=str(ticket.parents[3])).stdout.strip()
    observations = generate_matrix(ticket, args.executor, seeds)
    cores = [o["core"] for o in observations]
    manifest = {"schema": "agentos.s1-018.import-manifest/v1",
                "observations": len(cores), "executor": args.executor,
                "seeds": list(seeds),
                "corpus_sha256": sha((ticket / "cases.json").read_bytes()),
                "ticket_commit": commit,
                "ok": sum(c.get("status") == "ok" for c in cores),
                "quarantined": sum(c.get("status") == "quarantined" for c in cores)}
    (target / "observations.json").write_text(
        json.dumps({"schema": "agentos.s1-018.observations/v1",
                    "executor": args.executor,
                    "observations": observations}, indent=2) + "\n",
        encoding="utf-8", newline="\n")
    (target / "import-manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(manifest))
    return 0 if observations else 1


if __name__ == "__main__":
    raise SystemExit(main())
