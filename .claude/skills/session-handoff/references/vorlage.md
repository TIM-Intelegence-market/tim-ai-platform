# Die Vorlage

Diese Struktur wird jedes Mal benutzt, in dieser Reihenfolge, ohne Abschnitte
wegzulassen. Hat ein Abschnitt nichts zu melden, steht dort "keine".

```markdown
# Übergabe: <ein Satz, worum es in dieser Sitzung ging>

Datum: <JJJJ-MM-TT>
Projekt: <vollständiger Pfad zum Projektordner>

## Wo es anfing

<Zwei bis drei Sätze: was der Nutzer wollte, welche Vorgaben oder Grenzen
unterwegs dazukamen.>

## Entschieden und gebaut

- <Entscheidung oder Änderung> — <warum, und wo sie liegt (vollständiger Pfad)>

## Was nicht funktioniert hat

- <Weg, Ansatz oder Werkzeug> — <woran es scheiterte, und was daraus folgt>

## Wichtige Dateien für den nächsten Chat

- `<vollständiger Pfad>` — <warum das zuerst gelesen wird>

## Was gerade läuft

- Hintergrundprozesse: <Kennung + was es ist + Befehl zum Beenden> — oder "keine"
- Server und Ports: <Adresse + Port> — oder "keine"
- Branches und Arbeitskopien: <Pfade> — oder "keine"

## Prüfen, ob noch alles steht

- `<Befehl>` — <was dabei herauskommen muss>

## Offen und verschoben

- Verschoben: <Sache> — <warum nach hinten>
- Offen: <Frage, die der Nutzer beantworten muss> — <Zusammenhang>

## Hier weitermachen

<Ein bis zwei Sätze: die eine wahrscheinlichste nächste Handlung.>
```

## Zu den einzelnen Abschnitten

**Wo es anfing.** Der Auftrag, nicht der Verlauf. Wer das liest, muss verstehen,
warum die Entscheidungen darunter so ausgefallen sind.

**Entschieden und gebaut.** Eine Zeile je Sache. Die Begründung gehört dazu, sonst
wird die Entscheidung im neuen Chat noch einmal aufgemacht. Der Pfad gehört dazu,
sonst wird gesucht.

**Was nicht funktioniert hat.** Der wichtigste Abschnitt. Hier stehen die
Sackgassen: der Ansatz, der abgebrochen wurde, die Bibliothek, die es nicht
konnte, der Befehl, der einen Fehler warf, die Idee, die der Nutzer abgelehnt hat.
Zu jedem Punkt der Grund. Ein neuer Chat ohne diesen Abschnitt läuft dieselben
Wege noch einmal ab, und der Nutzer zahlt sie ein zweites Mal.

Nicht ausreichend: "einige Ansätze haben nicht geklappt".
Ausreichend: "Variante über den Cache verworfen, weil zwei Läufe gleichzeitig
denselben Stand überschreiben. Ohne Sperre nicht reparierbar."

**Wichtige Dateien.** Höchstens eine Handvoll, nach Lesereihenfolge sortiert. Gibt
es eine Plandatei, steht sie an erster Stelle.

**Was gerade läuft.** Der Abschnitt, der am häufigsten fehlt, weil "läuft ja
nichts". Dann steht dort dreimal "keine". Das ist die Information, nicht ihr
Fehlen.

**Prüfen.** Befehle, mit denen der neue Chat in einer Minute feststellt, ob der
beschriebene Stand noch stimmt. Immer mit dem erwarteten Ergebnis, sonst kann er
die Ausgabe nicht einordnen.

**Offen und verschoben.** Getrennt halten. Verschoben heißt: bewusst später.
Offen heißt: hängt an einer Antwort des Nutzers.

**Hier weitermachen.** Genau eine Handlung. Eine Liste mit fünf Empfehlungen ist
keine Übergabe, sondern eine neue Planung.
