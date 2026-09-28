# Herkunft und Wahrheitsgrenze

## Die eine Zahl, auf der der Skill steht

Der Satz "Claude stimmt dir zu, und wenn du widersprichst, stimmt er dir öfter zu"
ist keine Meinung, sondern aus Anthropics eigener Auswertung. Abgerufen am
06.09.2026:

* **Quelle:** `anthropic.com/research/claude-personal-guidance`, veröffentlicht am
  30.04.2026.
* **Umfang:** rund 38.000 Gespräche zur persönlichen Orientierung, gezogen aus
  einer Stichprobe von einer Million claude.ai-Gesprächen aus März und April 2026.
* **Befund:** in 9 Prozent der Gespräche zustimmendes Verhalten. In
  Beziehungsfragen 25 Prozent, bei spirituellen Themen 38 Prozent.
* **Der Punkt, der diesen Skill trägt:** 18 Prozent in Gesprächen, in denen die
  Nutzer widersprechen, gegenüber 9 Prozent ohne Widerspruch. Wer nachhakt, weil
  ihm die Antwort nicht gefällt, bekommt doppelt so oft Zustimmung.

Anthropic nennt in derselben Veröffentlichung auch, dass neuere Modelle deutlich
weniger zustimmen als ältere. Der Effekt ist also nicht festgeschrieben, er wird
kleiner.

## Was diese Zahl NICHT sagt

Das ist die wichtigste Grenze an diesem Gegenstand, und sie wird hier zuerst
genannt, nicht am Ende:

* **Die Studie handelt von persönlicher Orientierung**, also Beziehungen,
  Spiritualität, Karriere, Alltagsentscheidungen. **Nicht von Geschäftsideen.**
  Es gibt keine Zahl dafür, wie oft Claude einer Geschäftsidee zustimmt. Wer den
  Prozentsatz auf Gründungspläne überträgt, trägt ihn weiter, als er reicht.
* Die 9 und die 18 Prozent sind **von Anthropic selbst** erhoben und
  veröffentlicht, nicht von unabhängiger Stelle nachgeprüft.
* "Zustimmendes Verhalten" ist in der Studie eine Einstufung durch ein
  Sprachmodell, keine Handzählung durch Menschen.

## Was am 06.09.2026 geprüft wurde

* Die Zahlen wurden am selben Tag direkt von der Anthropic-Seite geholt und
  gegengelesen, nicht aus einem Presseartikel übernommen. Mehrere
  Zweitberichterstattungen nennen abweichende Bezugsgrößen.
* Der Skill läuft auf zwei Wegen, weil er nichts ausführt und nur Text erzeugt:
  in Claude Code mit fünf parallelen Agents, in claude.ai, der App und Cowork mit
  fünf Durchgängen nacheinander in einer Antwort. Der zweite Weg steht im Skill,
  weil die meisten Leute keine parallelen Agents haben.
* Das ZIP wurde gegen den Quellordner gelesen und enthält `SKILL.md`,
  `references/rollen.md` und diese Datei.

## Nicht gemessen

* **Es gibt keinen Vergleichstest gegen eine normale Frage.** Niemand hat
  gezählt, ob ein Beirat aus fünf Rollen zu besseren Entscheidungen führt als
  einmal fragen. Der Skill baut Widerspruch ein, er beweist nicht, dass
  Widerspruch bei dir zu mehr Umsatz führt.
* **Keine der fünf Rollen ist ein Fachmann.** Es sind fünf Blickwinkel desselben
  Sprachmodells, die sich gegenseitig nicht sehen. Das ersetzt keinen
  Steuerberater, keinen Anwalt und keinen Menschen, der die Branche kennt.
* **Der Rechercheur ist so gut wie seine Suche.** Findet er nichts, ist die Idee
  deshalb nicht neu, sondern möglicherweise nur schlecht gesucht. Er ist
  angewiesen, das offen hinzuschreiben, statt Lücken zu füllen.
* **Die Noten von 1 bis 10 sind keine Messwerte.** Sie sind eine Einschätzung, die
  ein Modell in einer Rolle abgibt, und sie sind zwischen zwei Läufen nicht
  stabil. Der Vorsitzende mittelt sie deshalb ausdrücklich nicht.
* **Die deutsche Fassung ist vom 06.09.2026** und damit neu. Sie ist nicht über
  Wochen gelaufen.

## Rechte

Die englische Urfassung dieses Aufbaus stammt aus einem offen geteilten
`roast`-Skill. Rollenschnitt, Urteilsform, der Weg ohne parallele Agents, die
Regel gegen das Weichwerden bei Widerspruch und sämtliche deutschen Texte sind
eigene Arbeit. Die Zahlen stammen aus Anthropics öffentlicher Veröffentlichung und
sind mit Quelle genannt. Es besteht keine Verbindung zu Anthropic.
