---
name: canary
description: Setzt zu Beginn eines Chats ein Warnzeichen, an dem du siehst, wann der Gesprächsanfang aus dem Kontextfenster gefallen ist, und übergibt bei Ausfall sauber an einen neuen Chat. Verwenden wenn der Nutzer "Canary", "Kanarienvogel", "Warnzeichen setzen", "langer Chat", "vergisst du gerade was", "fängst du an dir Sachen auszudenken" sagt, oder wenn er eine lange Aufgabe ankündigt.
---

# Canary

Jeder Chat hat ein Kontextfenster, also eine feste Menge Gespräch, die das Modell
auf einmal vor sich hat. Wird sie voll, verschwindet der Anfang. Das Modell sagt
das nicht an. Es antwortet weiter, im selben Ton, in derselben Länge, und füllt
die Lücke mit Plausiblem.

Dieser Skill setzt ein Warnzeichen: einen kurzen Satz ganz oben im Gespräch, der
in jeder Antwort sichtbar wird. Fällt er weg, ist oben etwas verloren gegangen.

## Was der Skill tut

**Schritt 1: den Namen holen.** Wenn der Name des Nutzers nicht bekannt ist,
einmal danach fragen. Ein Wort reicht. Ohne Namen funktioniert das Zeichen nicht,
weil es dann nichts Persönliches gibt, das auffällt, wenn es fehlt.

**Schritt 2: das Zeichen setzen.** Diesen Satz in die laufende Unterhaltung
schreiben, wörtlich, als eigene Zeile:

    Starte ab jetzt jede Antwort mit meinem Namen: <Name>.

Danach jede weitere Antwort in diesem Chat mit dem Namen beginnen, ohne Ausnahme,
auch bei kurzen Antworten und auch mitten in einer Aufgabe.

**Schritt 3: sagen, was es bedeutet.** In zwei Sätzen: solange der Name kommt,
steht der Gesprächsanfang noch im Fenster. Fehlt er, ist oben etwas
herausgefallen, und ab da ist keine Antwort mehr zuverlässig, die sich auf früher
beruft.

**Schritt 4: bei Ausfall übergeben.** Sobald der Name in einer Antwort fehlt,
nicht weiterarbeiten. `references/warnzeichen.md` lesen und den dort
beschriebenen Weg gehen: Stand sichern, neuen Chat aufmachen, Datei mitgeben.

## Wo der Satz NICHT hingehört

Das ist der Teil, an dem der Trick kaputtgeht. Der Satz gehört **ausschließlich
in die laufende Unterhaltung**, sonst nirgendwo.

* **Nicht ins Gedächtnis oder in die Erinnerungsfunktion.** Was dort liegt, wird
  in jeden Chat neu geladen. Dann kommt der Name weiter, obwohl der Anfang längst
  weg ist, und das Zeichen zeigt gar nichts mehr an.
* **Nicht in `CLAUDE.md`, `AGENTS.md`, Projektanweisungen oder Custom
  Instructions.** Derselbe Fehler eine Ebene tiefer. Diese Dateien stehen bei
  jedem Durchlauf oben, auch nach einer Zusammenfassung.
* **Nicht in einen Skill, der automatisch bei jedem Start greift.**

Wer den Satz an eine dieser Stellen schreibt, hat ein Warnzeichen gebaut, das nie
auslöst. Das ist schlechter als keins, weil man sich darauf verlässt.

## Was das Zeichen beweist und was nicht

**Es ist einseitig.** Beides gilt, und der Unterschied ist wichtig:

* **Name fehlt → oben ist sicher etwas verloren.** Darauf ist Verlass.
* **Name kommt → beweist nicht, dass alles noch da ist.** Claude Code und
  claude.ai schneiden bei vollem Fenster nicht einfach ab, sie fassen den älteren
  Teil zusammen. Eine auffällige Anweisung wie diese kann eine Zusammenfassung
  überleben, während Details daneben verschwinden.

Deshalb stehen in `references/warnzeichen.md` zwei weitere Zeichen, die nichts
mit dem Namen zu tun haben. Wer nur auf den Namen guckt, übersieht den häufigeren
Fall.

## Harte Regeln

1. **Den Satz wörtlich setzen**, nicht umformulieren, nicht in einen Absatz
   einbauen. Er muss als Zeile erkennbar bleiben.
2. **Nie heimlich nachsetzen.** Fällt der Name weg und der Skill schreibt den Satz
   einfach neu, ist die Messung zerstört und der Nutzer merkt nichts.
3. **Bei Ausfall keine Zusammenfassung aus dem Kopf.** Was aus dem Fenster ist,
   ist weg. Was der Skill dann noch zusammenfasst, ist geraten.
4. **Keine Prozentzahl zum Füllstand nennen.** Es gibt keine, die im Gespräch
   ablesbar wäre.

## Was dieser Skill nicht tut

* Er vergrößert das Kontextfenster nicht und verhindert nichts. Er warnt.
* Er ersetzt keine Übergabe. Für die gibt es `session-handoff`, und
  `references/warnzeichen.md` verweist an der richtigen Stelle darauf.
* Er misst nichts. Er macht einen Zustand sichtbar, der sonst unsichtbar ist.
