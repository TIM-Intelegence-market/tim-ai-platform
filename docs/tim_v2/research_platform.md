# TIM V2 Research Platform

The Research Platform manages scientific work; it does not execute a study in
V2.0. Its canonical objects are `Hypothesis`, `ResearchNote`, `Paper`,
`LiteratureSource`, `ExperimentPlan`, `ExperimentResult`, `StatisticalFinding`,
`PeerReview` and `OpenQuestion`.

Every insight records evidence references, source identity, trust class,
status (`draft`, `reviewed`, `supported`, `refuted`, `inconclusive`,
`superseded`), confidence, author/reviewer, temporal validity and links to the
dataset, configuration and code identity. Negative results and limitations are
first-class artifacts.

| Lifecycle | Required evidence | Gate |
|---|---|---|
| Propose | hypothesis, rationale, owner, source links | no claim of truth |
| Plan | dataset identity, method, parameters, metrics, leakage plan | reviewable plan |
| Run (future) | immutable manifest, code/config/environment IDs, artifacts | reproducibility check |
| Review | statistical method, limitations, peer review | independent review |
| Publish | evidence-backed claim and relationship links | knowledge validation |

Research never writes to TIM-IM V1, changes historical results or turns a
finding into a trading decision. Reproduction is a separate run with a new
result record linked to—not replacing—the original.
