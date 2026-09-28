# Herkunft und Wahrheitsgrenze

## Quelle

Die zwei Behauptungen, auf denen der Skill steht, sind Zitate und stehen wörtlich
in Anthropics eigener Dokumentation. Beide am 04.09.2026 abgerufen:

* **Context Rot:** `anthropic.com/engineering/effective-context-engineering-for-ai-agents`,
  Abschnitt "Why context engineering matters". Anthropic beschreibt dort selbst,
  dass die Genauigkeit sinkt, je mehr Token im Kontext stehen, und nennt den
  Effekt beim Namen.
* **Compact:** `code.claude.com/docs/en/how-claude-code-works`, Abschnitt zum
  Kontextfenster: Claude fasst automatisch zusammen, aber Anweisungen von früh
  im Gespräch können dabei verloren gehen ("can get lost").

Der Aufbau der Übergabe-Datei stammt aus der Praxis, aus der dieser Skill
entstanden ist: einem Projekt, in dem seit Monaten nach jeder Sitzung ein Eintrag
mit einer eigenen Zeile für das geschrieben wird, was schiefging. Genau daraus
kommt der Pflicht-Abschnitt `Was nicht funktioniert hat`. Die deutschen Sätze
dazwischen sind eigener Text.

## Am 04.09.2026 geprüft

* Beide Zitate am selben Tag von den Originalseiten geholt und wörtlich
  gegengelesen, nichts umformuliert, nichts sinnverändernd gekürzt.
* Der Skill läuft in Claude Code und in Claude.ai beziehungsweise Cowork, weil er
  nichts ausführt, sondern nur liest und eine Datei schreibt.
* Das ZIP wurde gegen den Quellordner gelesen und enthält `SKILL.md`,
  `references/vorlage.md` und diese Datei.

## Nicht gemessen

* **Es gibt keinen Vergleichstest.** Weder "spart X Prozent Tokens" noch "der
  neue Chat ist um Y besser". Der Skill setzt um, was Anthropic zum Kontext
  dokumentiert hat, gemessen ist das nicht.
* **Der Abschnitt `Was nicht funktioniert hat` ist eine Erfahrungsregel, kein
  Messergebnis.** Er steht drin, weil ein neuer Chat ohne ihn beobachtbar
  dieselben Wege noch einmal gegangen ist, nicht weil das jemand gezählt hätte.
* **Die Fassung, die eine Datei schreibt, ist vom 04.09.2026.** Die Version
  davor gab die Übergabe nur im Chat aus. Diese neue Fassung ist noch nicht über
  Wochen gelaufen.
* **Auf einem fremden Setup wurde der Skill nicht gefahren.** Er ist aus einem
  einzigen Projekt heraus entstanden.
* Ob eine Sackgasse wirklich eine war, beurteilt ein Sprachmodell aus dem
  Gesprächsverlauf. Wer es prüfen will, liest die Datei, bevor er den alten Chat
  zumacht.

## Rechte

Die zwei Zitate stammen aus Anthropics öffentlicher Dokumentation und sind mit
Quelle genannt. Der Rest ist eigener Text. Es besteht keine Verbindung zu
Anthropic.
