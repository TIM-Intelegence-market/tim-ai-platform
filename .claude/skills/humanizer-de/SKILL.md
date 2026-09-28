---
name: humanizer-de
description: Nutzen, wenn ein deutscher Text vor dem Veröffentlichen auf KI-Klang geprüft oder in der eigenen Stimme neu geschrieben werden soll (Post, Mail, Kommentar, Video-Skript, Webseitentext). Auch bei "klingt das nach KI", "menschlicher machen", "KI-Floskeln raus", "schreib das in meiner Stimme". Deutscher Layer zum englischen humanizer-Skill.
---

# humanizer-de

## Wozu es diesen Skill gibt

Der englische `humanizer` prüft Struktur: Ankündigungen, Aphorismen, Dreierregel, symmetrische Pointen, Gedankenstriche. Das greift in jeder Sprache.

Seine Wortlisten sind aber englisch. Auf einem deutschen Text finden sie so gut wie nichts, weil "delve", "tapestry" oder "testament" dort nicht vorkommen. Die deutschen Gegenstücke heißen "eintauchen", "ganzheitlich" und "Es ist wichtig zu beachten". Für genau diese Lücke ist dieser Skill da.

**Der Job hat zwei Seiten.** KI-Muster raus ist die eine. Die Stimme des Menschen drin lassen ist die andere, und die ist schwerer. **Das größere Risiko ist Überkorrektur, nicht ein übersehenes Muster.**

## Reihenfolge

1. Erst `humanizer` (englisch) für die Struktur.
2. Dann dieser Skill für die deutsche Wort- und Mechanik-Ebene.
3. Wenn eigene Texte vorliegen: Stimm-Abgleich (unten) vor dem Neuschrieb.

## Stimm-Abgleich mit eigenen Texten

Ohne eigene Texte kann der Skill nur Muster entfernen. Mit drei bis fünf echten Texten der Person (alte Posts, Mails, Sprachnachricht als Transkript) schreibt er in ihrer Stimme neu. Das ist der Teil, der den Unterschied macht.

**So läuft es:**

1. Die Texte zuerst lesen, bevor irgendetwas geändert wird.
2. Eine Stimm-Signatur als Tabelle festhalten: Satzlänge, typische Satzanfänge, Lieblingsverben, Satzzeichen, wiederkehrende Wendungen, wie Absätze beginnen und enden, wie direkt oder vorsichtig die Person formuliert.
3. Die Signatur schlägt jede Stilregel in diesem Skill. Schreibt die Person selbst Gedankenstriche oder "nicht nur, sondern auch", bleiben sie in ungefähr der Häufigkeit ihrer eigenen Texte.
4. Im Neuschrieb nichts aufwerten: umgangssprachliche Wörter bleiben umgangssprachlich, Eigenheiten bleiben Eigenheiten.

**Muster, die oft Stimme sind und keine KI:**

| Muster | Beispiel | Warum es bleibt |
|---|---|---|
| Subjektlose Kurzsätze | "Klingt banal." · "Stimmt schon." · "Ist auch keiner." | Gesprochener Rhythmus. Der englische Skill will die ausbauen, im Deutschen ist das falsch |
| Satzanfang mit Konjunktion | "Nur sitzt genau da..." · "Denn niemand tippt..." | Erzeugt den gesprochenen Ton, kein Grammatikfehler |
| Derbe, konkrete Verben | frisst, versickert, kippt, liegt brach | Das Gegenteil von KI-Vokabular. Nie gegen blassere Wörter tauschen |
| Selbstironische Einschübe | "Hätte ich nicht gedacht. Ist auch kein Lob." | Echtes Menschsignal, nie kürzen |
| Ungleiche Absatzlängen | ein Satz, dann fünf, dann zwei | Gleichmäßige Absätze sind selbst ein KI-Muster |

**Regel:** Steht ein Fund in der Stimm-Signatur der Person, ist es kein Fund.

## Deutsche KI-Muster

### 1. Floskel-Einstiege
**Wörter:** In der heutigen Zeit · In der heutigen schnelllebigen Welt · In einer Welt, in der · Immer mehr Menschen fragen sich · Stell dir vor
**Fix:** Ersatzlos streichen. Der Satz danach ist fast immer der echte Anfang.

### 2. Kommentare über den eigenen Text
**Wörter:** Es ist wichtig zu beachten · Es ist bemerkenswert · Es ist erwähnenswert · Es lässt sich nicht leugnen · Es versteht sich von selbst · Eines ist klar
**Problem:** Der Text kündigt Wichtigkeit an, statt wichtig zu sein.
**Vorher:** Es ist wichtig zu beachten, dass beide Zahlen aus derselben Umfrage stammen.
**Nachher:** Beide Zahlen stammen aus derselben Umfrage.

### 3. Zusammenfassungs-Floskeln
**Wörter:** Zusammenfassend lässt sich sagen · Abschließend lässt sich sagen · Im Großen und Ganzen · Fazit · Unterm Strich
**Fix:** Streichen und mit dem letzten konkreten Punkt enden.

### 4. Konjunktions-Stapel
**Wörter:** Darüber hinaus · Zusätzlich · Außerdem · Ferner · Des Weiteren · Nicht zuletzt
**Problem:** Einzeln harmlos. Zwei in einem kurzen Text sind auffällig, drei sind eine Signatur.
**Fix:** Punkt und neuer Satz. Deutsch braucht die Brücke seltener als Englisch.

### 5. Negative Parallelismen
**Wörter:** nicht nur X, sondern auch Y · Es geht nicht um X, sondern um Y · Es ist nicht X. Es ist Y. · weniger X als vielmehr Y
**Vorher:** Es geht nicht um bessere Tools, sondern um klare Abläufe.
**Nachher:** Bessere Tools lösen das nicht. Was fehlt, sind klare Abläufe.

**Abgrenzung, sonst gibt es Dutzende Fehlalarme:** "nicht A, sondern B" ist normales Deutsch, wenn B eine echte Korrektur von A ist und beide konkret sind. "Nicht weil es schlecht war, sondern weil nie jemand den langweiligen Teil gemacht hat" bleibt. Das Muster ist die aufgeblasene Variante: abstrakt, symmetrisch, als Pointe gebaut. Prüffrage: steht die Konstruktion für eine echte Unterscheidung oder nur für Rhythmus?

### 6. Überbetonung von Bedeutung
**Wörter:** spielt eine entscheidende Rolle · unterstreicht die Bedeutung · ist ein Zeugnis für · Wendepunkt · Meilenstein · Gamechanger · ebnet den Weg für · eine neue Ära
**Fix:** Den konkreten Vorgang hinschreiben, die Bewertung weglassen.

### 7. Werbe-Adjektive
**Wörter:** revolutionär · bahnbrechend · maßgeschneidert · nahtlos · ganzheitlich · essenziell · vielfältig · innovativ · zukunftsweisend · leistungsstark · Mehrwert · Synergien · leidenschaftlich
**Fix:** Streichen oder durch eine prüfbare Angabe ersetzen, wenn die im Original steht.

### 8. Eintauch- und Aufstiegs-Verben
**Wörter:** eintauchen · Tauchen wir ein · beleuchten · auf ein neues Level heben · den Grundstein legen · Potenzial ausschöpfen · Türen öffnen
**Fix:** Sagen, was tatsächlich passiert.

### 9. Partizip-Anhängsel
**Wörter:** gewährleistend · hervorhebend · widerspiegelnd · unterstreichend · ermöglichend
**Problem:** Direkte Übersetzung des englischen "-ing"-Anhängsels. Im Deutschen klingt es noch steifer.
**Vorher:** Der Prozess wurde vereinfacht, die Bearbeitungszeit halbierend.
**Nachher:** Der Prozess wurde vereinfacht. Die Bearbeitung dauert jetzt halb so lang.

### 10. Vage Autoritäten
**Wörter:** Experten sind sich einig · Studien zeigen (ohne Studie) · Branchenberichte · Es wird oft gesagt
**Fix:** Quelle benennen oder Satz streichen. Nie eine Quelle erfinden, um den Satz zu retten.

### 11. Höflichkeits- und Engagement-Floskeln
**Wörter:** Es freut mich, mit euch zu teilen · Ich bin gespannt auf eure Gedanken · Was denkt ihr? · Lasst es mich wissen · Ein herzliches Dankeschön an alle, die
**Fix:** Weg. Der Text endet mit seiner Aussage.

### 12. Generische Hooks
**Wörter:** 3 Dinge, die ich gelernt habe · Diese eine Sache hat alles verändert · X Lektionen aus Y · Kurzer Reminder
**Fix:** Durch ein Zitat, eine harte Zahl oder einen Einwand aus dem Original ersetzen.

### 13. Dreierregel
**Muster:** drei Adjektive in Reihe · drei Bullets, drei Tipps, drei Schritte, obwohl es zwei oder vier sind
**Fix:** Auf zwei kürzen oder auf die echte Zahl bringen. Der dritte Punkt ist meistens der schwächste.

### 14. Kann-Inflation und Absicherung
**Wörter:** kann (mehrfach pro Absatz) · könnte möglicherweise · unter Umständen · tendenziell · durchaus
**Fix:** Eine Abschwächung pro Aussage reicht.

## Deutsche Mechanik

### Lehnübersetzungen
| Auffällig | Deutsch |
|---|---|
| in 2026 | 2026, im Jahr 2026 |
| macht Sinn | ergibt Sinn |
| am Ende des Tages | letztlich, oder weglassen |
| ein Problem adressieren | angehen, lösen |
| realisieren (begreifen) | merken, begreifen |

### Typografie
- **Gedankenstriche** (`—` und `–` als Einschub) sind der bekannteste KI-Hinweis. Ersatz in dieser Reihenfolge: Punkt, Komma, Doppelpunkt, Klammer, Satz umbauen. Ausnahme: die Person schreibt sie selbst (Stimm-Abgleich).
- **Anführungszeichen einheitlich.** Pro Text eine Variante, „so“ oder "so", nie mitten im Text wechseln.
- **Keine Emoji-Listen** und keine Fett-Inflation.
- **Keine absichtlichen Tippfehler.** Fehler einbauen, um menschlicher zu wirken, ist selbst ein erkennbares Muster.

## Fehlalarme

- **Ein einzelnes "außerdem".** Erst die Häufung ist ein Muster.
- **Korrektes Deutsch.** Sauberer Satzbau beweist nichts.
- **Fachwörter aus dem Beruf.** Prozess, Workflow, Pilot, Case Study sind normale Sprache.
- **Ein kurzer Satz zur Betonung.** Erst eine Serie davon wird Staccato.
- **Zitate und Beispiele.** Steht ein Muster in einem wörtlichen Zitat, bleibt es.
- **Wiederholung eines Begriffs.** Deutsch verträgt Wiederholung besser als Englisch. Synonym-Zwang ist selbst ein Muster.

## Ausgabe

Immer diese vier Teile, in dieser Reihenfolge:

1. **Funde.** Pro Fund: Kategorie-Nummer, die Stelle wörtlich, warum sie ein Muster ist. "Keine" ist ein gültiges Ergebnis.
2. **Bewusst nicht angefasst.** Mindestens ein Eintrag, sobald der Text Muster aus der Stimm-Signatur enthält. Das erzwingt die Prüfung gegen Überkorrektur.
3. **Neuschrieb.** Vollständiger Text, keine Auslassungen, keine Platzhalter, keine neuen Fakten. Jede Zahl, jeder Name, jedes Datum kommt aus dem Original.
4. **Prüfzeile.** "Fakten unverändert: ja/nein · Gedankenstriche: Anzahl · Stimme intakt: ja/nein". Bei einem "nein" ist der Neuschrieb nicht fertig.

Bei null Funden wird nicht umgeschrieben. Ein sauberer Text bleibt, wie er ist.

## Was dieser Skill nicht verspricht

- **Er schlägt keine KI-Detektoren.** Weder dieser noch der englische Skill ist darauf gebaut oder daran gemessen.
- **Er entfernt kein Wasserzeichen durch Löschen.** Anthropic beschreibt sein Wasserzeichen als Muster in der Wortwahl ohne versteckte Zeichen, das leichte Änderungen übersteht. Ein Neuschrieb in eigener Stimme verändert die Wortwahl gründlich, ob das im Einzelfall für die Erkennung reicht, ist nicht gemessen.
- **Er erfindet keine Erfahrungen.** Braucht ein Satz ein echtes Detail, fragt der Skill danach, statt eins auszudenken.
