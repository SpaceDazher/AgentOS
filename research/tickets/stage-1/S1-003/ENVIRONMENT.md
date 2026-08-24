# S1-003 optional pySHACL environment

This directory contains an **optional, isolated** runtime used only to close the
`PASS_WITH_LIMITS` gap in S1-003 (see ADR-0009).  The core AgentOS runtime stays
stdlib-only (ADR-0001); rdflib/pySHACL are never imported by `src/agentos/` and
never required by the unit test suite.

## Pinned versions

| Component | Version |
|-----------|---------|
| Python    | 3.11.15 |
| rdflib    | 7.6.0   |
| pyshacl   | 0.40.1  |
| owlrl     | 7.6.2   |

Hashes are locked in `requirements-pyshacl.txt` (all deps + transitive, hash-locked).

## Creating the isolated venv (Windows / git-bash)

From this directory (`research/tickets/stage-1/S1-003`):

```bash
python3.11 -m venv .venv-pyshacl
./.venv-pyshacl/Scripts/python -m pip install --upgrade pip
./.venv-pyshacl/Scripts/python -m pip install --require-hashes -r requirements-pyshacl.txt
```

## Running the engine

The runner fails closed (exit code 1) if pySHACL is not importable in the
active interpreter, or if any of the 26 expected outcomes does not match:

```bash
# Using the isolated venv (recommended — pinned versions + hash lock):
./.venv-pyshacl/Scripts/python validate_pyshacl.py \
    --fixtures fixtures.json \
    --shapes-open shapes-v3.ttl \
    --shapes-promoted-only shapes-v3-promoted-only.ttl \
    --out engine-results.json

# Compare against the structural oracle:
./.venv-pyshacl/Scripts/python comparison.py \
    --engine-results engine-results.json \
    --structural-results raw-results.json \
    --out comparison-results.json

# Run adversarial probes:
./.venv-pyshacl/Scripts/python probes.py --out probe-results.json
```

## Determinism

- The Turtle serialization (`fixtures.ttl`, emitted by `fixtures_to_rdf.py`)
  uses stable IRIs keyed on `fixture_id` and **no random blank-node IDs**.
- Each SHACL run stores both a raw report hash (may vary due to internal blank
  nodes) and a stable **semantic digest** (sorted set of
  `<focus-node>|<severity>|<normalized-message>` tuples).
- Input SHA-256 of `shapes-v3.ttl`, `fixtures.json` and the generated Turtle are
  recorded per run.
