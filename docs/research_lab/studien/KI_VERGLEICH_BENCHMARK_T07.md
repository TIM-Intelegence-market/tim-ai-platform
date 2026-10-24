# T07: KI-Zusatznutzen gegen einfache Alternativen messen (Benchmark-Spezifikation, Entwurf)

Stand 22.10.2026. Abhängig von T06 (Kontextaufbau, Zitatprüfung) und T05 (Quellbindung). Annotation kann sofort
beginnen; der Vergleich läuft erst in einer Laborumgebung mit Modell (nicht auf dem Kampagnen-Mac).

## 1. Die eine Nutzeraufgabe

„Zeitbezogene Marktfrage mit belegter Antwort und sichtbarer Unsicherheit“: Der Nutzer nennt Symbol, Zeitpunkt oder
Zeitraum (UTC) und fragt, was TIM damals beobachtet hat, wie es ausging oder ob zwei Beobachtungen einander
widersprechen. Die Antwort nennt Beobachtungs-IDs, deren Ergebnis (falls bekannt zum Stichtag) und sagt, wenn sie
nichts belegen kann. Kein Signal, keine Empfehlung.

## 2. Fragenbestand (Pilot, 120 Fragen)

| Klasse | Anzahl | Beispiel | Erwartete Antwort |
|---|---|---|---|
| Belegfragen | 30 | „Welche Orderflow-Beobachtungen gab es am 2026-07-23 zwischen 20:30 und 21:00 UTC für BTCUSDT?“ | Liste der IDs aus der Datenbank, vollständig |
| Zeitfragen | 30 | „Was war zum Stand 2026-07-23 21:00 UTC über ofobs_00526436… bekannt?“ | nur Horizonte mit `target_at <= as_of`; 30-min-Ergebnis darf **nicht** genannt werden |
| Konfliktfragen | 30 | „Widersprechen sich die Beobachtungen X und Y?“ | Ja/Nein mit beiden IDs; ohne Erfindung einer Auflösung |
| Unbeantwortbare Fragen | 30 | „Wie wird BTC morgen schließen?“, „Welche Beobachtung gab es am 2026-02-30?“ | Enthaltung mit Begründung |

Quelle der Fälle: `artifacts/v2_completion/manual_review_workbook.json` (24 Fälle vom Juli 2026) und weitere Fälle
aus der Datenbank-Kopie des Labors (nie aus der Live-DB). Je Frage werden `expected_citations` (IDs), `allowed_claims`
(Sätze, die belegt sind), `forbidden_claims` (z. B. Ergebnisse nach dem Stichtag) und `as_of` annotiert.

**Trennung:** 80 Fragen Entwicklungssatz (offen), 40 Fragen verdeckter Testsatz (Hash der Datei im Repo, Inhalt
außerhalb bis zur Auswertung). Am verdeckten Satz wird nicht optimiert; reicht die Präzision nicht, wird ein neuer
Satz gebaut.

Dateiformat `docs/research_lab/studien/t07_fragen/*.jsonl`, eine Zeile je Frage:

```json
{"id":"T07-B-001","class":"beleg","question":"…","symbol":"BTCUSDT","as_of":"2026-07-23T21:00:00Z",
 "expected_citations":["ofobs_…"],"allowed_claims":["…"],"forbidden_claims":["…"],"annotator":"…","annotated_at":"…"}
```

## 3. Drei Varianten

| Variante | Was sie tut | Modell |
|---|---|---|
| A deterministische Suche | SQL/Filter über Beobachtungen und Validierungen bis `as_of`, Anzeige als Tabelle | keins |
| B Retrieval ohne Sprachmodell | Kontext aus T06 (`build_context`), Antwort = Vorlage mit IDs und Ergebnissen | keins |
| C Retrieval mit Sprachmodell | gleicher Kontext wie B, Antwort von Qwen, Zitatprüfung aus T06 | Qwen (Version, Prompt-Hash, Retrieval 0.2.0 eingefroren) |

Alle drei bekommen dieselbe Frage und denselben `as_of`.

## 4. Messgrößen (je Variante, je Klasse)

1. Quellenrichtigkeit: Anteil der Zitate, die existieren und zu `as_of` bekannt waren.
2. Gestützte Aussagen: Anteil der Sätze, die in `allowed_claims` liegen; Anteil `forbidden_claims` (muss 0 sein).
3. Relevante Treffer: Recall der `expected_citations`.
4. Enthaltungsqualität: Enthaltung bei unbeantwortbaren Fragen (richtig), Enthaltung bei beantwortbaren (falsch).
5. Bearbeitungszeit des Menschen bis zur verifizierten Antwort (Sekunden, bei A/B/C getrennt gemessen),
   Latenz und Kosten der Variante.

Menschliche Bewertung: zwei Bewerter, verblindet gegenüber der Variante, Reihenfolge der Varianten je Frage
zufällig permutiert (Seed im Bericht).

## 5. Vorab festgelegte Schwellen

- Qualitätsgrenzen (Ausschluss): `forbidden_claims` > 0 % oder Quellenrichtigkeit < 100 % im verdeckten Satz →
  Variante C ist nicht freigabefähig, unabhängig vom Nutzen.
- Minimaler relevanter Nutzen: C spart gegenüber B mindestens 25 % Bearbeitungszeit **oder** erhöht den Recall um
  mindestens 10 Prozentpunkte, bei gleicher Enthaltungsqualität. Unterschiede mit Bootstrap-Intervall über Fragen.
- Fällt C durch, wird der KI-Pfad optional (Schalter aus) oder entfernt; B bleibt als Produktweg möglich.
- 120 Fragen sind ein Pilot. Ist das Intervall breiter als der Mindestnutzen, lautet das Ergebnis KEIN URTEIL,
  und ein größerer Satz wird geplant.

## 6. Abnahme T07

Versionierter Benchmark (Fragen-Hash, Modell, Prompt, Retrieval, Commit), Vergleichsbericht mit allen fünf Größen
je Klasse, Rohdaten der Bewerter. Eine zweite Person reproduziert A und B vollständig und C auf einer Stichprobe.
