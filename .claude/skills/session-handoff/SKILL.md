---
name: session-handoff
description: Schreibt am Ende einer Sitzung eine Übergabe-Datei, mit der ein neuer Chat da weitermacht, wo der alte aufgehört hat. Verwenden wenn der Nutzer "Session Handoff", "Übergabe", "Handoff", "ich mach den Chat gleich zu", "fass zusammen bevor ich clear mache" sagt, oder wenn er ankündigt, den Chat zu leeren oder neu zu starten.
---

# Session Handoff

Ein langer Chat wird schlechter, nicht besser. Alles liegt auf einem Haufen: jeder
Fehlversuch, jeder Umweg, jede verworfene Idee. Das Wichtige geht darin unter.
Anthropic nennt das Context Rot.

Compact ist dagegen kein Mittel, sondern ein zweites Problem. Beim Zusammenfassen
entscheidet das Modell selbst, was es wegwirft, und die Entscheidung, an der alles
hängt, kann dabei verschwinden. Die Claude-Code-Doku sagt das selbst: Anweisungen
von früher können verloren gehen.

Dieser Skill macht stattdessen eine Übergabe: **eine Textdatei, geschrieben bevor
der Chat zugemacht wird.** Der neue Chat liest sie und arbeitet weiter, als hätte
es den alten nie gegeben.

## Der Punkt, an dem fast alle scheitern

**In der Datei muss stehen, was NICHT funktioniert hat.**

Ohne diesen Abschnitt macht der neue Chat denselben Fehler noch einmal: derselbe
Weg, dieselbe Sackgasse, doppelte Zeit, doppelte Tokens. Der Abschnitt
`Was nicht funktioniert hat` ist deshalb Pflicht und wird nie weggelassen, auch
nicht, wenn die Sitzung glatt lief. Lief sie glatt, steht dort genau das,
zusammen mit dem, was du unterwegs verworfen hast.

## Vor dem Schreiben

Lies `references/vorlage.md` vollständig. Dort steht die Struktur der Datei und
zu jedem Abschnitt, was hineingehört und was nicht.

## Schritt 1: die ganze Sitzung durchgehen

Nicht die letzten Nachrichten zusammenfassen. Das ist der häufigste Fehler und
macht aus der Übergabe einen Statusbericht über die letzte halbe Stunde.

Geh den kompletten Verlauf durch und zieh den Stand aus diesen Quellen, in dieser
Reihenfolge:

1. **Plan- und Aufgabenlisten**, die in dieser Sitzung entstanden sind, mitsamt
   dem, was noch offen ist.
2. **Dateien, die du angelegt oder geändert hast.** Du weißt, was du angefasst
   hast. Such es nicht im Nachhinein zusammen.
3. **Prozesse, die noch laufen:** Hintergrundbefehle, Entwicklungsserver, Ports,
   offene Branches. Ihre Kennungen sind für den nächsten Chat nicht auffindbar,
   wenn sie hier fehlen.
4. **Entscheidungen mit Begründung.** Nicht nur was gilt, sondern warum, sonst
   wird es im neuen Chat neu diskutiert.
5. **Fragen ohne Antwort:** was du gefragt hast und nie beantwortet wurde, und
   was der Nutzer gefragt hat und du nie beantwortet hast.

## Schritt 2: das Dateisystem NICHT durchsuchen

Kein `git log`, keine breite Dateisuche. Diese Datei ist die Zusammenfassung
dessen, was in **dieser** Sitzung passiert ist. Was du in dieser Sitzung nicht
angefasst hast, gehört nicht hinein.

## Schritt 3: die Datei schreiben

Schreib sie nach `handoff/<JJJJ-MM-TT>-<kurzer-name>.md` im aktuellen Projekt,
Struktur genau nach `references/vorlage.md`. Leg den Ordner an, wenn es ihn noch
nicht gibt.

Warum eine Datei und nicht nur eine Nachricht im Chat: der alte Chat ist
gleich zu. Was nur dort steht, muss der Nutzer von Hand kopieren, und genau das
passiert abends um halb zwölf nicht mehr.

Sag danach in einer Zeile, wo die Datei liegt, und schreib den Satz dazu, den
der Nutzer in den neuen Chat setzt:

    Lies <pfad zur datei> und mach da weiter.

## Schritt 4: gegenlesen

Geh die Datei einmal gegen diese vier Fragen durch, bevor du sie übergibst:

* Steht in jedem Abschnitt etwas, oder hast du einen weggelassen?
* Sind alle Pfade vollständig, also von der Wurzel aus und nicht relativ?
* Steht unter `Was nicht funktioniert hat` etwas Konkretes, oder eine Floskel?
* Könnte jemand, der diese Sitzung nicht erlebt hat, allein damit weitermachen?

## Harte Regeln

1. **Nichts erfinden.** Hat ein Abschnitt keinen Inhalt, schreib "keine". Nicht
   weglassen. Die Struktur muss jedes Mal gleich aussehen, sonst merkt der neue
   Chat nicht, dass etwas fehlt.
2. **Immer vollständige Pfade.** Der nächste Chat startet unter Umständen in
   einem anderen Ordner.
3. **Kennungen von Hintergrundprozessen sind Pflicht**, zusammen mit dem Befehl,
   der sie beendet.
4. **Kein Lob, keine Rückschau, keine Emojis.** Das ist keine Bilanz über die
   Sitzung, sondern eine Schichtübergabe.
5. **Ein einziger nächster Schritt am Ende.** Nicht fünf Empfehlungen. Was danach
   kommt, entscheidet der neue Chat.

## Was dieser Skill nicht tut

* Er ersetzt Compact nicht mitten in der Arbeit. Er ist für das Ende einer
  Sitzung gedacht, nicht für die Mitte.
* Er schreibt keine Dokumentation für andere Menschen. Der Leser ist der nächste
  Chat.
* Er räumt nichts auf und ändert keinen Code, während er die Übergabe schreibt.
