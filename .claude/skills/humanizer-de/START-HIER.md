# Humanizer: die KI-Handschrift aus deinem Text

Zwei Skills für Claude. Der erste prüft die Struktur (33 Muster, englisch), der
zweite die deutsche Wort- und Satzebene. Zusammen schreiben sie einen Text neu,
ohne dass Fakten verloren gehen oder dazukommen.

## Einbauen

**Claude Code, Mac und Linux.** Im entpackten Ordner ein Terminal öffnen:

```bash
mkdir -p ~/.claude/skills && cp -R humanizer humanizer-de ~/.claude/skills/
```

**Claude Code, Windows.** Die Ordner `humanizer` und `humanizer-de` nach
`C:\Users\DEINNAME\.claude\skills\` kopieren.

**Claude-App oder claude.ai.** Einstellungen, Fähigkeiten, Skills, Skill hochladen.
Jeder Skill wird einzeln als ZIP hochgeladen: den Ordner `humanizer` zippen und
hochladen, dann dasselbe mit `humanizer-de`.

Danach Claude neu starten und fragen, welche Skills es hat. Beide müssen in der
Liste stehen.

## Benutzen

```text
Prüf diesen Text mit humanizer und humanizer-de und schreib ihn neu:
[Text]
```

Der Teil, der den Unterschied macht:

```text
Hier sind drei Texte, die ich selbst geschrieben habe. Lies sie zuerst und halt
meine Stimme fest. Dann schreib den folgenden Text mit humanizer und humanizer-de
in genau dieser Stimme neu.
[eigene Texte]
[Text]
```

## Was es nicht kann

Es schlägt keine KI-Detektoren und ist nie dagegen gemessen worden. Warum ein
Neuschrieb trotzdem mehr bringt als ein "Watermark Remover", steht in
`HERKUNFT.md`.
