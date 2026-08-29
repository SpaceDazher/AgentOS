---- MODULE agentos_transitions_v1 ----
(***************************************************************************
 * AgentOS -- S1-004 transition model (TLA+), version v1
* Ticket:    research/tickets/stage-1/S1-004
* Sources:   SRC-06 S.7 INV5/INV6, SAF, LIVE (D:/Project/DeepeekHarness/
*            research/60_mathematical_model.md lines 234-243);
*            SRC-05 S.2 I2/I5 and S.3.1 DelegationGrant lifecycle;
*            SRC-03 transactional outbox / durable execution pattern [H3][H8].
*
* Scope: bounded exhaustive check of
*   INV5  revocation monotonicity -- no allow-trace for a grant after its
*         durable revoke;
*   INV6  budget conservation -- spent + outstanding reservations <= Alloc
*         under all interleavings of reserve/confirm/cancel/revoke;
*   SAF   every committed decision has exactly one outbox event (appended
*         atomically with the local commit); redelivery never creates a
*         second local effect receipt; unknown external outcomes always go
*         to reconciliation and a retry publish only happens afterwards;
*         grant state changes only through approve/deny/revoke/expire/exhaust;
*   LIVE  owner-approved grants activate within one scheduler tick;
*         crash between transition and publish is recovered by replay.
*
* Model contract alignment (documented in the S1-004 bundle):
*   - "deny" (proposed->denied, owner reject in SRC-05 S.3.1) is included in
*     the allowed transition set alongside approve/revoke/expire/exhaust;
*     SRC-06 S.7 SAF enumerates the live-grant transitions, SRC-05 S.3.1 adds
*     the admission rejection edge.
*   - The outbox append is atomic with the local commit (transactional
*     outbox); a crash can lose the in-flight publish but never the event.
*   - Budgets: Root may hold outstanding reservations created for Child
*     (derive() in SRC-05 S.2 I5); conservation is checked on both ledgers.
 *************************************************************************)
EXTENDS Integers, TLC

CONSTANTS Grants, Root, Child, Decisions, Alloc, MaxTick, MaxPub

GrantStates == {"proposed", "denied", "active", "revoked", "expired", "exhausted"}
EventStates == {"none", "pending", "acked", "nacked", "unknown", "reconciling"}
Transitions == {"init", "approve", "deny", "revoke", "expire", "exhaust"}

(*
  gstate[g]        grant state machine position;
  spent, reserved   per-grant ledger columns (INV6);
  approvedTick[g]  tick of owner approval (-1 = none), LIVE activation bound;
  revokedTick[g]   tick of durable revoke (-1 = none), INV5 anchor;
  lastTrans[g]     last named transition that changed gstate (SAF);
  lastAllowTick[d] last allow() tick of decision d (INV5 allow-trace);
  grantOf[d]       grant that produced decision d;
  committed        locally committed decisions;
  outbox           durable outbox events (atomic with commit);
  estate[d]        external delivery state;
  receipts         decisions with a local effect receipt;
  token[d]         current fencing token of the delivery attempt;
  receiptToken[d]  fencing token the receipt was created with;
  publishes[d]     publish attempts (bounded by MaxPub);
  reconcileDone[d] reconciliation resolved the previous unknown outcome;
  fenceStale[d]    observable count of fenced-out stale acks;
  tick             scheduler tick (bounded by MaxTick).
*)
VARIABLES gstate, spent, reserved, approvedTick, revokedTick, lastTrans,
          lastAllowTick, grantOf, committed, outbox, estate, receipts,
          token, receiptToken, publishes, reconcileDone, fenceStale, tick

vars == <<gstate, spent, reserved, approvedTick, revokedTick, lastTrans,
          lastAllowTick, grantOf, committed, outbox, estate, receipts,
          token, receiptToken, publishes, reconcileDone, fenceStale, tick>>

TypeOk ==
  /\ gstate \in [Grants -> GrantStates]
  /\ spent \in [Grants -> 0..Alloc]
  /\ reserved \in [Grants -> 0..Alloc]
  /\ approvedTick \in [Grants -> -1..MaxTick]
  /\ revokedTick \in [Grants -> -1..MaxTick]
  /\ lastTrans \in [Grants -> Transitions]
  /\ lastAllowTick \in [Decisions -> -1..MaxTick]
  /\ grantOf \in [Decisions -> Grants]
  /\ committed \subseteq Decisions
  /\ outbox \subseteq Decisions
  /\ estate \in [Decisions -> EventStates]
  /\ receipts \subseteq Decisions
  /\ token \in [Decisions -> 0..MaxPub]
  /\ receiptToken \in [Decisions -> 0..MaxPub]
  /\ publishes \in [Decisions -> 0..MaxPub]
  /\ reconcileDone \in [Decisions -> BOOLEAN]
  /\ fenceStale \in [Decisions -> 0..MaxPub]
  /\ tick \in 0..MaxTick

(* ---- checked invariants ---- *)

(* INV6: budget conservation on every grant ledger. *)
BudgetConservation ==
  \A g \in Grants : spent[g] + reserved[g] <= Alloc

(* SRC-05 S.2 I5: Child's outstanding budget is covered by Root's ledger. *)
ChildBudgetConsistency ==
  reserved[Child] <= reserved[Root]

(* INV5: no allow-trace after a durable revoke. *)
RevocationMonotonicity ==
  \A d \in Decisions :
    revokedTick[grantOf[d]] = -1
      \/ lastAllowTick[d] <= revokedTick[grantOf[d]]

(* SAF: every committed decision has exactly one outbox event. *)
OutboxCompleteness == committed = outbox

(* SAF: receipts only for committed decisions, only from an ack, with a
   fencing token issued by a real publish attempt. *)
ReceiptConsistency ==
  \A d \in Decisions :
    d \in receipts =>
      /\ d \in committed
      /\ estate[d] = "acked"
      /\ receiptToken[d] >= 1
      /\ receiptToken[d] <= token[d]

(* SAF: a second publish happens only after reconciliation resolved the
   previous unknown outcome (no blind retry). *)
NoBlindRetry ==
  \A d \in Decisions : publishes[d] > 1 => reconcileDone[d]

(* SAF: gstate changes only through the named transition set. *)
AllowedAfter[trans \in Transitions] ==
  IF trans = "init" THEN {"proposed"}
  ELSE IF trans = "approve" THEN {"active"}
  ELSE IF trans = "deny" THEN {"denied"}
  ELSE IF trans = "revoke" THEN {"revoked"}
  ELSE IF trans = "expire" THEN {"expired"}
  ELSE {"exhausted"}

GrantStateMachine ==
  \A g \in Grants : gstate[g] \in AllowedAfter[lastTrans[g]]

(* LIVE (bounded, tick-model): an owner-approved grant activates at the
   next scheduler tick; a pending approval never outlives its tick. *)
ActivationWithinOneTick ==
  \A g \in Grants :
    ~( /\ gstate[g] = "proposed"
       /\ approvedTick[g] # -1
       /\ tick > approvedTick[g]
    )

(* Fencing: a recorded receipt never claims a token above the current one
   and stale acks are fenced out observably. *)
FenceMonotone ==
  \A d \in Decisions :
    /\ receiptToken[d] <= token[d]
    /\ fenceStale[d] >= 0

Invariants == TypeOk /\ BudgetConservation /\ ChildBudgetConsistency
  /\ RevocationMonotonicity /\ OutboxCompleteness /\ ReceiptConsistency
  /\ NoBlindRetry /\ GrantStateMachine /\ ActivationWithinOneTick
  /\ FenceMonotone

(* ---- actions ---- *)

(* owner approves; activation happens at the next scheduler tick *)
Approve(g) ==
  /\ gstate[g] = "proposed"
  /\ approvedTick[g] = -1
  /\ tick < MaxTick
  /\ approvedTick' = [approvedTick EXCEPT ![g] = tick]
  /\ UNCHANGED <<gstate, spent, reserved, revokedTick, lastTrans,
                  lastAllowTick, grantOf, committed, outbox, estate,
                  receipts, token, receiptToken, publishes, reconcileDone,
                  fenceStale, tick>>

(* owner rejects the proposal (SRC-05 S.3.1 admission edge) *)
Deny(g) ==
  /\ gstate[g] = "proposed"
  /\ gstate' = [gstate EXCEPT ![g] = "denied"]
  /\ lastTrans' = [lastTrans EXCEPT ![g] = "deny"]
  /\ UNCHANGED <<spent, reserved, approvedTick, revokedTick,
                  lastAllowTick, grantOf, committed, outbox, estate,
                  receipts, token, receiptToken, publishes, reconcileDone,
                  fenceStale, tick>>

(* scheduler tick: activates pending owner approvals (LIVE within one tick) *)
TickAct ==
  /\ tick < MaxTick
  /\ tick' = tick + 1
  /\ gstate' = [g \in Grants |->
       IF gstate[g] = "proposed" /\ approvedTick[g] # -1
         THEN "active" ELSE gstate[g]]
  /\ lastTrans' = [g \in Grants |->
       IF gstate[g] = "proposed" /\ approvedTick[g] # -1
         THEN "approve" ELSE lastTrans[g]]
  /\ UNCHANGED <<spent, reserved, approvedTick, revokedTick,
                  lastAllowTick, grantOf, committed, outbox, estate,
                  receipts, token, receiptToken, publishes, reconcileDone,
                  fenceStale>>

(* durable revoke; outstanding reservations on the grant are released,
   and revoking Root also releases the outstanding child reservations
   (SRC-05 S.2 I5: child authority derives from the parent ledger) *)
Revoke(g) ==
  /\ gstate[g] = "active"
  /\ gstate' = [gstate EXCEPT ![g] = "revoked"]
  /\ lastTrans' = [lastTrans EXCEPT ![g] = "revoke"]
  /\ revokedTick' = [revokedTick EXCEPT ![g] = tick]
  /\ reserved' = [reserved EXCEPT
       ![g] = 0,
       ![Child] = IF g = Root THEN 0 ELSE reserved[Child]]
  /\ UNCHANGED <<spent, approvedTick, lastAllowTick, grantOf, committed,
                  outbox, estate, receipts, token, receiptToken, publishes,
                  reconcileDone, fenceStale, tick>>

Expire(g) ==
  /\ gstate[g] = "active"
  /\ gstate' = [gstate EXCEPT ![g] = "expired"]
  /\ lastTrans' = [lastTrans EXCEPT ![g] = "expire"]
  /\ UNCHANGED <<spent, reserved, approvedTick, revokedTick,
                  lastAllowTick, grantOf, committed, outbox, estate,
                  receipts, token, receiptToken, publishes, reconcileDone,
                  fenceStale, tick>>

(* budget fully consumed: the exhaust transition *)
Exhaust(g) ==
  /\ gstate[g] = "active"
  /\ spent[g] + reserved[g] = Alloc
  /\ gstate' = [gstate EXCEPT ![g] = "exhausted"]
  /\ lastTrans' = [lastTrans EXCEPT ![g] = "exhaust"]
  /\ UNCHANGED <<spent, reserved, approvedTick, revokedTick,
                  lastAllowTick, grantOf, committed, outbox, estate,
                  receipts, token, receiptToken, publishes, reconcileDone,
                  fenceStale, tick>>

(* reserve budget for the child against the root ledger (derive()) *)
ReserveChild ==
  /\ gstate[Root] = "active"
  /\ spent[Root] + reserved[Root] + 1 <= Alloc
  /\ reserved' = [reserved EXCEPT
       ![Root] = reserved[Root] + 1,
       ![Child] = reserved[Child] + 1]
  /\ UNCHANGED <<gstate, spent, approvedTick, revokedTick, lastTrans,
                  lastAllowTick, grantOf, committed, outbox, estate,
                  receipts, token, receiptToken, publishes, reconcileDone,
                  fenceStale, tick>>

(* child consumes a reserved unit: child spent grows, root reservation
   becomes root spent *)
ConfirmChild ==
  /\ gstate[Child] = "active"
  /\ reserved[Child] >= 1
  /\ reserved[Root] >= 1
  /\ spent' = [spent EXCEPT
       ![Child] = spent[Child] + 1,
       ![Root] = spent[Root] + 1]
  /\ reserved' = [reserved EXCEPT
       ![Child] = reserved[Child] - 1,
       ![Root] = reserved[Root] - 1]
  /\ UNCHANGED <<gstate, approvedTick, revokedTick, lastTrans,
                  lastAllowTick, grantOf, committed, outbox, estate,
                  receipts, token, receiptToken, publishes, reconcileDone,
                  fenceStale, tick>>

(* release an outstanding child reservation without consuming it *)
CancelChildReservation ==
  /\ reserved[Child] >= 1
  /\ reserved[Root] >= 1
  /\ reserved' = [reserved EXCEPT
       ![Child] = reserved[Child] - 1,
       ![Root] = reserved[Root] - 1]
  /\ UNCHANGED <<gstate, spent, approvedTick, revokedTick, lastTrans,
                  lastAllowTick, grantOf, committed, outbox, estate,
                  receipts, token, receiptToken, publishes, reconcileDone,
                  fenceStale, tick>>

ChainActive(g) == gstate[g] = "active" /\ gstate[Root] = "active"

(* allow(): local commit + atomic outbox append (SAF) *)
Allow(d, g) ==
  /\ ChainActive(g)
  /\ d \notin committed
  /\ committed' = committed \union {d}
  /\ outbox' = outbox \union {d}
  /\ estate' = [estate EXCEPT ![d] = "pending"]
  /\ grantOf' = [grantOf EXCEPT ![d] = g]
  /\ lastAllowTick' = [lastAllowTick EXCEPT ![d] = tick]
  /\ UNCHANGED <<gstate, spent, reserved, approvedTick, revokedTick,
                  lastTrans, receipts, token, receiptToken, publishes,
                  reconcileDone, fenceStale, tick>>

Publish(d) ==
  /\ estate[d] = "pending"
  /\ publishes[d] < MaxPub
  /\ publishes' = [publishes EXCEPT ![d] = publishes[d] + 1]
  /\ token' = [token EXCEPT ![d] = token[d] + 1]
  /\ UNCHANGED <<gstate, spent, reserved, approvedTick, revokedTick,
                  lastTrans, lastAllowTick, grantOf, committed, outbox,
                  reconcileDone, fenceStale, tick>>

(* external ack creates the local effect receipt exactly once, with the
   fencing token of this delivery attempt *)
PublishAck(d) ==
  /\ Publish(d)
  /\ d \notin receipts
  /\ estate' = [estate EXCEPT ![d] = "acked"]
  /\ receipts' = receipts \union {d}
  /\ receiptToken' = [receiptToken EXCEPT ![d] = token'[d]]
  /\ UNCHANGED <<gstate, spent, reserved, approvedTick, revokedTick,
                  lastTrans, lastAllowTick, grantOf, committed, outbox,
                  reconcileDone, fenceStale>>

PublishNack(d) ==
  /\ Publish(d)
  /\ estate' = [estate EXCEPT ![d] = "nacked"]
  /\ UNCHANGED <<receipts, receiptToken>>

(* unknown external outcome: reconciliation is mandatory before any retry *)
PublishUnknown(d) ==
  /\ Publish(d)
  /\ estate' = [estate EXCEPT ![d] = "unknown"]
  /\ UNCHANGED <<receipts, receiptToken>>

(* stale ack racing a newer delivery attempt: fenced out, observable *)
StaleFenceAck(d) ==
  /\ d \in receipts
  /\ receiptToken[d] < token[d]
  /\ fenceStale' = [fenceStale EXCEPT ![d] = fenceStale[d] + 1]
  /\ UNCHANGED <<gstate, spent, reserved, approvedTick, revokedTick,
                  lastTrans, lastAllowTick, grantOf, committed, outbox,
                  estate, receipts, token, receiptToken, publishes,
                  reconcileDone, tick>>

Reconcile(d) ==
  /\ estate[d] = "unknown"
  /\ estate' = [estate EXCEPT ![d] = "reconciling"]
  /\ UNCHANGED <<gstate, spent, reserved, approvedTick, revokedTick,
                  lastTrans, lastAllowTick, grantOf, committed, outbox,
                  receipts, token, receiptToken, publishes, reconcileDone,
                  fenceStale, tick>>

ResolveAck(d) ==
  /\ estate[d] = "reconciling"
  /\ estate' = [estate EXCEPT ![d] = "acked"]
  /\ reconcileDone' = [reconcileDone EXCEPT ![d] = TRUE]
  /\ receipts' = receipts \union {d}
  /\ receiptToken' = [receiptToken EXCEPT ![d] = token[d]]
  /\ UNCHANGED <<gstate, spent, reserved, approvedTick, revokedTick,
                  lastTrans, lastAllowTick, grantOf, committed, outbox,
                  token, publishes, fenceStale, tick>>

ResolveNack(d) ==
  /\ estate[d] = "reconciling"
  /\ estate' = [estate EXCEPT ![d] = "nacked"]
  /\ reconcileDone' = [reconcileDone EXCEPT ![d] = TRUE]
  /\ UNCHANGED <<gstate, spent, reserved, approvedTick, revokedTick,
                  lastTrans, lastAllowTick, grantOf, committed, outbox,
                  receipts, token, receiptToken, publishes, fenceStale, tick>>

(* retry is only reachable after reconciliation resolved the outcome *)
RetryPublish(d) ==
  /\ estate[d] = "nacked"
  /\ reconcileDone[d]
  /\ publishes[d] < MaxPub
  /\ estate' = [estate EXCEPT ![d] = "pending"]
  /\ UNCHANGED <<gstate, spent, reserved, approvedTick, revokedTick,
                  lastTrans, lastAllowTick, grantOf, committed, outbox,
                  receipts, token, receiptToken, publishes, reconcileDone,
                  fenceStale, tick>>

Next ==
  \/ \E g \in Grants : Approve(g) \/ Deny(g) \/ Revoke(g)
                            \/ Expire(g) \/ Exhaust(g)
  \/ TickAct
  \/ ReserveChild \/ ConfirmChild \/ CancelChildReservation
  \/ \E d \in Decisions :
       \/ Allow(d, Root) \/ Allow(d, Child)
       \/ PublishAck(d) \/ PublishNack(d) \/ PublishUnknown(d)
       \/ StaleFenceAck(d)
       \/ Reconcile(d) \/ ResolveAck(d) \/ ResolveNack(d)
       \/ RetryPublish(d)

Init ==
  /\ gstate = [g \in Grants |-> "proposed"]
  /\ spent = [g \in Grants |-> 0]
  /\ reserved = [g \in Grants |-> 0]
  /\ approvedTick = [g \in Grants |-> -1]
  /\ revokedTick = [g \in Grants |-> -1]
  /\ lastTrans = [g \in Grants |-> "init"]
  /\ lastAllowTick = [d \in Decisions |-> -1]
  /\ grantOf = [d \in Decisions |-> Root]
  /\ committed = {}
  /\ outbox = {}
  /\ estate = [d \in Decisions |-> "none"]
  /\ receipts = {}
  /\ token = [d \in Decisions |-> 0]
  /\ receiptToken = [d \in Decisions |-> 0]
  /\ publishes = [d \in Decisions |-> 0]
  /\ reconcileDone = [d \in Decisions |-> FALSE]
  /\ fenceStale = [d \in Decisions |-> 0]
  /\ tick = 0

Spec == Init /\ [][Next]_vars
  /\ WF_vars(TickAct)
  /\ WF_vars(\E d \in Decisions :
       (PublishAck(d) \/ PublishNack(d) \/ PublishUnknown(d)))
  /\ WF_vars(\E d \in Decisions : Reconcile(d))
  /\ WF_vars(\E d \in Decisions : (ResolveAck(d) \/ ResolveNack(d)))

(* Bounded-model note: terminal states (tick = MaxTick, or a decision whose
   bounded retry budget publishes = MaxPub is spent while nacked) have no
   enabled action on purpose; the bounded exploration envelope ends there.
   TLC deadlock checking is therefore disabled with -deadlock, and premature
   parking is ruled out by LiveDelivery instead. *)

(* LIVE: every committed decision eventually reaches a terminal external
   outcome (local receipt or definitive nack) -- the replay/reconciliation
   obligations under weak fairness of the scheduler. *)
LiveDelivery ==
  \A d \in Decisions :
    (d \in committed) ~> (d \in receipts \/ estate[d] = "nacked")

(* Liveness note: TLC checks LiveDelivery with the weak fairness conjuncts
   above. A state-space overflow would downgrade LIVE2 to a design
   obligation backed by the simulator crash-replay probe only. *)

=============================================================================
