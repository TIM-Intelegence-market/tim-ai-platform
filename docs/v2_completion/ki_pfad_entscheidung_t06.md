# T06: Ein nachvollziehbarer KI-Pfad (Entscheidungsvorlage und Stand)

Stand 22.10.2026, platform-main `e985971` plus Branch `claude/project-thread-shxgzj`.

## 1. Tatsächlicher Einstiegspunkt der Nutzerfrage

| Pfad | Einstieg | Antwort | Stand |
|---|---|---|---|
| Runtime (`main.py`) | keine Nutzerfrage; Ollama in der Runtime aus (`TIM_ENABLE_OLLAMA=false`) | – | live, ohne KI |
| Control Center / Dashboard (`src/dashboard`) | liest Beobachtungen, Fälle, Validierungen, Retrospektive | deterministische Anzeige, kein Sprachmodell | live |
| `src/assistant/rag_qwen.py` (`RAGQwenAssistant`) | von keinem Modul, Skript oder Dienst importiert (Paketinventar: `assistant` 129 Zeilen, 92 unerreicht) | Qwen über Ollama/OmniRoute | **Experiment, nicht Teil des Produkts** |
| `src/local_first` (Qwen-Issue-Worker) | GitHub-Issues, nicht Nutzerfragen | Code-PRs | Werkzeug, nicht Produktpfad |

**Entscheidung (Vorschlag, nach Plan Abschnitt 1 Punkt 2):** Der freigegebene V2-Produktpfad enthält
keine KI-Antwort auf Nutzerfragen. `RAGQwenAssistant` bleibt als Experiment im Repo, trägt die
Kennzeichnung EXPERIMENTAL im Modul-Docstring und wird nur über den Benchmark aus T07 in das Produkt
aufgenommen. Bis dahin ist jede Aussage „TIM beantwortet Marktfragen mit KI“ unzulässig.

## 2. Reproduzierte Fehler und ihre Behebung (Codex F02–F04)

| Befund | Vorher | Jetzt |
|---|---|---|
| Join Fälle ↔ ähnliche Beobachtungen | `any(str(o.observation_id) in [ids der ähnlichen] for o in [anchor])` prüfte, ob die **Anker**-ID unter den ähnlichen ist (immer falsch: `similar` schließt den Anker aus). Ergebnis: nie ein Fall. | Join über die IDs der ähnlichen Beobachtungen gegen `case.observation_ids`, Filter auf Symbol des Ankers |
| Wissenszeit | kein Stichtag; `latest cases` nahm die letzten drei Fälle unabhängig von der Zeit | `as_of` (Pflicht tz-aware), Standard = Zeit des Ankers; Beobachtungen und Fälle nach `as_of` ausgeschlossen |
| „letzte Fälle“ als Ähnlichkeit ausgegeben | kein Hinweis | `mode = latest_cases` im Kontext und im Prompt; Jaccard über Feldnamen bleibt Baseline, kein Marktähnlichkeitsmodell |
| Zitate | Modell-Zitate ungeprüft übernommen; bei Modellfehler wurden Zitate aus dem Kontext „erfunden“ | nur IDs aus dem Kontext bleiben, Rest in `rejected_citations`; ohne gültiges Zitat Enthaltung; bei Modellfehler keine Zitate |
| Enthaltung | nicht vorgesehen | `abstain` im Schema, leerer Kontext → Enthaltung |
| Daten als Daten | – | Prompt erklärt Beobachtungstexte als Evidenz, nicht Anweisung; Test mit anweisungsartigem Text |

Tests: `tests/test_assistant_rag_qwen.py` (8 Fälle, offline, ohne Modell).

## 3. Was noch fehlt, bevor der Pfad produktrelevant werden könnte

1. Fragenabhängiger Abruf (heute: Anker-Ähnlichkeit oder Rezenz, kein Textabruf).
2. Quellhashes der Beobachtungen im Kontext stehen im Prompt (`input_hash`), werden aber in der Antwort noch
   nicht zurückverlangt. T05 legt fest, ob Zitate an `input_hash` statt nur an die ID gebunden werden.
3. Benchmark T07 gegen zwei einfache Alternativen. Ohne nachgewiesenen Nutzen bleibt der Pfad optional.

## 4. Abnahme T06

- [x] Einstiegspunkt der Nutzerfrage nachgewiesen (es gibt keinen im Produkt).
- [x] Join korrigiert, Zeit-/Symbolfilter, Modus ausgewiesen.
- [x] Unbekannte Zitat-IDs werden abgelehnt (Negativtests).
- [x] Spätere Beobachtungen bei historischen Antworten ausgeschlossen (`as_of`).
- [ ] Vollständiger Offline-Durchlauf mit echtem Modell (braucht Ollama; nicht im Cloud-Container, nicht auf dem Kampagnen-Mac).
