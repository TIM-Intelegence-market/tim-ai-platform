---
name: vormachen-vorbereitung
description: Bereitet eine Record-&-Replay-Aufnahme in ChatGPT oder Codex vor und legt vorher fest, welche Angaben sich bei jedem Lauf ändern und an welchen Stellen nachgefragt werden muss. Verwenden wenn der Nutzer "Record and Replay", "Record a skill", "Skill aufnehmen", "Ablauf vormachen", "VORMACHEN" sagt, oder wenn er einen wiederkehrenden Ablauf am Rechner automatisieren will und ihn lieber zeigt als beschreibt.
---

# Vormachen: die Vorbereitung vor der Aufnahme

Record & Replay nimmt auf, was du tust. Es nimmt nicht auf, was du dir dabei
gedacht hast.

Genau daran scheitern die meisten ersten Aufnahmen. Der Mitschnitt zeigt: Datei
`oktober.csv` geöffnet, Zeitraum 01.10. bis 31.10. gewählt, Bericht an
buchhaltung@ geschickt. Beim nächsten Lauf macht der Skill wieder genau das,
mit derselben Datei, demselben Zeitraum, demselben Empfänger. Er kann nicht
wissen, was davon der Fall war und was die Regel ist.

**Dieser Skill schreibt vor der Aufnahme auf, was der Mitschnitt nicht sehen
kann.** Danach erst wird aufgenommen.

Zwei Sachen kommen dabei heraus:

1. **Die veränderlichen Angaben.** Was ist an diesem einen Durchlauf zufällig
   und muss beim nächsten Mal abgefragt werden.
2. **Die Haltepunkte.** Wo darf der Skill nicht selbst entscheiden, sondern muss
   fragen, bevor er weitermacht.

Ohne beides läuft der Skill zuverlässig falsch statt zuverlässig richtig.

## Ablauf

Die fünf Schritte werden der Reihe nach abgearbeitet, einer nach dem anderen, und
jeder wird beantwortet, bevor der nächste kommt. Nicht alle fünf Fragen auf
einmal stellen.

### Schritt 1: den Ablauf benennen

Fragen:

* Was ist der Ablauf, in einem Satz, vom ersten Klick bis zum Ergebnis?
* Wie oft kommt er vor, und was ist am Ende da, das vorher nicht da war?
* Wie lange dauert er von Hand?

Wenn die Antwort auf die erste Frage länger als ein Satz ist, sind es zwei
Abläufe. Dann wird der kleinere zuerst aufgenommen. Eine Aufnahme über zwanzig
Minuten mit drei Programmen ergibt einen Skill, der an einer von dreißig Stellen
hängen bleibt und an dem niemand den Fehler findet.

**Regel: ein Ablauf, ein Ergebnis, eine Aufnahme.**

### Schritt 2: die veränderlichen Angaben herausschreiben

Frage, wörtlich so stellen:

> Geh den Ablauf einmal im Kopf durch. An welchen Stellen tippst oder wählst du
> etwas aus, das beim nächsten Mal anders wäre?

Typisch sind: Dateiname, Zeitraum, Monat, Kundenname, Empfänger, Betrag,
Projektnummer, Ordner, Suchbegriff.

Jede genannte Stelle kommt in eine Tabelle mit drei Spalten: **Angabe**,
**Beispiel aus diesem Durchlauf**, **woher sie beim nächsten Mal kommt** (der
Nutzer nennt sie / steht in einer Datei / ist immer der gleiche Wert).

Was in der dritten Spalte "ist immer der gleiche Wert" trägt, ist keine
veränderliche Angabe und fliegt wieder raus. Was dort "der Nutzer nennt sie"
trägt, muss der fertige Skill abfragen können.

**Kontrollfrage am Ende, immer stellen:** "Wenn ich den Ablauf nächsten Monat
starte und dir nur den Monat nenne, fehlt dir dann noch etwas?" Was hier
nachkommt, ist die Angabe, die sonst fehlt.

### Schritt 3: die Haltepunkte festlegen

Frage:

> An welcher Stelle im Ablauf wäre ein Fehler nach draußen sichtbar oder nicht
> mehr zurückzunehmen?

Standard-Haltepunkte, die immer gesetzt werden, auch wenn der Nutzer sie nicht
nennt:

* **Senden.** Mail, Nachricht, Kommentar, alles, was bei jemand anderem ankommt.
* **Veröffentlichen.** Hochladen, freigeben, live stellen.
* **Bezahlen und beauftragen.** Jeder Vorgang mit Geld.
* **Löschen und Überschreiben.** Besonders alles, was keinen Papierkorb hat.
* **Fremde Daten.** Sobald Daten von Kunden, Mitarbeitern oder Patienten im Spiel
  sind: Haltepunkt vor jedem Schritt, bei dem sie den Rechner verlassen.

Für jeden Haltepunkt wird festgelegt, was der Skill statt des Schritts tut:
anhalten und fragen, oder den Schritt als Entwurf vorbereiten und liegen lassen.
**Entwurf ist besser als Frage**, weil eine Frage übersehen wird und ein Entwurf
liegen bleibt, bis jemand hinsieht.

### Schritt 4: die Prüfung am Ende

Frage:

> Woran siehst du, dass der Durchlauf richtig war, ohne alles nachzurechnen?

Daraus wird ein Satz, der später im Skill unter "wie zu prüfen" steht. Zum
Beispiel: die Zeilenzahl der Ausgabe stimmt mit der Eingabe überein, die Summe
unten entspricht dem Kontoauszug, die Datei liegt im richtigen Ordner und trägt
das heutige Datum.

Ohne diesen Satz merkt niemand, wenn der Skill ab dem dritten Lauf leise etwas
anderes tut.

### Schritt 5: die Aufnahme vorbereiten

`references/aufnahme-checkliste.md` vorlesen und Punkt für Punkt abhaken. Erst
danach wird aufgenommen.

## Was am Ende dieses Skills entsteht

Eine Datei `vormachen-<ablauf>.md` im aktuellen Ordner, mit genau diesen
Abschnitten:

```
# <Ablauf in einem Satz>

## Veränderliche Angaben
| Angabe | Beispiel heute | Woher beim nächsten Mal |

## Haltepunkte
- <Stelle>: anhalten und fragen / als Entwurf liegen lassen

## Fertig ist der Lauf, wenn
<der eine Prüfsatz>

## Vor der Aufnahme erledigt
<abgehakte Checkliste>
```

Diese Datei wird beim Start der Aufnahme mit in den Prompt gegeben. Die Doku
sieht das ausdrücklich vor: der vorgeschlagene Prompt kann vor dem Abschicken
ergänzt werden ("Review the suggested prompt, add any helpful context, and
submit it").

## Nach der Aufnahme

Record & Replay schreibt einen Entwurf des Skills. Der wird nicht ungelesen
übernommen, sondern gegen die Datei von oben gelesen:

1. **Stehen alle veränderlichen Angaben als Platzhalter drin,** oder sind die
   Beispielwerte vom Aufnahmetag fest eingebrannt? Fest eingebrannte Werte
   werden ersetzt, entweder von Hand oder mit der Bitte um eine Überarbeitung
   ("You can also ask for further refinements", sagt die Doku).
2. **Steht jeder Haltepunkt drin?** Fehlt einer, wird er nachgetragen.
3. **Steht der Prüfsatz unter "wie zu prüfen"?**
4. **Ein Probelauf mit anderen Werten**, nicht mit denen aus der Aufnahme. Wer
   mit denselben Werten prüft, prüft nichts.

Die Vorlage in `references/vorlage-skill.md` zeigt, wie der fertige Skill
aussehen soll, inklusive der Platzhalter-Schreibweise.

## Voraussetzungen, vorher abfragen

Wenn der Nutzer noch nie aufgenommen hat, diese drei Punkte prüfen, bevor es
losgeht:

* **macOS.** Record & Replay gibt es laut Doku nur dort.
* **Computer Use muss verfügbar und eingeschaltet sein.** Ohne das erscheint der
  Menüpunkt nicht. In verwalteten Installationen mit `requirements.toml` schaltet
  `[features].computer_use = false` beides zusammen ab.
* **Der Weg zur Aufnahme geht über die ChatGPT-Desktop-App**, nicht über die
  Kommandozeile: ChatGPT wählen und im Umschalter Work einschalten oder Codex
  wählen, dann Plugins öffnen, das Plus-Menü öffnen, **Record a skill** wählen.
  Es gibt dafür keinen Slash-Befehl.

Der Menüpunkt heißt "Record a skill", das Feature heißt "Record & Replay". Wer
im Menü nach "Record & Replay" sucht, findet nichts.

## Grenze, die offen benannt wird

Der Skill läuft beim nächsten Mal nicht von selbst los. Du öffnest einen neuen
Chat, bittest darum, den Skill zu benutzen, und nennst die Werte, die diesmal
anders sind. Ab da läuft der Ablauf allein durch. Wer etwas anderes verspricht,
hat die Doku nicht gelesen.
