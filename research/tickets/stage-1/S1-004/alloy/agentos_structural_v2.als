module agentos_structural_v2

/* AgentOS — S1-004 structural property model (Alloy), version v2
 *
 * Ticket:     research/tickets/stage-1/S1-004
 * Sources:    SRC-06 §7 INV1–INV4 (D:/Project/DeepeekHarness/research/
 *             60_mathematical_model.md lines 219–233),
 *             SRC-05 §2 invariants I2–I4 and §3.1/§3.2 lifecycles.
 *
 * v1 correction record (kept as alloy/agentos_structural_v1.als):
 *   v1 had (a) two Alloy syntax/type defects (declaration without `|`
 *     in `no p : PromotionActivity`, `#(p : S | f)` comprehension spelling,
 *     `ka` variable shadowing the PromotionActivity.ka field) and
 *     (b) an inverted command semantics: `check X { NearMiss }` looks for
 *     instances where the near-miss is FALSE, so every check trivially
 *     reported "Counterexample found". v2 encodes the contract as named
 *     predicates and asks the solver the question directly:
 *       - Valid  fixtures:  run  Contract and Fixture        => SAT
 *       - NearMiss fixtures: run Contract and Violation      => UNSAT
 *       - Mutant fixtures:  run Violation (contract relaxed) => SAT
 *     A near-miss UNSAT is only meaningful when the mutant SAT proves the
 *     violation is expressible at all; every near-miss below has a
 *     matching mutant.
 *
 * Properties (bounded, structural):
 *   INV1 identity separation — a principal never participates in two
 *        incompatible identity classes at once;
 *   INV2 single scope — every ContentObject has exactly one scope;
 *   INV3 attenuation — every derived grant satisfies rights <: parent.rights;
 *   INV4 no orphan promotion — a promoted KnowledgeAssertion has >=1 evidence
 *        and exactly one PromotionActivity.
 * All results are bounded by the per-command scopes (3–5 atoms). This is
 * bounded structural validation, not an unbounded proof.
 */

/* ---- entity sorts ---- */

sig Principal, IdentityClass, Scope, Evidence {}

sig ContentObject {
  /* v2: scope is a set so the contract itself (not the declaration)
     enforces "exactly one"; the v1 declaration `one Scope` hid INV2. */
  scopes : set Scope
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

/* ---- schema contract, v2: named predicates, not facts ---- */

pred SingleScopeContract {
  all co : ContentObject | one co.scopes
}

pred IdentitySeparationContract {
  all p : Principal | lone classes[p]
}

pred AttenuationContract {
  all g : Grant | some g.parent implies g.rights in g.parent.rights
}

pred NoOrphanPromotionContract {
  all k : KnowledgeAssertion |
    k.status = KaPromoted implies
      (some k.evidence
       and one p : PromotionActivity | p.ka = k)
}

pred Contract {
  SingleScopeContract
  and IdentitySeparationContract
  and AttenuationContract
  and NoOrphanPromotionContract
}

/* ---- valid fixtures (expect SAT: the contract admits real models) ---- */

pred FixtureDerivedGrantAndPromotion {
  some gParent, gChild : Grant |
    gChild.parent = gParent
    and gChild.rights in gParent.rights
    and some gParent.rights
  some k : KnowledgeAssertion |
    k.status = KaPromoted
    and some k.evidence
  some co : ContentObject | one co.scopes
  some p : Principal | one classes[p]
}

run ValidDerivedGrantAndPromotion {
  Contract and FixtureDerivedGrantAndPromotion
} for 4 but exactly 2 Grant, exactly 2 Right, exactly 1 IdentityMembership

/* lifecycle-consistent fixture: an un-promoted proposal without evidence
   is legal (open shapes must not reject un-promoted assertions) */
pred FixtureProposedWithoutPromotion {
  some k : KnowledgeAssertion |
    k.status = KaProposed and no k.evidence
  no PromotionActivity
}

run ValidProposedWithoutPromotion {
  Contract and FixtureProposedWithoutPromotion
} for 3

/* ---- near-miss fixtures (expect UNSAT under the contract) ---- */

pred ViolateDualIdentity {
  some p : Principal | #classes[p] > 1
}

run NearMissDualIdentity {
  Contract and ViolateDualIdentity
} for 4

pred ViolateTwoScopes {
  some co : ContentObject | #co.scopes > 1
}

run NearMissTwoScopes {
  Contract and ViolateTwoScopes
} for 3

pred ViolateRightsExpansion {
  some g : Grant |
    some g.parent and not g.rights in g.parent.rights
}

run NearMissRightsExpansion {
  Contract and ViolateRightsExpansion
} for 4 but exactly 2 Grant, exactly 2 Right

pred ViolatePromotedWithoutEvidence {
  some k : KnowledgeAssertion |
    k.status = KaPromoted and no k.evidence
}

run NearMissPromotedWithoutEvidence {
  Contract and ViolatePromotedWithoutEvidence
} for 4

pred ViolatePromotedWrongActivityCount {
  some k : KnowledgeAssertion |
    k.status = KaPromoted
    and #{ p : PromotionActivity | p.ka = k } != 1
}

run NearMissPromotedWrongActivityCount {
  Contract and ViolatePromotedWrongActivityCount
} for 4

/* ---- mutants (expect SAT: each near-miss UNSAT is non-vacuous) ---- */

/* relaxing only the INV1 constraint must make the dual identity possible */
run MutantDualIdentity {
  SingleScopeContract and AttenuationContract
  and NoOrphanPromotionContract
  and ViolateDualIdentity
} for 4

/* relaxing only the INV2 constraint must make the double scope possible */
run MutantTwoScopes {
  IdentitySeparationContract and AttenuationContract
  and NoOrphanPromotionContract
  and ViolateTwoScopes
} for 3

/* relaxing only the INV3 constraint must make rights expansion possible */
run MutantRightsExpansion {
  SingleScopeContract and IdentitySeparationContract
  and NoOrphanPromotionContract
  and ViolateRightsExpansion
} for 4 but exactly 2 Grant, exactly 2 Right

/* relaxing only the INV4 constraint must make the orphan promotion possible */
run MutantPromotedWithoutEvidence {
  SingleScopeContract and IdentitySeparationContract
  and AttenuationContract
  and ViolatePromotedWithoutEvidence
} for 4

run MutantPromotedWrongActivityCount {
  SingleScopeContract and IdentitySeparationContract
  and AttenuationContract
  and ViolatePromotedWrongActivityCount
} for 4
