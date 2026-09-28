# Herkunft und Wahrheitsgrenze

## Woher die Idee stammt

Der Trick ist nicht erfunden, sondern übernommen. Quelle ist ein Reel von
**mavgpt vom 02.09.2026** (instagram.com/reel/DcyRFvQz-N9), dort auf Englisch und
ohne Skill: der Zuschauer schreibt die Anweisung von Hand in den Chat.

**Drei Punkte aus dem Original sind bewusst NICHT übernommen**, weil sie den
Trick aufheben oder nichts beschreiben:

* *"Save this to your memory."* Was im Gedächtnis liegt, wird in jeden Chat neu
  geladen und fällt nie mit dem Anfang heraus. Der Name käme dann weiter, obwohl
  der Kontext längst gekürzt ist.
* *"Put this exact line in any instruction files."* Derselbe Fehler eine Ebene
  tiefer. Eine Zeile in `CLAUDE.md` steht bei jedem Durchlauf oben, auch nach
  einer Zusammenfassung.
* *"Your session starts to degrade."* Ein Wort ohne Bild. In diesem Skill steht
  stattdessen, was passiert: der obere Teil des Gesprächs ist nicht mehr
  vollständig vorhanden.

Der deutsche Text, die drei Warnzeichen und der Übergabeweg sind eigener Text.

## Was gemessen ist

* Der Skill führt nichts aus. Er liest, schreibt einen Satz in die Unterhaltung
  und verweist auf eine zweite Datei. Deshalb läuft er in Claude Code genauso wie
  in Claude.ai und Cowork.
* Das ZIP wurde gegen den Quellordner gelesen und enthält `SKILL.md`,
  `references/warnzeichen.md` und diese Datei.

## Nicht gemessen

Dieser Abschnitt ist der wichtigere. Wer den Skill benutzt, soll wissen, worauf
er sich nicht verlassen kann.

* **Es gibt keinen eigenen Überlauftest.** Es wurde kein Chat kontrolliert über
  das Kontextfenster getrieben und dabei protokolliert, ob der Namenssatz
  tatsächlich als Erstes ausfällt. Der Satz "er fällt zuerst heraus" stammt aus
  dem Original-Reel und ist hier nicht nachgemessen.
* **Deshalb ist das Zeichen im Skill einseitig formuliert.** Name fehlt heißt,
  oben ist etwas verloren. Name kommt heißt nicht, dass alles noch da ist. Claude
  Code und claude.ai schneiden bei vollem Fenster nicht hart ab, sie fassen den
  älteren Teil zusammen. Eine auffällige Anweisung kann eine Zusammenfassung
  überleben, während Details daneben verschwinden. Genau dafür stehen Zeichen 2
  und 3 in `references/warnzeichen.md`.
* **Es ist nicht verglichen, ob sich Claude Code, claude.ai und Cowork gleich
  verhalten.** Die drei kürzen unterschiedlich, gemessen ist keins davon.
* **Es ist nicht gezählt, wie oft das Modell die Anweisung schlicht vergisst,
  ohne dass das Fenster voll ist.** Ein ausbleibender Name kann auch daran
  liegen. Das erzeugt einen Fehlalarm, kein übersehenes Problem.
* **Der Skill ist neu und nicht über Wochen gelaufen.** Er ist am 21.09.2026
  gebaut worden.

## Rechte

Die Idee stammt aus einem öffentlichen Instagram-Reel und ist mit Quelle genannt.
Der Text ist eigener Text. Es besteht keine Verbindung zu Anthropic und keine zu
mavgpt.
