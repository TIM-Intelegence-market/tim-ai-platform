# Qualification campaign status

Status: **NOT STARTED — POSTGRESQL SECURITY START GATE FAILED**

| Field | Value |
|---|---|
| Dataset | `V2_PROSPECTIVE_QUALIFICATION_V1` |
| Start UTC | not assigned |
| Expected end UTC | not assigned |
| Prospective coverage | not applicable / 0 collected campaign minutes |
| Prospective independent units | 0 |
| Daily manifests | 0 |
| Retrospective start allowed | no |
| Minimum duration after valid activation | 34 complete UTC days |
| Human approval | absent |

No time evidence is claimed. The monitor was executed once and correctly
refused to write a daily manifest while the start gate was blocked.

The primary blocker owner is an **authorized PostgreSQL administrator**. That
person must apply the idempotent hardening bundle, rotate the TIM database
credential through the approved secret flow, restart PostgreSQL safely, and
produce localhost-success/LAN-refusal/HBA evidence. The **TIM release owner**
must then rerun the full acceptance, freeze the implementation commit and
explicitly activate the pre-registration. Neither role is simulated by Codex.
