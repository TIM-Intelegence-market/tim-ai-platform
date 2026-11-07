# KI1: KI-Filter vor TIM-Trades (Präregistrierung, Entwurf 0.1)

Stand: 07.11.2026. Auftrag Uzi (Thread „07.11. Agenten-Karte und KI-Anbindung“): „KI entscheidet bei Trades mit“,
Ziel „Die KI soll mit der Datensammlung sehr gute Trades machen“, dabei OF und alle anderen Strategien nutzen.
Status: **Entwurf**. Version 1.0 wird vor der ersten Auswertung eingefroren; Änderungen danach nur als neue Version.

## Frage

Verbessert ein lokales Sprachmodell als Filter die Ergebnisse der TIM-Pläne nach Kosten, wenn es jeden neuen
Plan der Horizont-Journale (15m, 1h, 1d) vor dem Ergebnis mit NEHMEN oder AUSLASSEN beurteilt?

## Arme

- **Regeln allein:** alle rechtzeitig beurteilten, geschlossenen Pläne (so wie der Kraken-Test sie heute handelt).
- **Regeln plus KI:** dieselben Pläne, nur die mit NEHMEN.
- Zur Kontrolle: **ausgelassene** Pläne (was die KI weggefiltert hat).

## Was die KI sieht (nur Daten bis zur Planzeit `created_at`)

1. Plan: Richtung, Einstiegszone, Stop, Ziele (auch in R), Marktzustand, Szenario, Grade, fehlende Bestätigungen,
   Datenqualität. Bewusst nicht: Evidenzstatus und Journal-/Pipeline-Entscheidung (stehen bei fast jedem Plan auf
   INSUFFICIENT_EVIDENCE/NO_TRADE und tragen keine Information).
2. Bisherige Ergebnisse desselben Journals, nur vor der Planzeit geschlossen (letzte 10, Summe netto R).
3. Andere TIM-Strategien (30m, struct, level, vp und die anderen Horizonte): Pläne der letzten 24 h bis zur Planzeit
   ohne Status, dazu deren Bilanz vor der Planzeit.
4. Markt: die letzten 24 geschlossenen Kerzen der Zeitebene mit Volumen und Delta (Taker-Kauf minus -Verkauf aus
   `agg_trades`, nur 15m und 1h), wenn `TIM_KI_MARKET_DSN` eine nur lesende Rolle nennt.

Code: `src/research_lab/ki_filter/` (Whitelist in `context.py`, zweite Zeitgrenze in `market_context`).

## Ablauf und Protokoll

- Beurteilt wird nur ein Plan im Status OPEN, höchstens 20 min nach `created_at`.
- Jede Antwort steht vor dem Ergebnis in `ki1_decisions.jsonl` (nur anhängen, Hash-Kette, Kopf-Datei `.head` mit
  Anzahl und letztem Hash; ein gekürztes, ersetztes oder kaputtes Protokoll bricht jede Auswertung ab).
  Gespeichert: Modell, Prompt-Version, der ganze Kontext, den die KI sah, Entscheidung, Vertrauen, Grund,
  `decided_at` (Laufbeginn) und `written_at` (Zeitpunkt des Schreibens). Jeder Lauf gibt den Kopf aus; er gehört in
  die Evidenzdatei, damit ein gemeinsam neu geschriebenes Protokoll samt Kopf auffällt.
- Modell zu Beginn: `qwen3.5:9b` lokal über Ollama, Temperatur 0, Seed 7, Prompt-Version `ki1-prompt/2`.
  Ein Wechsel von Modell oder Prompt startet eine neue Zählung (die Auswertung trennt danach).
- Fehlgeschlagene Anfragen schreiben nichts; der nächste Lauf versucht es innerhalb des Fensters erneut.

## Auswertung

- Gezählt wird ein Urteil nur, wenn `written_at` vor `filled_at` liegt (oder der Plan nie gefüllt wurde).
  Spätere Urteile zählen als „late“ und gehen in keinen Arm. Doppelte Urteile zum selben Plan zählen einmal.
- Auswahl: Pläne, die schon vor dem ersten Lauf gefüllt sind, werden nie beurteilt. Beide Arme haben dieselben
  Pläne, der Vergleich bleibt fair; „Regeln allein“ ist aber nicht genau die Menge, die der Kraken-Test handelt.
  Der Anteil verpasster Pläne wird mitberichtet.
- Ergebnis je Arm: Trades, Summe und Mittel netto R (Kostenmodell protocol/1.1 des Plan-Journals), Treffer,
  größter Drawdown in R; zusätzlich je Zeitebene.
- **Frühestens nach 60 geschlossenen, rechtzeitig beurteilten Plänen.** Vorher nur Zählstand, keine Bewertung.
- Offen bis 1.0: kleinster relevanter Effekt (Vorschlag: +0,05 R je Plan im Mittel und kein größerer Drawdown),
  Test (Vorschlag: gepaarter Bootstrap über die Pläne, einseitig, 5 %), Umgang mit sehr wenigen NEHMEN.

## Grenzen

- Nur Papier und Schatten. Der Live-Trader liest dieses Protokoll nicht.
- Echtgeld: erst nach bestandener Auswertung und nur auf Uzis ausdrückliches Wort. Auch dann darf die KI nur
  einen Plan sperren, nie einen eigenen Trade öffnen; die Limits des Kraken-Tests bleiben.
- Holdout 2025 bleibt zu. Die Studie ist prospektiv und nutzt keine Archivdaten.
- Erste Probe am Mac (07.11.2026, abgelaufener 15m-Plan, ohne Marktdaten): Antwort im Schema nach 37 s.
