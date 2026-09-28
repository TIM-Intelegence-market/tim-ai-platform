# Herkunft und Wahrheitsgrenze

## Quelle

Alles, was dieser Skill über Record & Replay behauptet, steht in OpenAIs eigener
Dokumentation. Beide Seiten am 14.09.2026 abgerufen:

* **https://developers.openai.com/codex/extend/record-and-replay** — Schreibweise
  "Record & Replay", der Hinweis auf macOS und Computer Use, der Klickweg über
  die ChatGPT-Desktop-App mit dem Menüpunkt "Record a skill", der Satz, dass der
  Entwurf beschreibt, wann der Ablauf gilt, welche Eingaben er braucht, welche
  Schritte folgen und wie das Ergebnis zu prüfen ist, der Hinweis auf weitere
  Überarbeitungen, und der Abschnitt "Replay the workflow", nach dem man in einem
  neuen Chat um den Skill bittet und die diesmal abweichenden Werte nennt.
* **https://developers.openai.com/codex/build-skills** — ein Skill ist ein
  Verzeichnis mit `SKILL.md` plus optionalen Skripten und Referenzen, `name` und
  `description` sind Pflicht.
* **https://developers.openai.com/codex/changelog** — Eintrag vom 18.06.2026
  (Version 26.616) zur Einführung, Eintrag vom 31.07.2026 zur Ausweitung auf EU,
  Vereinigtes Königreich und Schweiz.

Die fünf Schritte, die Haltepunkt-Liste und die Aufnahme-Checkliste sind **eigene
Arbeit** und stehen so in keiner Doku. Sie kommen aus der Frage, warum ein
aufgenommener Ablauf beim zweiten Durchlauf etwas anderes tut als beim ersten,
und aus der Erfahrung mit Automationen, die zu früh selbst senden durften.

## Am 14.09.2026 geprüft

* Beide Doku-Seiten am selben Tag geöffnet und die Stellen wörtlich
  gegengelesen, nichts sinnverändernd gekürzt.
* Die beiden 404-Adressen, die man naheliegend rät, sind wirklich tot:
  `/codex/desktop` und `/codex/extend/skills`. Die richtigen Adressen stehen oben.
* Das Repo `github.com/openai/codex` trägt dazu nichts bei. Seine `docs/` sind
  Stubs, `docs/skills.md` ist eine Weiterleitung mit 115 Byte. Record & Replay
  sitzt in der Desktop-App, nicht in der CLI.

## Nicht gemessen, ausdrücklich

* **Die Aufnahme selbst wurde nicht gefahren.** Niemand hat für diesen Skill eine
  Record-&-Replay-Aufnahme gemacht und den erzeugten Skill danach laufen lassen.
  Der Inhalt hier ist die Vorbereitung darauf, belegt aus der Doku, nicht aus
  einem eigenen Durchlauf.
* **Die drei "Stellen, an denen ein aufgenommener Skill regelmäßig falsch ist"
  sind eine begründete Erwartung, keine Statistik.** Sie folgen daraus, was ein
  Bildschirmmitschnitt sehen kann und was nicht. Gezählt hat sie niemand.
* **Kein Vergleich mit anderen Wegen.** Ob ein aufgenommener Skill besser läuft
  als ein von Hand geschriebener, ist hier nicht geprüft.
* **Die Verfügbarkeit in Deutschland** stützt sich auf den Changelog-Eintrag vom
  31.07.2026, nicht auf einen eigenen Test auf einem deutschen Konto.

## Rechte

Die Zitate stammen aus OpenAIs öffentlicher Dokumentation und sind mit Quelle
genannt. Der Rest ist eigener Text. Es besteht keine Verbindung zu OpenAI.
