# Wie der fertige Skill aussehen soll

Record & Replay schreibt den Entwurf selbst. Diese Vorlage ist der Maßstab, gegen
den er gelesen wird, nicht etwas zum Abtippen.

Laut Doku ist ein Skill ein Ordner mit einer Datei `SKILL.md` darin, dazu
optional Skripte und weitere Dateien. `name` und `description` sind Pflicht.

## Gerüst

```markdown
---
name: monatsbericht-buchhaltung
description: Baut den Monatsbericht aus dem Kontoexport und legt ihn als Entwurf
  für die Buchhaltung ab. Verwenden wenn der Nutzer nach dem Monatsbericht fragt
  oder einen Monat nennt.
---

# Monatsbericht

## Wann dieser Skill gilt
<ein Satz, woran der Fall zu erkennen ist>

## Was ich vorher wissen muss
- Monat: <wird abgefragt>
- Kontoexport: <Datei, wird abgefragt, Standardordner ~/Downloads>

## Schritte
1. ...
2. ...

## Haltepunkte
- Vor dem Versand an die Buchhaltung: Mail als Entwurf speichern und melden,
  nicht senden.

## Fertig, wenn
<der eine Prüfsatz aus Schritt 4>
```

## Die drei Stellen, an denen ein aufgenommener Skill regelmäßig falsch ist

**1. Eingebrannte Werte.** Im Entwurf steht `oktober.csv`, obwohl jeden Monat
eine andere Datei kommt. Richtig ist ein Platzhalter plus die Angabe, woher der
Wert kommt:

```
Öffne die Datei, die der Nutzer nennt (Beispiel aus der Aufnahme: oktober.csv).
Wenn er keine nennt, frage danach, bevor du anfängst.
```

**2. Fehlende Haltepunkte.** Der Mitschnitt zeigt, dass die Mail rausging, also
schreibt der Entwurf "Mail senden". Das wird ersetzt durch "Mail als Entwurf
anlegen und dem Nutzer sagen, dass sie bereitliegt".

**3. Kein Prüfsatz.** Der Entwurf endet mit dem letzten Klick. Dahinter gehört,
woran ein richtiger Lauf zu erkennen ist.

## Probelauf

Neuer Chat, um den Skill bitten, **andere Werte nennen als in der Aufnahme**.
Die Doku beschreibt genau das: den Skill nennen und die Werte mitgeben, die
diesmal anders sind. Wer mit den Aufnahmewerten prüft, prüft nur, ob das Gerät
seinen eigenen Mitschnitt abspielen kann.
