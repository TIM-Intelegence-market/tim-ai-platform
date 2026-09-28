---
name: session-handoff
description: Erstellt am Sitzungsende eine Übergabedatei für einen neuen Chat oder ein anderes Modell mit Ziel, Stand, Dateien, laufenden Prozessen, Fehlschlägen, offenen Fragen und genau einem nächsten Schritt. Verwenden bei "Übergabe", "Handoff", "neuer Chat", "Stand sichern", "Kontext wird voll", "morgen weitermachen".
---

# Session-Handoff

Quelle: `ai-resources/KI-Ressourcen.md`, Abschnitt „Übergabe an einen neuen Chat“ (Bibliothekseintrag 24, HANDOFF).
Aus dem Prompt der Ressourcendatei abgeleitet, nicht die Originaldatei aus dem ZIP.

## Ablauf

1. Stand aus der Sitzung sammeln: `git status`, `git log`, geänderte Dateien, laufende Prozesse.
2. Datei `ai-resources/handoffs/YYYY-MM-DD-<thema>.md` mit diesen Abschnitten schreiben:
   - **Ziel**
   - **Aktueller Stand**
   - **Wichtige Dateien/Orte** (Branch, Pfade)
   - **Getroffene Entscheidungen**
   - **Laufende Prozesse**
   - **Was nicht funktioniert hat**, mit Grund
   - **Offene Fragen**
   - **Risiken**
   - **Genau ein nächster Schritt**
3. Bestätigte Fakten und Annahmen sichtbar trennen, z. B. mit `[ANNAHME]`.
4. Pfad der Datei nennen. Committen nur, wenn der Nutzer das möchte.

## Regeln

- Keine Zugangsdaten, Tokens oder Passwörter aufnehmen.
- Nichts als erledigt darstellen, was nicht verifiziert wurde.

## Fertig, wenn

- [ ] alle neun Abschnitte vorhanden
- [ ] genau ein nächster Schritt
- [ ] keine Geheimnisse in der Datei
