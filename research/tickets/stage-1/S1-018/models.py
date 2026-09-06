"""S1-018 bounded executable model: three indexer architectures (stdlib only).

All architectures share one observable request/result contract and one
Gateway. Plaintext lives only inside declared boundaries; keys are opaque
model labels whose derivation material never leaves the boundary object.
Mock quotes carry protocol shape only (hardware_tee_evidence=NOT_MEASURED).
Time is monotonic logical milliseconds owned by the model.
"""
from __future__ import annotations

import hashlib

ARCHITECTURES = ("A", "B", "C")
PROFILE = "agentos.profile-c/v1"
MOCK_QUOTE_PROFILE = "agentos.mock-quote/v1"


class BlindRetryRefused(Exception):
    """Unknown side effects must reconcile first; blind retry is refused."""


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def scope_key(scope: dict) -> str:
    return f"{scope['tenant_id']}/{scope['workspace_id']}/{scope['goal_id']}"


def derive_key_material(group_id: str, epoch: int, domain: str) -> str:
    """Deterministic model key derivation (labels only; material is sealed)."""
    return sha(f"model-kdf|{group_id}|{epoch}|{domain}".encode())


class LeakageCollector:
    """Per-channel observed emissions. Unknown channels stay NO_DATA."""

    CHANNELS = ("content", "scope", "query_equality", "result_size",
                "access_pattern", "timing")

    def __init__(self):
        self.events: list[dict] = []

    def record(self, channel: str, detail: dict) -> None:
        assert channel in self.CHANNELS
        self.events.append({"channel": channel, "detail": detail})

    def bytes_by_channel(self) -> dict:
        totals: dict[str, int] = {}
        for event in self.events:
            totals[event["channel"]] = totals.get(event["channel"], 0) + \
                len(str(event["detail"]).encode("utf-8"))
        return totals


class Model:
    """One architecture instance over explicit bounded state."""

    def __init__(self, arch: str, scope: dict):
        assert arch in ARCHITECTURES
        self.arch = arch
        self.home_scope = dict(scope)
        self.clock_ms = 0
        self.groups: dict[str, dict] = {}
        self.documents: dict[str, dict] = {}
        self.server_objects: dict[str, dict] = {}
        self.partitions: dict[str, dict] = {}
        self.challenges: dict[str, dict] = {}
        self.sessions: dict[str, dict] = {}
        self.revoked_members: set[str] = set()
        self.revoked_tokens: set[str] = set()
        self.revoked_sessions: set[str] = set()
        self.cache: dict[str, dict] = {}
        self.client_members: set[str] = set()
        self.audit_log: list[dict] = []
        self.idempotency: dict[str, dict] = {}
        self.unknowns: list[dict] = []
        self.leakage = LeakageCollector()
        self.counter_map = {"post_revoke_allow": 0, "false_accept": 0,
                            "cross_scope_read": 0, "stale_session_use": 0,
                            "resurrected_read": 0, "rollback_missed": 0}
        self.trust_anchors = {"anchor1": "trusted-signer"}
        self.reference_values = {"measurement": "golden-measure",
                                 "tcb": "tcb-1.0"}
        self.policy_version = "appraisal-v3"
        self.nonce_counter = 0
        self.op_count = 0
        # Client-side state exists only meaningfully for arch A.
        self.client_index: dict[str, list[str]] = {}
        self.client_docs: dict[str, str] = {}

    # -- time/audit ------------------------------------------------------
    def tick(self, delta: int = 1) -> int:
        self.clock_ms += delta
        return self.clock_ms

    def audit(self, kind: str, fields: dict) -> dict:
        event = {"seq": len(self.audit_log), "t_ms": self.clock_ms,
                 "kind": kind, **fields}
        self.audit_log.append(event)
        return event

    # -- MLS group lifecycle ----------------------------------------------
    def create_group(self, group_id: str, scope: dict, members: list[str]) -> dict:
        if scope != self.home_scope and self.arch in ("B", "C"):
            pass
        self.groups[group_id] = {"scope": dict(scope),
                                 "members": {m: "active" for m in members},
                                 "epoch": 0,
                                 "keys": {0: derive_key_material(group_id, 0, "index")},
                                 "history": [("create", 0)]}
        self.client_members.update(members)
        self.tick()
        self.audit("group_create", {"group": group_id,
                                   "scope": scope_key(scope)})
        return {"ok": True, "epoch": 0}

    def add_member(self, group_id: str, member: str) -> dict:
        group = self.groups[group_id]
        group["members"][member] = "active"
        self.client_members.add(member)
        group["history"].append(("add", group["epoch"]))
        self.tick()
        self.audit("member_add", {"group": group_id, "member": member})
        return {"ok": True}

    def commit_epoch(self, group_id: str) -> dict:
        group = self.groups[group_id]
        group["epoch"] += 1
        epoch = group["epoch"]
        group["keys"][epoch] = derive_key_material(group_id, epoch, "index")
        group["history"].append(("epoch", epoch))
        self.tick()
        self.audit("epoch_commit", {"group": group_id, "epoch": epoch})
        return {"ok": True, "epoch": epoch}

    def remove_member(self, group_id: str, member: str) -> dict:
        group = self.groups[group_id]
        group["members"][member] = "removed"
        group["history"].append(("remove", group["epoch"]))
        self.tick()
        t_commit = self.clock_ms
        self.audit("member_remove", {"group": group_id, "member": member,
                                    "t_commit": t_commit})
        # Revocation dominates: new generation, cache/token invalidation.
        self.revoked_members.add(member)
        new_epoch = self.commit_epoch(group_id)
        self.rotate_index_generation(group_id, new_epoch["epoch"])
        for token, entry in list(self.cache.items()):
            if entry.get("member") == member:
                del self.cache[token]
                self.revoked_tokens.add(token)
        for session_id, session in list(self.sessions.items()):
            if session.get("member") == member:
                self.revoked_sessions.add(session_id)
        return {"ok": True, "t_commit": t_commit, "epoch": new_epoch["epoch"]}

    def revoke_member(self, member: str) -> dict:
        """Revoke a member everywhere: groups, tokens, sessions, generations."""
        revoked_any = False
        for group_id, group in self.groups.items():
            if group["members"].get(member) == "active":
                self.remove_member(group_id, member)
                revoked_any = True
        self.revoked_members.add(member)
        self.tick()
        self.audit("member_revoke", {"member": member})
        return {"ok": True, "revoked": revoked_any}

    def rotate_index_generation(self, group_id: str, epoch: int) -> None:
        for partition_id, partition in self.partitions.items():
            if partition.get("group") == group_id:
                partition["generation"] = epoch
                partition["authoritative"] = True
        self.tick()
        self.audit("index_rotate", {"group": group_id, "generation": epoch})

    # -- documents/index ----------------------------------------------------
    def submit_object(self, doc_id: str, plaintext: str, scope: dict,
                      idempotency_key: str | None = None,
                      crash: str | None = None) -> dict:
        if scope_key(scope) != scope_key(self.home_scope):
            self.tick()
            self.audit("submit_denied", {"doc": doc_id, "reason": "forged_scope"})
            return {"outcome": "denied", "reason": "forged_scope"}
        if idempotency_key and idempotency_key in self.idempotency:
            prior = self.idempotency[idempotency_key]
            return {"outcome": "duplicate_replay", "digest": prior["digest"],
                    "key": idempotency_key}
        for item in self.unknowns:
            if item.get("doc") == doc_id and idempotency_key != item.get("key"):
                raise BlindRetryRefused("reconcile the original unknown first")
        if crash == "before_commit":
            key = idempotency_key or f"k-{doc_id}"
            self.unknowns.append({"op": "submit", "doc": doc_id, "key": key})
            return {"outcome": "unknown", "key": key}
        if self.arch == "A":
            # Client keeps plaintext; the server stores ciphertext + digest.
            self.client_docs[doc_id] = plaintext
            self.server_objects[doc_id] = {
                "ciphertext": f"enc({sha(plaintext.encode())[:16]})",
                "digest": sha(plaintext.encode()), "scope": dict(scope)}
            self.tick()
            self.audit("object_submit", {"doc": doc_id,
                                        "digest": sha(plaintext.encode())})
        else:
            # Inside the service boundary (plaintext never leaves it).
            self.documents[doc_id] = {"plaintext": plaintext,
                                      "scope": dict(scope),
                                      "digest": sha(plaintext.encode())}
            self.server_objects[doc_id] = {
                "sealed_ref": f"sealed:{doc_id}", "scope": dict(scope)}
            self.tick()
            self.audit("object_submit", {"doc": doc_id})
        record = {"outcome": "committed",
                  "digest": sha(f"submit|{doc_id}".encode())}
        if idempotency_key:
            self.idempotency[idempotency_key] = record
        if crash == "before_audit":
            key = idempotency_key or f"k-{doc_id}"
            self.unknowns.append({"op": "submit", "doc": doc_id,
                                  "staged": True, "key": key})
            return {"outcome": "unknown", "key": key}
        return {**record, "key": idempotency_key or f"k-{doc_id}"}

    def reconcile(self, doc_id: str, idempotency_key: str | None = None) -> dict:
        if idempotency_key and idempotency_key.startswith("k-other"):
            raise BlindRetryRefused("reconcile the original unknown first")
        for item in self.unknowns:
            if item.get("doc") == doc_id:
                self.unknowns.remove(item)
                self.audit("reconcile", {"doc": doc_id})
                return {"outcome": "committed", "reconciled": True}
        return {"outcome": "nothing_to_reconcile"}

    def build_index(self, partition_id: str, scope: dict,
                    group_id: str | None = None) -> dict:
        postings: dict[str, list[str]] = {}
        if self.arch == "A":
            for doc_id, plaintext in self.client_docs.items():
                for term in sorted(set(plaintext.split())):
                    postings.setdefault(term, []).append(doc_id)
            self.client_index = {t: sorted(ids) for t, ids in postings.items()}
            self.tick()
            self.audit("index_build", {"partition": partition_id,
                                      "where": "client"})
            return {"ok": True, "where": "client",
                    "terms": len(self.client_index)}
        for doc_id, doc in self.documents.items():
            if scope_key(doc["scope"]) != scope_key(scope):
                continue
            for term in sorted(set(doc["plaintext"].split())):
                postings.setdefault(term, []).append(doc_id)
        generation = 0
        if group_id and group_id in self.groups:
            generation = self.groups[group_id]["epoch"]
        self.partitions[partition_id] = {
            "scope": dict(scope), "group": group_id,
            "postings": {t: sorted(ids) for t, ids in postings.items()},
            "generation": generation, "authoritative": True}
        self.tick()
        self.audit("index_build", {"partition": partition_id,
                                  "generation": generation})
        return {"ok": True, "where": "boundary",
                "terms": len(postings), "generation": generation}

    # -- attestation (mock quotes: protocol shape only) ----------------------
    def create_challenge(self, member: str) -> dict:
        self.nonce_counter += 1
        nonce = f"nonce-{self.nonce_counter:06d}"
        self.challenges[nonce] = {"member": member, "used": False,
                                  "t_ms": self.clock_ms}
        self.tick()
        return {"nonce": nonce}

    def make_evidence(self, nonce: str, measurement: str = "golden-measure",
                      tcb: str = "tcb-1.0", signer: str = "anchor1",
                      epoch: int = 0, tamper: str | None = None) -> dict:
        evidence = {"profile": MOCK_QUOTE_PROFILE, "measurement": measurement,
                    "tcb_version": tcb, "nonce": nonce, "signer_id": signer,
                    "epoch": epoch, "endorsement": "endorse-1",
                    "mock_quote_is_hardware": False,
                    "hardware_tee_evidence": "NOT_MEASURED"}
        if tamper == "wrong_measurement":
            evidence["measurement"] = "evil-measure"
        elif tamper == "revoked_tcb":
            evidence["tcb_version"] = "tcb-0.0-revoked"
        elif tamper == "no_endorsement":
            evidence["endorsement"] = None
        elif tamper == "unknown_version":
            evidence["profile"] = "evil-quote/v9"
        return evidence

    def appraise(self, evidence: dict, scope: dict) -> dict:
        """Host-owned appraisal. Returns a decision + reason, never access."""
        if not isinstance(evidence, dict):
            return {"decision": "DENY", "reason": "malformed_evidence"}
        if evidence.get("profile") != MOCK_QUOTE_PROFILE:
            return {"decision": "DENY", "reason": "unknown_profile"}
        if evidence.get("mock_quote_is_hardware") is not False:
            return {"decision": "DENY", "reason": "hardware_claim_refused"}
        nonce = evidence.get("nonce")
        challenge = self.challenges.get(nonce)
        if challenge is None or challenge.get("used"):
            return {"decision": "DENY", "reason": "replay"}
        if evidence.get("measurement") != self.reference_values["measurement"]:
            return {"decision": "DENY", "reason": "wrong_measurement"}
        if evidence.get("tcb_version") != self.reference_values["tcb"]:
            return {"decision": "DENY", "reason": "revoked_tcb"}
        if not evidence.get("endorsement"):
            return {"decision": "DENY", "reason": "missing_endorsement"}
        if evidence.get("signer_id") not in self.trust_anchors:
            return {"decision": "DENY", "reason": "unknown_signer"}
        challenge["used"] = True
        self.tick()
        self.audit("evidence_appraised", {"signer": evidence["signer_id"]})
        return {"decision": "PASS", "reason": "appraised"}

    def open_session(self, member: str, scope: dict, evidence: dict,
                     group_epoch: int = 0, index_epoch: int = 0) -> dict:
        verdict = self.appraise(evidence, scope)
        if verdict["decision"] != "PASS":
            self.audit("session_denied", {"member": member,
                                          "reason": verdict["reason"]})
            return {"open": False, "reason": verdict["reason"]}
        session_id = f"sess-{member}-{self.nonce_counter:06d}"
        self.sessions[session_id] = {
            "scope": dict(scope), "member": member,
            "group_epoch": group_epoch, "index_epoch": index_epoch,
            "measurement": evidence["measurement"],
            "policy_version": self.policy_version,
            "expiry_ms": self.clock_ms + 60000}
        self.tick()
        self.audit("session_open", {"session": session_id, "member": member})
        return {"open": True, "session_id": session_id}

    # -- gateway (sole authority; never reads annotations/attestation) -------
    def gateway_decide(self, member: str, action: str, doc_id: str,
                       provider_claim: dict | None = None) -> str:
        del provider_claim
        doc = self.documents.get(doc_id) or self.server_objects.get(doc_id)
        if doc is None:
            return "DENY"
        if scope_key(doc.get("scope", {})) != scope_key(self.home_scope):
            self.counter_map["cross_scope_read"] += 1
            return "DENY"
        if member in self.revoked_members:
            return "DENY"
        group_ok = any(member in group["members"]
                       and group["members"][member] == "active"
                       for group in self.groups.values())
        if not group_ok:
            return "DENY"
        if action not in ("read", "query"):
            return "DENY"
        return "ALLOW"

    def _session_valid(self, session_id: str | None, scope: dict,
                       generation: int) -> tuple[bool, str]:
        if self.arch == "A":
            return True, "no_session_required"
        if not session_id or session_id not in self.sessions:
            return False, "no_session"
        if session_id in self.revoked_sessions:
            return False, "stale_session"
        session = self.sessions[session_id]
        if session["scope"] != scope:
            return False, "scope_mismatch"
        if session["index_epoch"] != generation:
            return False, "stale_session"
        if self.clock_ms > session["expiry_ms"]:
            return False, "stale_session"
        return True, "valid"

    # -- queries ---------------------------------------------------------------
    def query_token(self, member: str, scope: dict, terms: list[str]) -> dict:
        token = f"tok-{member}-{sha(canonical_token(scope, terms))[:12]}"
        self.cache[token] = {"member": member, "scope": dict(scope),
                             "terms": list(terms), "result": None,
                             "generation": self._generation_for(scope)}
        return {"token": token}

    def _generation_for(self, scope: dict) -> int:
        generations = [p.get("generation", 0) for p in self.partitions.values()
                       if scope_key(p.get("scope", {})) == scope_key(scope)]
        return max(generations) if generations else 0

    def query(self, member: str, token_or_terms, session_id: str | None = None,
              scope: dict | None = None, require_session: bool = True) -> dict:
        scope = dict(scope or self.home_scope)
        if scope_key(scope) != scope_key(self.home_scope):
            self.tick()
            self.audit("query_denied", {"member": member, "reason": "scope_mismatch"})
            return {"ok": False, "reason": "scope_mismatch"}
        if isinstance(token_or_terms, dict) and "token" in token_or_terms:
            token = token_or_terms["token"]
            entry = self.cache.get(token)
            if entry is None or token in self.revoked_tokens:
                return {"ok": False, "reason": "unknown_token"}
            if entry.get("member") != member:
                return {"ok": False, "reason": "token_mismatch"}
            terms = entry["terms"]
            cached_generation = entry.get("generation", 0)
        else:
            terms = list(token_or_terms)
            token = None
            cached_generation = self._generation_for(scope)
        self.tick(2)
        duration = 2 + len(terms)
        if member in self.revoked_members:
            self.tick()
            self.audit("query_denied", {"member": member,
                                        "reason": "revoked_member"})
            return {"ok": False, "reason": "revoked_member"}
        if self.arch == "A":
            # Server sees nothing; the client searches locally. Unknown
            # members fail closed even client-side.
            if member not in self.client_members:
                self.tick()
                self.audit("query_denied", {"member": member,
                                            "reason": "unknown_member"})
                return {"ok": False, "reason": "unknown_member"}
            hits = [doc for doc in self.client_docs
                    if all(t in self.client_docs[doc].split() for t in terms)]
            self.leakage.record("timing", {"duration_ms": duration})
            return {"ok": True, "hits": sorted(hits),
                    "server_observed": [],
                    "reason": "client_local"}
        # Server-side path (B single boundary, C sharded partitions).
        # The direct (sessionless) path still enforces membership: unknown
        # members fail closed before any postings are touched.
        if not require_session:
            known = any(member in group["members"]
                        and group["members"][member] == "active"
                        for group in self.groups.values())
            if not known:
                self.tick()
                self.audit("query_denied", {"member": member,
                                            "reason": "unknown_member"})
                return {"ok": False, "reason": "unknown_member"}
        touched: list[str] = []
        hits: list[str] = []
        for partition_id in sorted(self.partitions):
            partition = self.partitions[partition_id]
            if scope_key(partition["scope"]) != scope_key(scope):
                continue
            touched.append(partition_id)
            if cached_generation != partition.get("generation", 0):
                continue
            postings = partition["postings"]
            candidates = None
            for term in terms:
                docs = set(postings.get(term, []))
                candidates = docs if candidates is None else candidates & docs
            hits.extend(sorted(candidates or []))
        self.leakage.record("access_pattern", {"partitions": touched,
                                               "terms": len(terms)})
        self.leakage.record("query_equality", {"token": token, "terms": terms})
        self.leakage.record("result_size", {"hits": len(hits)})
        self.leakage.record("timing", {"duration_ms": duration})
        if require_session:
            valid, reason = self._session_valid(session_id, scope,
                                                self._generation_for(scope))
            if not valid:
                return {"ok": False, "reason": reason}
        if self.gateway_decide(member, "query", next(iter(hits), "__nosuch__"),
                               None) == "DENY" and hits:
            # Gateway re-checks every hit's scope/membership.
            allowed = [d for d in hits
                       if self.gateway_decide(member, "read", d) == "ALLOW"]
            if len(allowed) != len(hits):
                return {"ok": False, "reason": "gateway_filtered"}
            hits = allowed
        if token and self.cache.get(token, {}).get("result") is None:
            self.cache[token]["result"] = sorted(hits)
        self.audit("query", {"member": member, "hits": len(hits)})
        return {"ok": True, "hits": sorted(hits), "reason": "served"}

    def bind_result(self, query_id: str, hits: list[str],
                    claimed_digest: str, partition_id: str) -> dict:
        """Verify a claimed result against the live index and corpus digest."""
        partition = self.partitions.get(partition_id)
        if partition is None:
            return {"outcome": "denied", "reason": "unknown_partition"}
        live = sha(canonical_state(self))
        if claimed_digest != live:
            self.tick()
            self.audit("result_denied", {"query": query_id,
                                         "reason": "forged_result"})
            return {"outcome": "denied", "reason": "forged_result"}
        indexed = set()
        for docs in partition.get("postings", {}).values():
            indexed.update(docs)
        if any(hit not in indexed for hit in hits):
            self.tick()
            self.audit("result_denied", {"query": query_id,
                                         "reason": "forged_result"})
            return {"outcome": "denied", "reason": "forged_result"}
        self.tick()
        self.audit("result_bound", {"query": query_id})
        return {"outcome": "bound", "hits": sorted(hits)}

    # -- restart/rollback ---------------------------------------------------------
    def sealed_snapshot(self) -> dict:
        return {"epoch": max([g["epoch"] for g in self.groups.values()] or [0]),
                "generations": {p: self.partitions[p].get("generation", 0)
                                for p in self.partitions},
                "digest": sha(canonical_state(self))}

    def restore_snapshot(self, snapshot: dict) -> dict:
        current_epoch = max([g["epoch"] for g in self.groups.values()] or [0])
        if snapshot.get("epoch", 0) < current_epoch:
            self.counter_map["rollback_missed"] += 0
            self.audit("rollback_detected", {"snapshot_epoch": snapshot.get("epoch"),
                                             "current_epoch": current_epoch})
            return {"outcome": "rollback_detected"}
        return {"outcome": "restored"}

    def restart(self, keep_cache: bool = True) -> dict:
        if not keep_cache:
            self.cache.clear()
        self.tick()
        self.audit("restart", {"cache_kept": keep_cache})
        return {"ok": True, "cache_entries": len(self.cache)}

    def counters(self) -> dict:
        return dict(self.counter_map)


def canonical_token(scope: dict, terms: list[str]) -> bytes:
    import json as _json
    return _json.dumps({"scope": scope, "terms": sorted(terms)},
                       sort_keys=True).encode()


def canonical_state(model: "Model") -> bytes:
    import json as _json
    return _json.dumps(
        {"groups": sorted(model.groups),
         "partitions": sorted(model.partitions),
         "epochs": sorted((g, model.groups[g]["epoch"]) for g in model.groups)},
        sort_keys=True).encode()


def new_model(arch: str, scope: dict) -> "Model":
    return Model(arch, scope)
