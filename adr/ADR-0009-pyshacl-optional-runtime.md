# ADR-0009: Optional pySHACL/rdflib runtime for S1-003 SHACL engine validation

- Status: Accepted
- Date: 2026-08-24
- Deciders: project owner + implementation agent (S1-003)

## Context

S1-003 froze an open SHACL ontology contract (`shapes.ttl`) and 24 JSON fixtures
(`fixtures.json`) with a bounded **stdlib-only structural oracle**
(`validate_structural.py`). That oracle deliberately does not parse Turtle or
run a SHACL engine, so the ticket verdict remained `PASS_WITH_LIMITS`:
Turtle syntax, RDF entailment, SHACL-conformance, and SHACL-SPARQL behavior were
unverified.

The ticket goal is to close that single limitation by executing the same
fixtures through a **real pySHACL engine**, proving a 26/26 match with the
structural oracle, without weakening any existing invariant (promotion, scope,
ownership, EvidenceShape, independence). The core AgentOS runtime must remain
stdlib-only per ADR-0001; rdflib/pySHACL must therefore be **optional and
isolated**.

## Decision

1. **Optional, not core.** `rdflib` and `pyshacl` are declared in
   `research/tickets/stage-1/S1-003/requirements-pyshacl.txt` only. They are
   never imported by `src/agentos/` core, never added to the core venv, and
   never required by `python -m unittest discover -s tests`.

2. **Isolated interpreter.** A self-contained virtualenv is bootstrapped with
   the pinned versions below. The pySHACL runner
   (`validate_pyshacl.py`) fails closed with exit code 1 when the interpreter
   is absent or the pinned version differs — it never silently falls back.

3. **Pinned, hash-locked versions (Python 3.11.15):**
   - `rdflib==7.6.0`
   - `pyshacl==0.40.1`
   - `owlrl==7.6.2` (pulled by pyshacl)

   Pin file:
   `research/tickets/stage-1/S1-003/requirements-pyshacl.txt` with hashes.

4. **Determinism requirements.**
   - Fixtures are serialized to Turtle via a deterministic serializer
     (`fixtures_to_rdf.py`): stable IRIs keyed on `fixture_id`, no random
     blank-node IDs, sorted predicate/object order.
   - The pySHACL runner stores both a **raw report hash** (unstable,
     blank-node-aware) and a **stable semantic digest** (focus node + severity
     + normalized message set) for each run, plus the SHA-256 of `shapes.ttl`,
     `fixtures.json`, and the generated Turtle.
   - A mismatch against the structural oracle exits non-zero and records a
     `BLOCKED`/failure verdict.

5. **No network during validation.** `pyshacl.validate` is invoked with
   `advanced=False` and no online lookup. No fixture data is ever executed as
   code.

## Consequences

- The core stack stays stdlib-only (ADR-0001 preserved).
- A reproducible SHACL-engine run is now possible: the runner records runtime
  identity and report digests so the same inputs yield the same agreement.
- The ticket verdict graduates from `PASS_WITH_LIMITS` to `PASS` **only** when
  26/26 engine results agree with the structural oracle. If any case diverges,
  the ticket stays or regresses to `BLOCKED`.
- Adding future optional runtimes (e.g. an OWL-RL reasoner) follows this same
  ADR pattern.

## Alternatives considered

- Installing rdflib/pyshacl into the core venv: rejected — violates ADR-0001.
- Driving the SHACL-SPARQL checks by hand (regex): rejected — not a real
  engine; the structural oracle already covers the intended matrix.
- Using an online SHACL service: rejected — violates the offline/no-network
  invariant and adds non-determinism.
