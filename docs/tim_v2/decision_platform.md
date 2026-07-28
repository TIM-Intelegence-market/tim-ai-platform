# TIM V2 Decision Platform

The Decision Platform is a future evidence-governance layer, not a trading or
order-execution component. V2.0 introduces no decision runtime.

A `DecisionRecord` contains the question/scope, eligible alternatives,
supporting and contradicting evidence, evaluation references, risk constraints,
assumptions, temporal validity, owner/approver identities, policy version,
outcome, rationale, limitations and supersession links. Its status is
`draft`, `reviewed`, `approved`, `rejected`, `expired` or `superseded`.

The platform consumes read-compatible evidence from TIM-IM V1 and future V2
registries. It produces an auditable recommendation or governance decision;
it cannot call Simulation, Paper, Shadow or Execution directly. Any later
promotion remains a separate human, risk and security authorization.
