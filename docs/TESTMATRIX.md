# T10: Reproduzierbare Umgebung und Testmatrix

Stand 22.10.2026. Zone B. Nichts hier wird in `~/TIM-live/.venv` installiert.

## 1. Umgebungsstand

- Live: Python 3.13 (Homebrew), Pakete laut `requirements.txt` ohne Sperre. Der Ist-Stand ist nur per
  `~/TIM-live/.venv/bin/pip freeze` auf dem Mac lesbar (T01, offen).
- CI: `pip install -r requirements.txt` plus `coverage`, `pytest-cov`; frische venv je Lauf (`ci.yml`).
- Cloud-Container: Python 3.12, `pip install -r requirements.txt`; Research-Lab- und RAG-Tests laufen (grün, Stand d86baea: 80 Tests der acht Zieldateien in 1,4 s).

## 2. Reproduzierbare Entwicklungsauflösung (Vorschlag, noch nicht im Repo)

```sh
# einmalig, lokal, nie in der Live-venv
uv venv .venv-dev --python 3.13
uv pip compile requirements.txt -o requirements.lock.txt            # Laufzeit
uv pip compile requirements-research.txt -o requirements-research.lock.txt
uv pip sync requirements.lock.txt
```

Regeln: `requirements.txt` bleibt die Quelle der Bereiche (sie ist durch das PR-Gate gesperrt); die `.lock`-Dateien
sind abgeleitet und werden mit dem Datum und dem Python der Erzeugung kommentiert. `pytest`, `pytest-asyncio`
gehören in eine `requirements-dev.txt`, `langchain-ollama`, `langgraph`, `duckduckgo-search` in
`requirements-research.txt`, sobald geprüft ist, dass kein Live-Pfad sie importiert (`llm/ollama_client.py` nutzt
nur `httpx`/Standardbibliothek: zu verifizieren). Die Umstellung der CI auf die Sperrdatei ist ein eigener PR.

## 3. Abdeckung nach Bereichen (statt einer Zahl über `src/`)

**Gemessen 26.10.2026 (Grün-Plan T3), Stand `platform-main` 2fbbe78, Cloud, Python 3.13.17, beide Suite-Teile
(6106 + 245 Tests, `--cov=src`):** Zeilenabdeckung `src/` **89,7 %** (42 827 von 47 762 Zeilen). Niedrigste
Pakete: `orderflow_scenario.execution` 0 %, `control_portal` 59,9 %, `agent_infra` 72,2 %, `research_intelligence`
74,8 %, `llm` 75,5 %, `operational` 78,1 %. Die CI schreibt dieselbe Zahl je Lauf in die Lauf-Zusammenfassung
(Schritt „Coverage summary“); die Bereichswerte unten bleiben die Messlatte, die Gesamtzahl ist nur die Hausnummer.

| Bereich | Pakete | Zielwert | Warum |
|---|---|---|---|
| Ingestion/Persistenz | `data_ingestion`, `database`, `models` | ≥ 90 % Zeilen, Mutationstests auf Cursor, Outbox, Lückenauflösung | hier entsteht die Evidenz |
| Forschung | `research`, `research_lab`, `orderflow`, `insights`, `reflection` | ≥ 85 %, Mutationstests auf Zeitgrenzen (`known_at`, `signalled_in`, `retrospective._known_at`) | Zeitfehler sind die teuersten Fehler |
| KI | `assistant`, `llm` | 100 % der Zitatprüfung, Negativtests | kleine Fläche, hohe Wirkung |
| Betriebswerkzeuge | `operational`, `v2_completion`, `v2_readiness`, `scripts/` | ≥ 70 % | Gates und Belege |
| Gates/Reviews | `v2_completion.independent_cases`, Start-Gates | 100 % der Entscheidungszweige (PASS/PENDING/FAIL) | Freigabelogik |

Umsetzung: `coverage run --source=src.data_ingestion,src.database,…` je Bereich oder `--cov` mit `--cov-report=term`
und einem kleinen Skript, das die Bereichswerte aus `coverage.xml` zieht. Eine hohe Gesamtzahl über 67.000 Zeilen,
von denen 16 % live laufen, bleibt ohne Aussage.

## 4. Mutations-/Gegenproben (gezielt, nicht flächig)

| Invariante | Gegenprobe |
|---|---|
| Walk-Forward sieht keine Zukunft | `test_walk_forward_choice_ignores_outcomes_unknown_at_fit_end` (vorhanden) |
| Retrospektive zählt nur bekannte Ergebnisse | Validierung mit `target_at > as_of` darf nicht zählen (vorhanden in `test_research_retrospective*`? prüfen, sonst ergänzen) |
| Lücken werden nach Erfolg aufgelöst | `resolve_gaps_through` nach Catch-up (vorhanden seit #159/#183, Test prüfen) |
| Outbox-Idempotenz | gleicher `idempotency_key` erzeugt keine zweite Zeile (vorhanden) |
| Hashbindung Tagesbelege | geänderter Inhalt bei gleichem Hash → FAIL (PR #353) |
| Review-Vollständigkeit | leeres Workbook mit `approval=true` → PENDING_OR_FAIL (PR #364) |
| Zitate | unbekannte ID → `rejected_citations` **und** gesamte Antwort verworfen (`test_valid_answer_and_mixed_citations_including_eleventh`, `test_invalid_model_answers_never_preserve_claims`) |
| Wissenszeit RAG | ohne inhaltsgebundenen Verfügbarkeitsbeleg `<= as_of` nicht im Kontext, Filter vor `limit`, Fallrevision braucht neuen Beleg (`test_late_availability_excluded_before_limit_and_unknown_revisions_fail_closed`, `test_case_revision_requires_new_attestation_and_context_is_snapshot`) |

Mutationstest-Werkzeug: `mutmut` auf genau diese Module, einmalig, Ergebnis als Bericht; kein Dauerlauf in CI.

## 5. Langsame Tests

`tests/test_research_lab_guard.py::test_guard_finds_built_in_edge_in_200_series` braucht ~137 s (ein Drittel der
Suite). Vorschlag: Marker `slow`, in CI weiterhin laufen lassen (Pflicht bleibt), lokal per `-m "not slow"`
ausblendbar. Kein Pflichttest verschwindet still; `tim-full-suite.yml` bleibt der manuelle Komplettlauf.

## 6. Abnahme T10

Frische isolierte Umgebung aus der Sperrdatei reproduziert die Suite und die Research-Lab-Berichte (Hashes gleich),
Bereichsabdeckung berichtet, Gegenproben dokumentiert, keine Verbindung zur Produktionsdatenbank
(`tests/conftest.py` verweigert alles außer der Test-DB, bleibt so).
