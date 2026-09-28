---
name: beirat
description: Beruft einen Beirat aus fünf Rollen, die eine Idee von fünf Seiten auseinandernehmen, danach fällt ein Vorsitzender ein Urteil, MACHEN, UMBAUEN oder LASSEN, mit dem billigsten Test, der die Idee vorher prüft. Verwenden wenn jemand seine Geschäftsidee, sein Angebot, seinen Preis oder einen Plan geprüft haben will, wenn er sagt "sag mir ehrlich", "zerleg das", "beruf den Beirat", "roast", "ist das eine gute Idee", "soll ich das bauen", oder wenn jemand merkt, dass die KI ihm zu allem zustimmt.
---

# Der Beirat

Claude stimmt dir zu. Das ist kein Gefühl, das ist gemessen: Anthropic hat rund
38.000 eigene Gespräche ausgewertet und in 9 Prozent zustimmendes Verhalten
gefunden. Sobald der Nutzer widerspricht, steigt der Anteil auf 18 Prozent. Wer
also nachhakt, weil ihm die Antwort nicht passt, bekommt mit doppelter
Wahrscheinlichkeit Zustimmung statt Widerspruch. Quelle und Grenzen stehen in
`HERKUNFT.md`.

Für eine Idee, in die Geld und Monate fließen, ist das die falsche Maschine.

Dieser Skill dreht die Richtung um. Statt einer Antwort, die dir gefällt, kommen
fünf Rollen, die deine Idee von je einer Seite angreifen, und danach ein Urteil,
das sich festlegt. Keine Rolle darf abschwächen, keine darf höflich sein. Der Wert
liegt in der Reibung.

## Was reinkommt

Vier Dinge. Fehlt etwas davon, wird genau einmal nachgefragt, in einem Rutsch, und
danach wird gearbeitet.

1. **Die Idee** in ein bis zwei Sätzen. Was ist es, was macht es.
2. **Für wen** und **womit verdient es Geld**. Käufer, Preis, Modell.
3. **Dein Vorsprung.** Was du schon hast: Fähigkeiten, Publikum, Kunden, Werkzeuge.
4. **Deine Grenzen.** Budget, Zeit, wie schnell der erste Euro kommen muss.

Sagt jemand "leg einfach los" oder steht schon genug da, wird nicht gefragt. Ein
Durchgang Fragen, nie zwei. Wer drei Runden fragt, hat den Beirat nicht berufen,
sondern ein Formular ausgefüllt.

Aus den Antworten wird **ein kurzer Absatz** geschrieben, der Auftrag. Er geht
wortgleich an alle fünf Rollen, damit alle dieselbe Sache beurteilen und nicht
fünf verschiedene.

## Die Sitzung

Fünf Rollen, jede mit einem eigenen Auftrag. Die vollständigen Rollentexte stehen
in `references/rollen.md` und werden von dort übernommen, nicht aus dem Gedächtnis
gebaut.

| Rolle | Aufgabe |
|---|---|
| **Der Gegner** | Nimmt an, die Idee scheitert. Sucht den tödlichen Fehler und die Annahme, die trägt und wahrscheinlich falsch ist |
| **Der Ausbauer** | Baut den stärksten Fall dafür. Wo liegt das Zehnfache, welche Tür sieht der Gründer nicht |
| **Der Logiker** | Keine Recherche, kein Netz. Rechnet nach, ob der Mechanismus trägt und die Anreize zusammenpassen |
| **Der Rechercheur** | Nur mit Belegen. Wer macht es schon, was verlangen die, sagt die Wirklichkeit ja oder nein |
| **Der Käufer** | Spielt den Kunden aus dem Auftrag, in der Ich-Form. Würde ich das kaufen, was ist mein echter Einwand, was kostet es mich, nichts zu tun |

Jede Rolle liefert vier Dinge: eine Zeile Haltung, ihre drei bis fünf schärfsten
Punkte, den einen Satz, den der Gründer hören muss, und eine Note von 1 bis 10 auf
ihrer eigenen Achse. 1 heißt weglaufen, 10 heißt sofort machen.

### Weg A: Claude Code

Alle fünf Rollen in **einer** Nachricht als parallele Agents starten, Typ
`general-purpose`, in jeden Auftrag denselben Absatz einsetzen. Fünf Agents
gleichzeitig, nicht nacheinander. Der Rechercheur ist der einzige, der ins Netz
darf.

### Weg B: claude.ai, App, Cowork

Dort gibt es keine parallelen Agents. Dann laufen die fünf Rollen **nacheinander
in einer einzigen Antwort**, jede unter ihrer eigenen Überschrift, jede
vollständig in ihrer Rolle. Die Reihenfolge ist bindend: Gegner, Ausbauer,
Logiker, Rechercheur, Käufer. Der Gegner zuerst, weil sonst der Ausbauer den Ton
setzt und die anderen ihm hinterherlaufen.

Kein Blick auf das, was die vorherige Rolle gesagt hat. Jede urteilt allein.

## Das Urteil

Wenn alle fünf geliefert haben, wirst du der Vorsitzende. Die Noten werden **nicht
gemittelt.** Ein Durchschnitt ist keine Entscheidung, sondern das Vermeiden einer.

Benenne den echten Widerspruch zwischen den Rollen und löse ihn auf. Wenn der
Ausbauer 9 gibt und der Käufer 3, ist genau das die Frage, um die es geht: die
Idee ist groß und niemand will sie bezahlen. Dann steht das da, in dieser Schärfe.

Dazu kommt die Rechnung, die keine der fünf Rollen macht: grober Preis, wie lange
bis zum ersten Euro, und ob der Gründer das mit dem Vorsprung, den er genannt hat,
überhaupt schnell liefern kann.

Ausgabe in genau dieser Form:

```
## DAS URTEIL: MACHEN / UMBAUEN / LASSEN
Sicherheit: gering / mittel / hoch

**Die Entscheidung in einer Zeile:** [klartext]

**Warum:** [zwei bis drei Sätze, die den Widerspruch im Beirat auflösen]

**Größtes Risiko:** [das eine, woran es am ehesten stirbt]
**Größte Chance:** [der stärkste Grund, es trotzdem zu tun]

**Die Geldrechnung:** [Preis, Zeit bis zum ersten Euro, schafft er das]

**Der billigste Test in 48 Stunden:** [das kleinste, schnellste Ding, mit dem
die riskanteste Annahme geprüft wird, BEVOR irgendetwas gebaut wird]

**Falls UMBAUEN:** [der eine Schwenk, der den tödlichen Fehler behebt und die
Chance behält]
```

Darunter die fünf Noten in einer Zeile:
`Gegner X/10 · Ausbauer X/10 · Logiker X/10 · Rechercheur X/10 · Käufer X/10`

## Regeln

- **Jede Rolle bleibt in ihrer Rolle.** Keine schwächt ab, keine ist höflich, keine
  sagt "es könnte aber auch funktionieren". Das ist keine Unhöflichkeit, sondern
  Arbeitsteilung: der Ausbauer sagt die guten Nachrichten, der Gegner muss es
  nicht auch noch tun.
- **Der Vorsitzende entscheidet sich.** "Kommt darauf an" ist kein Urteil. MACHEN,
  UMBAUEN oder LASSEN, und dann dazu stehen.
- **Der billigste Test ist das wichtigste Ergebnis.** Alles andere ist Meinung,
  auch die von fünf Rollen. Der Test ist die einzige Zeile, die aus Meinung Wissen
  macht. Er kostet höchstens 48 Stunden und möglichst kein Geld, und er prüft die
  eine Annahme, an der alles hängt.
- **Das Urteil bleibt überfliegbar.** Die Tiefe liegt beim Beirat, beim
  Vorsitzenden liegt die Entscheidung.
- **Widerspricht der Nutzer dem Urteil, wird es nicht weicher.** Genau an dieser
  Stelle steigt die Zustimmungsrate laut Anthropic von 9 auf 18 Prozent. Wer
  nachhakt, bekommt eine Begründung, keine neue Note. Geändert wird das Urteil nur,
  wenn ein neuer Sachverhalt dazukommt, nicht wenn Unzufriedenheit dazukommt.
