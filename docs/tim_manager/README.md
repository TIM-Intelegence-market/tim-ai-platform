# TIM Intelligence Manager

TIM-IM is an isolated, local-first and read-only project intelligence subsystem.
It scans evidence from the TIM repository, records source provenance, builds a
canonical management snapshot and exposes grounded read-only queries.

It does not modify TIM V1 scientific data, trigger trading, call exchanges or
require an external language model.

## Quick start

```bash
.venv/bin/python -m src.tim_manager.cli doctor
.venv/bin/python -m src.tim_manager.cli scan
.venv/bin/python -m src.tim_manager.cli status
.venv/bin/python -m src.tim_manager.cli query "How is Orderflow?"
```

Canonical outputs live exclusively under `artifacts/tim_manager/`.
