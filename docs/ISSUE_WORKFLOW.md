# GitHub-Issues und Abschluss

## Ein Issue, ein prüfbares Ergebnis

Vor dem Anlegen offene und geschlossene Issues nach Überschneidungen durchsuchen.
Vorhandene Anforderungen ergänzen statt doppelt erfassen. Mehrere unabhängig
lieferbare Ergebnisse gehören in verlinkte Teilaufgaben unter einem Epic.
Epics sind Koordination und kein einzelner Worker-Auftrag.

Jeder Titel nennt Bereich und konkretes Ergebnis. Der Body enthält:

1. **Ziel / Problem:** beobachtetes Verhalten und gewünschtes Ergebnis.
2. **Aktueller Stand:** Datum, genau ein Status und Beleglinks. Ungeprüfte
   Annahmen ausdrücklich als ungeprüft kennzeichnen.
3. **Erledigt:** abgehakte Ergebnisse mit gemergtem PR oder Abnahmebeleg.
4. **Restarbeiten:** offene, konkrete Checkliste; keine bereits erledigten Arbeiten.
5. **Abhängigkeiten:** Parent und tatsächlich blockierende offene Issues.
   Verwandte Referenzen getrennt aufführen. Geschlossene Abhängigkeiten entfernen.
6. **Abnahme:** beobachtbares Ergebnis, erforderliche Tests bzw. Laufzeitnachweise.
7. **Nächster Schritt:** genau eine ausführbare Handlung und Zuständigkeit/Rolle.
8. **Grenzen:** betroffene Komponenten und ausdrücklich ausgeschlossener Umfang.

## Status und Labels

Genau ein `status:*`-Label pro Issue verwenden:

| Label | Bedeutung |
| --- | --- |
| `status:roadmap` | Noch kein ausführbarer Auftrag priorisiert |
| `status:ready` | Klar abgegrenzt, Voraussetzungen erfüllt, nicht begonnen |
| `status:active` | Wird tatsächlich bearbeitet |
| `status:partial` | Belegte Teilergebnisse vorhanden, Rest noch offen |
| `status:waiting` | Wartet auf benannte offene Abhängigkeiten |
| `status:blocked` | Konkreter Fehler oder fehlender Nachweis verhindert Fortsetzung |
| `status:external-action` | Benannter externer Schritt erforderlich |
| `status:verify` | Umsetzung vorhanden, Abnahme steht aus |
| `status:done` | Vollständige Abnahme belegt; Issue schließen |

Zusätzlich passenden Typ und Workstream verwenden. Priorität nach fachlicher
Dringlichkeit vergeben; Agent-Eignung ist keine Priorität. Worker-Labels und
`TIM_QWEN_TASK_V1`-Verträge nur ändern, wenn sich der Ausführungsauftrag ändert.

## Nach Umsetzung und Merge

- PR mit Teilaufgabe verlinken; `Closes #N` nur bei vollständiger Abnahme von #N.
- Erledigten Punkt im Parent abhaken und PR-Beleg ergänzen.
- Verbleibende Integration, Laufzeitprüfung oder externe Schritte konkret nennen.
- Status, Abhängigkeiten und nächsten Schritt im Body aktualisieren. Alte
  Kommentare sind Historie, nicht der aktuelle Arbeitsauftrag.
- Bei widersprüchlicher alter Dokumentation den aktuellen Stand oben erklären;
  ursprüngliche Anforderungen und Sicherheitsgrenzen erhalten.
- Erst schließen, wenn alle Abnahmekriterien erfüllt oder Änderungen am Umfang
  ausdrücklich dokumentiert sind. Ein grüner Modultest beweist keinen Rollout.

## Merge

Nur den geprüften aktuellen PR-Head mergen, wenn alle erforderlichen Checks und
Reviews bestehen und keine bekannten blockierenden Befunde offen sind. Keine
Branch-Protection umgehen. Infrastrukturfehler dürfen erneut ausgeführt werden;
fachliche Fehler müssen vor dem Merge behoben werden. Laufende fremde Arbeiten
vor Änderungen erneut lesen und redaktionelle Änderungen nicht blind überschreiben.
