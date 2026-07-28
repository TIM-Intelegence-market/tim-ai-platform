# TIM V2 Evaluation Platform

The Evaluation Platform specifies reproducible gates for future candidates; it
does not run evaluations in V2.0.

Required evaluation-plan fields are candidate/version, hypothesis, dataset and
split manifests, event-time policy, metric definitions, benchmark, random seed
policy, cost assumptions, robustness plan, limitations and promotion rule.

| Method | Purpose | Minimum guard |
|---|---|---|
| Walk-forward / rolling validation | temporal generalization | embargo and non-overlap |
| Cross validation | controlled comparison | split provenance |
| Monte Carlo | uncertainty and path sensitivity | seed/manifests |
| Stability / sensitivity | parameter robustness | predeclared ranges |
| Bias / overfitting detection | invalid inference detection | independent holdout |
| Benchmarking | contextual performance | immutable baseline |

An evaluation package retains all failures, exclusions and inconclusive runs.
It may create an evidence-backed recommendation but cannot promote or execute
anything; Risk and Governance make the next independent decision.
