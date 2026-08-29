# S1-004 — Environment and reproduction manifest

Ticket: `research/tickets/stage-1/S1-004` — Alloy/TLA+ and seeded
deterministic invariant simulation. Every executed engine, command, model
and result artifact is recorded here with its SHA-256 so an auditor can
reproduce the evidence byte-for-byte.

## Formal engines (real executions, no imitation)

| Engine | Version | Artifact | SHA-256 | Runtime |
|---|---|---|---|---|
| Alloy | 5.1.0.201908141853 (`org.alloytools.alloy.dist`) | `tools/alloy.jar` | `a3b43e8ec9967947aea2d5101bd96b3c4eb0d81eb3dc9bba41cc9649349c690a` | Java 1.8.0_401 |
| TLC | TLC2 Version 2.15 (rev `eb3ff99`, tla2tools **1.7.0**) | `tools/tla2tools-1.7.0.jar` | `8cce75caa1e59d0b0483bb8fb881ba33825edce8b2d98aba59d66ce685dd3d1a` | Java 1.8.0_401 |

- Runtime: `java version "1.8.0_401"` (Java SE Runtime Environment,
  64-Bit Server VM), Windows 11 10.0 (amd64), host `Daniil`.
- The currently published tla2tools **2.0** build requires Java 11+
  (class file 55) and cannot run on this host; the executed engine is the
  1.7.0 release, which is Java-8 compatible. The download URL and hash of
  the executed jar are pinned above.
- Alloy solver: `sat4j` (pure Java, bundled), selected with `-Dsat4j=yes`.
  SimpleCLI's default solver path (`/zweb/sat/mem`) is broken by design on
  non-MIT infrastructure; `-Dsat4j=yes` avoids it.

### Alloy commands (executed from the ticket directory)

```text
java -Dsat4j=yes -cp tools/alloy.jar edu.mit.csail.sdg.alloy4whole.SimpleCLI alloy/agentos_structural_v2.als
```

- Model: `alloy/agentos_structural_v2.als`
  SHA-256: see `results/formal_summary.json` (`results/alloy/alloy_report.txt`
  header repeats it).
- Report: `results/alloy/alloy_report.txt` (full engine output);
  verdict matrix: `results/alloy/alloy_verdicts.json`.
- Bound note: every command declares its scope (3–5 atoms). Results are
  bounded structural checks, not unbounded proofs. v2 corrected the v1
  inverted `check` semantics (see the v2 header comment and the
  `synthesis_and_gaps` bundle artifact).

### TLC commands (executed inside a scratch directory with copies)

```text
java -cp tools/tla2tools-1.7.0.jar tlc2.TLC -deadlock -config agentos_transitions_v1.cfg agentos_transitions_v1.tla
```

- Spec: `tla/agentos_transitions_v1.tla`; config:
  `tla/agentos_transitions_v1.cfg`.
- Report: `results/tla/tlc_report.txt`; verdict:
  `results/tla/tlc_verdicts.json`.
- State-space bounds: `Grants={g1,g2}`, `Decisions={d1}`, `Alloc=3`,
  `MaxTick=4`, `MaxPub=2` → 271,168 distinct states (903,731 generated),
  exhaustive; 10 invariants + the `LiveDelivery` temporal property under
  weak fairness all hold (`Model checking completed. No error has been
  found.`).
- `-deadlock` rationale: bounded terminal states have no enabled action by
  design; premature parking is ruled out by `LiveDelivery`.

## Deterministic simulator (stdlib-only)

- Module: `simulator/invariant_simulator.py` v1.1.0 — no third-party
  dependencies; deterministic via a single `random.Random(seed)`
  (Mersenne Twister); no wall-clock or dict-order dependence.
- Driver: `simulator/run_acceptance.py` (acceptance + independent rerun),
  `simulator/run_formal.py` (engine orchestration).
- Module hashes at execution time are recorded in
  `results/simulation/manifest.json` (`module_sha256`) — they are the
  authoritative binding between evidence and code.

### Acceptance command (executed from the repository root)

```powershell
$env:PYTHONPATH = "research/tickets/stage-1/S1-004/simulator"
python research/tickets/stage-1/S1-004/simulator/run_acceptance.py `
  --out research/tickets/stage-1/S1-004/results/simulation
```

- Envelope: seeds `11, 22, 33` × 1,000,000 operations, global audit every
  4,096 operations plus a terminal audit.
- Result: **PASS** — zero violations of INV1–INV6, SAF1–SAF4, LIVE1–LIVE2;
  independent rerun reproduced the exact trace digest of every seed
  (`results/simulation/manifest.json`, `runs[*].trace_digest`,
  `reruns[*].digest_match=true`).
- Per-seed artifacts: `results/simulation/seed-<seed>/{config.json,
  result.json, trace_digest.txt}` with their SHA-256 in the manifest.

### Formal driver command

```powershell
python research/tickets/stage-1/S1-004/simulator/run_formal.py `
  --ticket research/tickets/stage-1/S1-004
```

## Fail-closed rules encoded in the runners

- empty operation series → abort (`run_acceptance.py`);
- requested ops below the 1,000,000 acceptance floor → abort;
- missing seed / incomplete invariant counter table / empty trace digest →
  abort;
- engine verdict line missing or unrecognized → abort (`run_formal.py`);
- Alloy expectation matrix (Valid=SAT, NearMiss=UNSAT, Mutant=SAT)
  violated → abort;
- rerun digest mismatch → abort.

## Known environment limitations

- The host has only a Java 8 JRE (no JDK); `javac` is unavailable, so the
  Alloy/TLC drivers shell out instead of compiling Java helpers.
- `SimpleCLI` reports placeholder solve timings (`12345ms`); verdict lines
  are authoritative (documented in the report header).
- TLC progress counters use locale group separators; `run_formal.py`
  normalizes them when extracting the final state counts.
