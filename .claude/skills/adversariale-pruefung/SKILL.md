---
name: adversariale-pruefung
description: Prüft eine Änderung unabhängig und kritisch auf Logikfehler, Sonderfälle, Sicherheitslücken und stille Annahmen, ohne selbst etwas zu ändern. Verwenden bei "prüf die Änderung", "Review", "zweite Prüfung", "Gegenprüfung", "findest du Fehler", "Vier-Augen-Prinzip", "ist das sicher".
---

# Adversariale Prüfung nach einer Änderung

Quelle: `ai-resources/KI-Ressourcen.md`, Abschnitt „Adversariale Prüfung nach einer Änderung“.
Aus dem Prompt der Ressourcendatei übernommen, nicht die Originaldatei aus dem ZIP.

## Ablauf

1. Knapp zusammenfassen, **was geändert wurde** (z. B. `git diff`) und **welche Anforderungen** gelten.
2. Unabhängig prüfen auf:
   - Logikfehler
   - Sonderfälle und Randwerte
   - Sicherheitslücken
   - stille Annahmen
3. Für jeden möglichen Fund: **konkretes Fehlerszenario** (Eingabe/Zustand → falsches Ergebnis)
   und betroffene Stelle als `datei:zeile`.
4. Funde einteilen in **bestätigt**, **Fehlalarm** und **unsicher**.
5. Je bestätigtem Problem den kleinsten sinnvollen Fix und die passende Verifikation empfehlen.

## Regeln

- **Selbst keine Änderungen vornehmen.**
- Nur behaupten, was am Code oder durch einen ausgeführten Test belegt ist.

## Fertig, wenn

- [ ] Änderung und Anforderungen zusammengefasst
- [ ] jeder Fund mit Szenario und Stelle
- [ ] Funde als bestätigt / Fehlalarm / unsicher markiert
- [ ] Fix- und Prüfempfehlung je bestätigtem Problem
