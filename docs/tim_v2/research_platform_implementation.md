# TIM V2 Research Platform - implementation record

Status: implementation in progress; not accepted or merged.

The Research Platform is an immutable metadata registry for hypotheses,
experiment plans, sessions, planned jobs, artifacts, results and peer reviews.
It references Dataset and Knowledge identities without reading or changing those
platforms. `replay()` deterministically reconstructs a plan manifest only; it
never executes research, calls models, accesses raw data, changes TIM-IM or
creates a trading decision.
