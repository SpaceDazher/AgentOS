module agentos_structural_v1

/* AgentOS — S1-004 structural property model (Alloy), version v1
 *
 * Ticket:     research/tickets/stage-1/S1-004 (bundle artifact input)
 * Source:     SRC-06 §7 INV1–INV4
 *             (D:/Project/DeepeekHarness/research/60_mathematical_model.md,
 *              lines 230–233), SRC-05 ontology classes.
 * Properties (bounded, structural):
 *   INV1 identity separation — a principal never participates in two
 *        incompatible identity classes at once;
 *   INV2 single scope — every ContentObject has exactly one locatedIn scope;
 *   INV3 attenuation — every derived grant satisfies rights ⊑ parent.rights;
 *   INV4 no orphan promotion — a promoted KnowledgeAssertion has >=1 evidence
 *        and exactly one PromotionActivity.
 * Method: the schema contract is encoded as facts; valid fixtures must be
 *   satisfiable (run => SAT, non-vacuity), near-miss fixtures must be
 *   unsatisfiable (check => no counterexample). This is bounded structural
 *   validation, not unbounded proof. Bounded scopes are declared per command.
 */

/* ---- entity sorts ---- */

sig Principal {}
sig IdentityClass {}
sig Scope {}
sig Evidence {}

sig ContentObject {
  locatedIn : one Scope
}

abstract sig KaStatus {}
one sig KaProposed, KaPromoted, KaRejected, KaSuperseded, KaRevoked
  extends KaStatus {}

sig KnowledgeAssertion {
  status   : one KaStatus,
  evidence : set Evidence
}

sig PromotionActivity {
  ka : one KnowledgeAssertion
}

sig Right {}

sig Grant {
  parent : lone Grant,
  rights : set Right
}

/* identity class participation (INV1 domain) */
sig IdentityMembership {
  principal : one Principal,
  cls       : one IdentityClass
}

fun classes[p : Principal] : set IdentityClass {
  { c : IdentityClass |
    some m : IdentityMembership | m.principal = p and m.cls = c }
}

/* ---- schema contract (facts) ---- */

/* INV2 — single scope: locatedIn is functional by declaration; the fact
   below restates it explicitly so the contract is auditable as a fact. */
fact SingleScopeFact {
  all co : ContentObject | one co.locatedIn
}

/* INV1 — identity separation: class participation is a partial function
   from principals to classes; two memberships of one principal must agree,
   so a principal never occupies incompatible classes simultaneously. */
fact IdentitySeparationFact {
  all p : Principal | lone classes[p]
}

/* INV3 — attenuation: a derived grant never expands beyond its parent. */
fact AttenuationFact {
  all g : Grant | some g.parent implies g.rights in g.parent.rights
}

/* INV4 — no orphan promotion: promotion requires at least one evidence and
   exactly one PromotionActivity. */
fact NoOrphanPromotionFact {
  all k : KnowledgeAssertion |
    k.status = KaPromoted implies
      (some k.evidence
       and one p : PromotionActivity | p.ka = k)
}

/* ---- valid fixtures (must be SAT: contract is not vacuous) ---- */

pred ValidDerivedGrantAndPromotion() {
  some gParent, gChild : Grant |
    gChild.parent = gParent
    and gChild.rights in gParent.rights      /* attenuation holds */
    and some gParent.rights
  some ka : KnowledgeAssertion |
    ka.status = KaPromoted
    and some ka.evidence
  some co : ContentObject | one co.locatedIn
  some p : Principal | some classes[p]
}

run ValidDerivedGrantAndPromotion
  for 4 but exactly 2 Grant, exactly 2 Right, exactly 1 IdentityMembership

/* a lifecycle-consistent fixture: proposed without promotion evidence must
   remain legal (open shapes must not reject un-promoted assertions) */
pred ValidProposedWithoutPromotion() {
  some ka : KnowledgeAssertion |
    ka.status = KaProposed and no ka.evidence
  no PromotionActivity
}
run ValidProposedWithoutPromotion for 3

/* ---- near-miss fixtures (must be UNSAT: check finds no counterexample) ---- */

/* INV1 near-miss: one principal in two different identity classes */
pred NearMissDualIdentity() {
  some p : Principal | #classes[p] > 1
}
check NearMissDualIdentityIsImpossible { NearMissDualIdentity } for 4

/* INV2 near-miss: a ContentObject with more than one scope */
pred NearMissTwoScopes() {
  some co : ContentObject | #co.locatedIn > 1
}
check NearMissTwoScopesIsImpossible { NearMissTwoScopes } for 3

/* INV3 near-miss: a derived grant with a right outside the parent grant */
pred NearMissRightsExpansion() {
  some g : Grant |
    some g.parent and not g.rights in g.parent.rights
}
check NearMissRightsExpansionIsImpossible { NearMissRightsExpansion } for 4

/* INV4 near-miss A: promoted with zero evidence */
pred NearMissPromotedWithoutEvidence() {
  some ka : KnowledgeAssertion |
    ka.status = KaPromoted and no ka.evidence
}
check NearMissPromotedWithoutEvidenceIsImpossible {
  NearMissPromotedWithoutEvidence } for 4

/* INV4 near-miss B: promoted with zero or >=2 PromotionActivities */
pred NearMissPromotedWrongActivityCount() {
  some k : KnowledgeAssertion |
    k.status = KaPromoted
    and #{ p : PromotionActivity | p.ka = k } != 1
}
check NearMissPromotedWrongActivityCountIsImpossible {
  NearMissPromotedWrongActivityCount } for 4
