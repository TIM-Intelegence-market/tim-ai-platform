---
name: playbook-erstellen
description: Macht aus einer wiederkehrenden Aufgabe ein wiederverwendbares Skill-Playbook (Interview, SKILL.md, Ablage, Fertig-Liste, Korrekturen). Verwenden bei "Playbook", "wiederkehrende Aufgabe", "mach daraus einen Skill", "immer gleich ablaufen", "automatisieren", "Ablauf festhalten", "das war falsch, merk dir das".
---

# Playbook-System für wiederkehrende Aufgaben

Quelle: `ai-resources/KI-Ressourcen.md`, Abschnitt „Playbook-System“ (Bibliothekseintrag 3, PLAYBOOK).
Aus den Prompts der Ressourcendatei übernommen, nicht die Originaldatei aus dem ZIP.

## Zielstruktur

```text
.claude/skills/<aufgabe>/
  SKILL.md    Ablauf, Quellen, Regeln, Beispiel, Ablage, Fertig-Liste, Korrekturen
  ablage.md   Index wiederverwendbarer Hilfsmittel
  vorlagen/   neutrale Vorlagen, Textbausteine und Skripte
```

## Ablauf

### 1. Interview
Interviewe den Nutzer, bis der Ablauf zuverlässig beschreibbar ist. **Immer genau eine Frage stellen
und auf die Antwort warten.** Mit dem letzten konkreten Fall beginnen und Schritt für Schritt
durchgehen: Quellen, Werkzeuge, Empfänger, Fehler und Korrekturen, ein gutes Ergebnis, Kriterien für
„fertig“, Schritte, die immer freigegeben werden müssen. Bei vagen Antworten nach einem konkreten
Beispiel fragen. Am Ende Ablauf, Quellen, Regeln, Fehler, anonymisiertes Beispiel und
Fertig-Kriterien zusammenfassen und ehrlich auflisten, was unbekannt ist.

### 2. Playbook erstellen
Aus dem bestätigten Interview `.claude/skills/<aufgabe>/SKILL.md` schreiben:
- YAML-Felder `name` und `description`; die Beschreibung enthält die Alltagswörter, mit denen die
  Aufgabe angefragt wird.
- Abschnitte: Ablauf, Quellen, Regeln, anonymisiertes Beispiel, Fertig-Liste, Korrekturen.
- `[OFFEN]` überall, wo Informationen fehlen. Nichts erfinden.
- Speicherort nennen.

### 3. Ablage
`ablage.md` und `vorlagen/` anlegen. Vor jeder Ausführung den Index lesen und vorhandene Hilfsmittel
nutzen. Nach der Aufgabe prüfen, ob etwas wirklich wiederverwendbar ist; wenn ja, neutral in
`vorlagen/` speichern und Dateiname, Zweck, Datum in `ablage.md` eintragen.
**Keine personenbezogenen Kundendaten oder Geheimnisse ablegen.**

### 4. Fertig-Liste
Höchstens zehn beobachtbare Ja/Nein-Prüfpunkte. Vor jeder Ausgabe jeden Punkt prüfen; bei „Nein“
innerhalb des Auftrags verbessern und erneut prüfen. Unter dem Ergebnis berichten, wie viele Punkte
erfüllt sind und was offen bleibt. Keine Prüfung behaupten, die nicht durchgeführt wurde.

### 5. Korrektur dauerhaft übernehmen
Meldet der Nutzer einen Fehler: bestätigte Regel und betroffenen Abschnitt analysieren, konkrete
Änderung an `SKILL.md` vorschlagen, bei beobachtbarem Fehler einen Prüfschritt ergänzen und unter
„Korrekturen“ Datum, Fehler und neue Regel protokollieren. Keine weiteren Dateien ändern. Änderung
zeigen, dann die Aufgabe mit der korrigierten Anleitung wiederholen. Bei Unklarheit gezielt nachfragen.

### 6. Testlauf
In einer neuen Sitzung einen ungefährlichen, repräsentativen Testfall mit anderen Werten ausführen,
ohne das Playbook namentlich anzufordern. Berichten, ob es automatisch gewählt wurde, welche Regeln
angewandt wurden und was offen blieb. Wurde es nicht gewählt: bessere `description` mit echten
Alltagsbegriffen vorschlagen und erst nach Zustimmung ändern.

## Fertig, wenn

- [ ] Interview-Zusammenfassung vom Nutzer bestätigt
- [ ] `SKILL.md` mit `name`, `description` und allen Abschnitten, Lücken als `[OFFEN]`
- [ ] `ablage.md` und `vorlagen/` vorhanden, ohne personenbezogene Daten
- [ ] Fertig-Liste mit höchstens zehn beobachtbaren Punkten
- [ ] Speicherort genannt
