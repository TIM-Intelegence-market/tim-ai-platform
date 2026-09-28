# Herkunft und Wahrheitsgrenze

## Die zwei Skills

**`humanizer/`** ist der Skill von Siqi Chen, Repo `github.com/blader/humanizer`,
MIT-Lizenz, unverändert in Version 2.9.1 (identisch mit Commit `dcdc103` im Repo).
Die Lizenz liegt daneben als `LICENSE` und muss bei jeder Weitergabe mit.
Er prüft gegen 33 Muster, abgeleitet aus der englischen Wikipedia-Seite
"Wikipedia:Signs of AI writing" des WikiProject AI Cleanup.

Stand 17.09.2026: im Repo liegt inzwischen Version 3.0.0 vom 06.09.2026. Dort sind
die Muster neu sortiert und auf 25 zusammengefasst. Hier liegt bewusst 2.9.1, weil
das die Fassung ist, die im Video gezeigt wird und die im Einsatz war. Wer die
neueste will, holt sie direkt aus dem Repo.

**`humanizer-de/`** ist eigene Arbeit. Die englischen Wortlisten finden auf
deutschen Texten praktisch nichts, dieser Skill ergänzt die deutschen
Gegenstücke, die deutsche Mechanik (Lehnübersetzungen, Typografie) und den
Stimm-Abgleich mit eigenen Texten. Entstanden am 26.07.2026 für den eigenen
Gebrauch, am 17.09.2026 für die Weitergabe von allen persönlichen Bezügen befreit.

## Das Wasserzeichen

Anthropic, Beitrag "claude-text-watermark" vom 14.08.2026 auf anthropic.com, am
17.09.2026 abgerufen:

* "Future Claude models will generate text that contains a watermark."
  Angekündigt für künftige Modelle, nicht rückwirkend für jeden Text.
* "Nothing is added to the text and there are no hidden characters." Das Muster
  sitzt in der Wortwahl, nach dem SynthID-Text-Verfahren von Google DeepMind.
* Leichte Änderungen lassen es stehen, "a complete rewrite where every word is
  replaced" entfernt es.
* Erkennen können es nur berechtigte Stellen nach EU-Recht (Behörden, Medien,
  Faktenprüfer, Forschung). Grundlage ist der EU Code of Practice on Transparency
  of AI-Generated Content, von Anthropic im Juli 2026 unterzeichnet.

Daraus folgt: Programme, die "unsichtbare Zeichen" aus einem Text löschen, löschen
nicht dieses Wasserzeichen. Gegengeprüft am 16.09.2026 an 75 Dateien, die Claude
geschrieben hat: null Zero-Width Spaces, null schmale geschützte Leerzeichen.

## Nicht gemessen, ausdrücklich

* **Kein Detektor-Test.** Weder `humanizer` noch `humanizer-de` wurde gegen einen
  KI-Detektor oder Anthropics Erkennung gefahren. Die Erkennung ist für
  Privatleute nicht zugänglich. Der englische Skill verspricht das selbst nicht.
* **Ob ein Neuschrieb das Wasserzeichen im Einzelfall entfernt, ist nicht
  gemessen.** Belegt ist nur Anthropics Aussage, dass ein vollständiger
  Neuschrieb es tut und leichte Änderungen nicht.
* **Der Stimm-Abgleich ist nicht systematisch verglichen.** Er wurde an eigenen
  Texten benutzt, nicht in einem Blindtest gegen Texte ohne Abgleich.

## Rechte

`humanizer` steht unter MIT-Lizenz, Copyright (c) 2025 Siqi Chen. `humanizer-de`
ist eigener Text. Keine Verbindung zu Anthropic, Wikipedia oder dem Autor des
englischen Skills.
