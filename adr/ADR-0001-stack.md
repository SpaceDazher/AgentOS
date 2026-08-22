# ADR-0001: Language and stack — Python 3.11 + stdlib, SQLite, zero-core-dependencies

- Status: Accepted
- Date: 2026-08-21
- Deciders: project owner + implementation agent

## Context

The repository contains only research documents; there is no existing code,
language choice or stack to preserve. The task mandates a minimal typed stack,
one deployable application, relational storage and a separated domain core.
Tests must not require an LLM.

## Decision

- **Language:** Python 3.11 (available on the host; the user is a backend dev
  learning Python — this maximizes their ability to read/extend the code).
- **Typing:** full `typing` annotations + `dataclasses`; runtime validation via
  explicit checks in transition guards (no pydantic dependency at core).
- **Storage:** SQLite via `sqlite3` (stdlib), WAL mode, foreign keys ON.
  One database file = one deployable runtime. Migrations are plain SQL files
  applied in lexicographic order with a `schema_migrations` table.
- **Core dependencies:** none (standard library only). The demo CLI needs only
  stdlib. A real worker adapter may use the `hermes` CLI as an external process;
  it is optional at runtime and never imported by tests.
- **Process model:** single process, single deployable app. No microservices.
  The three planes (execution / assurance / governance) are package boundaries,
  not services.
- **Testing:** `unittest` from stdlib (no pytest dependency needed).

## Consequences

- Clean-DB migrations must work: every schema change ships as a new migration file.
- SQLite's single-writer model matches MVP concurrency; leases/fencing logic is
  enforced in code above the DB so the semantics survive a move to Postgres.
- If heavy deps are ever required, they enter behind an interface with a new ADR.

## Alternatives considered

- Go/Rust: stronger typing and single-binary deploys, but higher iteration cost
  for this user and no existing code to justify them.
- Postgres from day one: better concurrency, but adds install/config friction for
  a local vertical slice; the SQL is kept portable.
