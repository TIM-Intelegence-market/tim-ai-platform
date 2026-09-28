# Manual scientific review packet

Status: **MACHINE WORK COMPLETE — HUMAN APPROVAL PENDING**

This packet is ready for real reviewers but contains no simulated review,
signature or approval. Its structured workbook is
`artifacts/v2_completion/manual_review_workbook.json`; the prior deterministic
selection manifest and exact replay evidence remain in
`artifacts/v2_readiness/manual_review_sample_manifest.json` and
`artifacts/v2_readiness/scientific_replay_run_1.json`.

## Packet contents

- full Frozen audit chain: 1,339 → 910 → 378 → 14;
- current completion-cut audit: 22,225 → 19,998 → 8,620 → 298;
- canonical independent-unit definition and sampling restrictions;
- 24 deterministic observation-kind × outcome replay strata;
- source-window, observation/case, input and validation identities per sample;
- blank human decision fields;
- inter-rater conflict and resolution fields;
- explicit unsigned approval state.

## Reviewer procedure

Two named scientific reviewers independently inspect each selected case and
record all of the following:

1. reviewer ID and review timestamp;
2. source data quality;
3. whether the observation is correct;
4. whether the persisted label is correct;
5. whether future information is absent;
6. whether narrative adjustment is absent;
7. confidence from 0 to 1;
8. accept, reject or exclude decision;
9. exclusion reason when applicable;
10. evidence-based rationale;
11. inter-rater conflict status;
12. conflict resolution when a conflict exists.

A partially populated decision is invalid. Reviewers must not change the
sample, source evidence, hashes or automated audit. Any replacement requires a
new deterministic selection manifest with an explicit exclusion trail.

## Approval

Current human decisions: **0 / 24**.

Reviewer signature: **absent**.

Release authority signature: **absent**.

Human approval: **false**.

Even a completed review of this 24-case diagnostic sample cannot substitute
for the prospective gate of 1,000 valid independent units with negative and
neutral controls. Final scientific approval must bind the completed
qualification dataset, its daily manifests, replay/leakage/look-ahead results,
inter-rater reconciliation and release decision.
