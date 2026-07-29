# TIM — Transparent Intelligence for Markets

TIM provides a local, observation-only BTCUSDT research pipeline: public Binance aggregate trades, deterministic multi-timeframe candle aggregation, TimescaleDB persistence, BOS and Broncx context observations, plus optional explanation-only Ollama summaries.

## Repository governance

TIM is maintained as a standalone repository. Contributions must use a review
branch and a pull request; direct changes to `main` are not permitted. Start
with [CONTRIBUTING.md](CONTRIBUTING.md), report security issues according to
[SECURITY.md](SECURITY.md), and consult
[docs/governance/repository_governance.md](docs/governance/repository_governance.md)
for branch, review, merge, and release rules.

The local repository is authoritative for the current source state. A GitHub
remote has not yet been configured, so no external repository, branch
protection, or hosted integration is claimed.

## Week 2 research layer

- **Observation Engine:** central versioned event layer with stable UUIDs, input hashes, rule IDs, rule versions, provenance, and restart deduplication.
- **Market Memory:** deterministic historical memory with transparent Jaccard feature overlap. Future observations are excluded from similarity results; similarity is not a prediction.
- **Research Cases:** groups observations into fixed 30-minute research containers, records evidence and rule versions, and explicitly lists missing evidence. Outcomes must be documented after the case evidence and cannot be backdated.
- **Human Dashboard V1:** read-only market status, active observations, research cases, missing evidence, system health, memory status, and an explicitly inactive news placeholder. HTML and JSON are available locally at `http://127.0.0.1:8765/` and `/api/state` while TIM is running.

All Week 2 components remain research-only. They contain no trading, prediction, order, account, wallet, or execution path.

## Intelligence V1 modules

- `src/news`: authorized news records and deterministic links to historical observations.
- `src/knowledge`: authorized GoatHub/personal material with searchable citations and hashes.
- `src/longterm`: descriptive macro, dominance and sector context.
- `src/assistant`: OBSERVE-only short-term evidence explanation.
- `src/paper`: disabled-by-default TEST_ONLY research journaling; no exchange interface.
- `docs/VISION_2030.md`: roadmap and governance.
- `docs/VALIDATION_REPORT_2026-07-19.md`: current verification evidence and risks.

## Passive source ingestion

No external source is enabled by default. Configure explicit allowlists and invoke ingestion manually:

```bash
export TIM_ALLOWED_NEWS_HOSTS="example.com,news.example"
export TIM_ALLOWED_KNOWLEDGE_ROOTS="$HOME/Documents/AuthorizedNotes"
.venv/bin/python scripts/passive_ingest.py news /path/to/news.json
.venv/bin/python scripts/passive_ingest.py knowledge /path/to/authorized-note.md
```

The connector is read-only toward source files. It creates content-addressed snapshots under `data/source_snapshots`, suppresses duplicates and only reports retention candidates; it never deletes source material.

## Start

```bash
docker compose up -d
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python main.py --init-schema
```

Configuration uses `TIM_` environment variables defined in `config/settings.py`. Ollama is disabled by default. The service uses no API key, private exchange endpoint, account, wallet, order, or execution path.

Dashboard binding can be changed with `TIM_DASHBOARD_HOST` and `TIM_DASHBOARD_PORT`. Keep the host on `127.0.0.1` unless you explicitly intend to expose the research dashboard to a trusted network.

## Test

```bash
pytest -q
```
# Operational validation, data quality, and benchmarks

TIM includes a restart-safe 72-hour OBSERVE validator, deterministic batch data
quality reports, and a permanent five-case research benchmark. See
`docs/OPERATIONAL_VALIDATION.md`, `docs/DATA_QUALITY.md`, and
`docs/BENCHMARKS.md` for operation and guarantees.
