---
name: bauplan
description: Plant eine größere Aufgabe vor jeder Änderung - Ziel, überprüfbare Pakete, Nicht-Ziele, Abhängigkeiten, Risiken und Prüfbefehle - und wartet auf Freigabe. Verwenden bei "Bauplan", "plan das erst", "größere Aufgabe", "neues Feature", "Umbau", "Projekt starten", "bevor du baust".
---

# Bauplan vor Implementierung

Quelle: `ai-resources/KI-Ressourcen.md`, Abschnitt „Bauplan vor Implementierung“ (Bibliothekseintrag 29).
Aus dem Prompt der Ressourcendatei übernommen, nicht die Originaldatei aus dem ZIP.

## Ablauf

1. Aufgabe verstehen: vorhandenen Code, `CLAUDE.md` und Projektregeln lesen. **Noch nichts ändern.**
2. Kompakten Plan zeigen:
   - **Ziel** in 2–5 Sätzen
   - **Pakete** in Reihenfolge, jedes überprüfbar, mit:
     - Verantwortlichkeit (wer/welcher Agent, welche Dateien)
     - Prüfschritt mit konkretem Befehl oder Test
     - erwartetes Ergebnis
   - **Nicht-Ziele** (explizit)
   - **Abhängigkeiten**
   - **Größte Risiken**
3. **Auf das Go des Nutzers warten.**
4. Pakete nacheinander umsetzen; nach jedem Paket wie geplant verifizieren und das beobachtete
   Ergebnis berichten.
5. Größere Änderungen zusätzlich unabhängig prüfen (Skill `adversariale-pruefung`).

## Regeln

- Keinen Erfolg ohne sichtbaren Nachweis behaupten.
- Weicht die Umsetzung vom Plan ab: anhalten, Abweichung nennen, Plan anpassen lassen.
- Bei parallelen Agenten Dateibesitz pro Paket festlegen; nie zwei an derselben Datei.

## Fertig, wenn

- [ ] Plan mit allen fünf Teilen gezeigt und freigegeben
- [ ] jedes Paket mit ausgeführtem Prüfschritt und Ergebnis
- [ ] Abweichungen und offene Risiken genannt
