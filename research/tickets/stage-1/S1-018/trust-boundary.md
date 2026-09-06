# S1-018 trust boundary diagram (Profile-C attested indexer PoC)

Legend: `[X]` trust zone, `-->` data flow with content label, `###` boundary.
Mock quotes carry protocol shape only (`hardware_tee_evidence=NOT_MEASURED`).

```text
CLIENT (authorized member scope S)
  |
  |  plaintext doc/query  (inside S only)
  v
[GATEWAY allow/deny] <--- policy/capability/approval (host-owned)
  |            ^
  | ALLOW      |  audit evidence (atomic)
  v            |
+-------------------------------------------------------------+
| INDEXER SERVICE BOUNDARY (arch B: single; arch C: per       |
| scope/epoch partition; arch A: ABSENT — client only)        |
|                                                             |
|  encrypted objects at rest                                  |
|  decrypt -> index/query -> bind result   (inside boundary)  |
|  attestation: challenge -> evidence -> appraisal -> session |
|  scope/epoch-bound session, exact bindings (PC6)            |
|  revocation/epoch/rollback checks before use (PC7/PC8)      |
+-------------------------------------------------------------+
  |            ^
  | results    |  sealed state (rollback-checked on open)
  v            |
HOST/OS/STORAGE/NETWORK  ### UNTRUSTED ###
  (ciphertext, digests, redacted receipts, counts only;
   NO plaintext/keys/scopes outside S — PC1/PC11)

VERIFIER (host-owned trust anchors, reference values, policy version)
  - appraises evidence -> attestation results (PC4/PC5)
  - NEVER grants access (PC2); Gateway re-checks everything
```

Architectures:
- A CLIENT_SIDE_INDEX_ONLY: no indexer boundary exists server-side;
  plaintext never leaves the client; server stores encrypted objects only.
- B SINGLE_ATTESTED_INDEXER: one boundary as drawn; cross-scope blast
  radius measured per scope pair.
- C SCOPE_EPOCH_SHARDED: one boundary per (scope, epoch) partition;
  revocation/rekey starts a new authoritative generation; old
  sessions/tokens/snapshots cannot read the new generation.

Unknowns (NOT_MEASURED, no default score): physical attacks,
microarchitectural side channels, vendor key compromise, real sealed-storage
rollback guarantees, production topology, any hardware TEE behavior.
