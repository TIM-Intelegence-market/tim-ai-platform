# GoatHub-Kanal: vollständig in Claudes Memory, gute Calls für TIM

Status: Community-Meinung, nur Beobachtung. TIM führt GoatHub als Quellenklasse
`HUMAN_COMMUNITY_TRADING_RESEARCH`: menschliche Trading-Forschung, gelesen als Hypothese mit Autor, Zeit und Beleg. Ergänzt den [Broncx-Feed](BRONCX_DISCORD_FEED.md),
der Broncx' Beiträge aus The Goat Hub gewichtet. Dieser Feed nimmt den ganzen Kanal mit allen Autoren.

## Was passiert

1. `scripts/goathub_discord_bot.py sync` liest jeden eingetragenen Kanal bis zur neuesten Nachricht.
   Beim ersten Lauf holt er den ganzen Verlauf (bis 10 000 Nachrichten je Kanal und Lauf, der Rest
   folgt beim nächsten Lauf). Gespeichert wird lokal in `data/goathub_feed/messages.jsonl` (nicht committet).
2. Danach schreibt er nach `data/goathub_feed/memory/`:
   - `GOATHUB_KANAL.md`: der ganze Kanal, wörtlich, nach Kanal und Tag, oben die guten Calls
   - `GOATHUB_KURZ.md`: Kurzfassung unter 4 KB für einen Memory-Index
   - `goathub_calls.json`: die guten Calls mit erkannter Richtung, Symbol, Level und Invalidierung
   Mit `--memory-dir <Ordner>` (mehrfach möglich) landen dieselben Dateien zusätzlich dort.
3. launchd startet `sync` dreimal täglich (07:05, 13:05, 21:05 Ortszeit, `ops/launchd/com.tim.goathub-sync.plist`).
4. Eine Claude-Routine im TIM-Projekt liest den Export danach vom Mac und aktualisiert
   `/mnt/project-files/goathub/` und den Memory-Eintrag `goathub-kanal`.
5. `ofsc --goathub-feed data/goathub_feed` zeigt die guten Calls zum analysierten Symbol im Bericht
   unter **HUMAN-COMMUNITY-TRADING-RESEARCH**, mit Level-Prüfung gegen die Kerzen (TOUCHED / NOT_REACHED)
   und Invalidierung per Schlusskurs.

## Was ein guter Call ist

Ein Call ist eine Nachricht mit aktueller Richtung (LONG/SHORT). Verneinte oder geschlossene
Positionen („closed my short“) und Squeeze-Wörter zählen nicht. Die Erkennung nutzt dieselben
Muster wie der Broncx-Feed und erkennt zusätzlich jede Coin nach „long/short/buy“ oder als Paar
(„MOVR/USDT“). Prozent- und Größenangaben („2-5% of account“) gelten nie als Level, „SL on 1.5$“
und „SL … to 0.48“ als Stop. Eine Liste mehrerer Coins nennt kein einzelnes Symbol und bleibt Note C.

| Note | Bedeutung |
| --- | --- |
| A | Richtung, Symbol, Level und Invalidierung oder Stop |
| B | Richtung, Symbol und Level oder Stop (z. B. „Long HNT from here with SL 0.5“) |
| C | der Rest (kein Symbol oder kein Level), gilt nicht als guter Call |

Die Note sagt nur, wie vollständig ein Call geschrieben ist, nicht ob er stimmt. Reaktionen
(ab 3) stehen als Hinweis dabei, ändern die Note aber nicht.

## Was TIM damit darf

| Darf | Darf nicht |
| --- | --- |
| gute Calls zum analysierten Symbol im Bericht und Audit zeigen (`engine: community_calls`) | Scores gewichten oder Szenarien anlegen (`influences_scores: false`) |
| Level gegen die Kerzen nach dem Call prüfen | als Bestätigung zählen oder die Entscheidung ändern |
| Invalidierung mit Zahl per Schlusskurs prüfen | Calls nutzen, die nach dem Analysezeitpunkt gepostet oder empfangen wurden |
| | Calls älter als die Frist (Standard 24 h, `--goathub-max-age-hours`) zeigen |

Anders als Broncx haben Community-Autoren in TIM noch keine Trefferquote. Eine Gewichtung wäre
erst nach einer Auswertung sinnvoll, welche Autoren mit ihren Calls richtig lagen.

## Zwei Wege an den Kanal

| Modus | Wie | Vollständig? |
| --- | --- | --- |
| `direct` | Ein Admin von The Goat Hub lädt den TIM-Bot in den Server ein (Rechte *View Channels* und *Read Message History*, nur für die gewünschten Kanäle). Der Bot liest dann alle Nachrichten mit Autor und Reaktionen. | ja |
| Folgen (im Modus `forward`) | Ist der GoatHub-Kanal ein Ankündigungskanal (Megafon-Symbol), zeigt Discord oben **Folgen**. Du wählst als Ziel deinen Kanal im TIM-Server, dafür brauchst du dort „Webhooks verwalten“, keinen GoatHub-Admin. Discord postet jede neue Nachricht automatisch in deinen Kanal, der Bot übernimmt sie (Quelle `discord_follow`). | alle neuen Nachrichten ab dem Folgen, ohne Autor des Einzelbeitrags |
| `forward` (Standard) | Du leitest Beiträge per **Weiterleiten** in einen eigenen Kanal im TIM-Server, wie beim Broncx-Feed. Nur deine Nutzer-ID wird angenommen, der ursprüngliche Autor fehlt. | nur was du weiterleitest |

Ein Bot kann einen fremden Server nicht ohne Einladung lesen, und ein eigenes Discord-Konto
automatisch mitlesen zu lassen verstößt gegen die Discord-Regeln. Den ganzen Kanal gibt es deshalb
nur im Modus `direct`.

## Einrichtung

Voraussetzung: der Broncx-Bot ist eingerichtet (gleiches Bot-Geheimnis, siehe Broncx-Doku).
Im Discord-Entwicklerportal muss **Message Content Intent** an sein.

```sh
cd ~/Documents/TIM/tim-broncx-feed
git pull --ff-only origin platform-main
.venv/bin/python scripts/goathub_discord_bot.py setup   # Kanal-ID(s), Modus, deine Nutzer-ID
.venv/bin/python scripts/goathub_discord_bot.py sync    # erwartet: stored=… complete=True
.venv/bin/python scripts/goathub_discord_bot.py calls   # zeigt die guten Calls
cp ops/launchd/com.tim.goathub-sync.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.tim.goathub-sync.plist
```

Mehrere Kanäle bei `setup` mit Komma trennen, optional mit Namen: `1234…=calls,5678…=general`.
Das Log steht in `data/operational/goathub_sync.log`. Stoppen:
`launchctl bootout gui/$(id -u)/com.tim.goathub-sync`.

Einstellbar per Umgebungsvariable: `TIM_GOATHUB_FEED_DIR`, `TIM_GOATHUB_DISCORD_CONFIG`
(Standard `~/Library/Application Support/TIM/goathub-discord.json`) und
`TIM_GOATHUB_DISCORD_SECRET_FILE` (Standard: das Broncx-Bot-Geheimnis).

## Gemeinsame Einrichtung mit Treta (Modus `direct`)

Entwurf zur Abstimmung. Nichts davon ist umgesetzt oder vom GoatHub-Team freigegeben.

**Vorgeschlagene Kategorien** (jede mit mehreren Kanälen)

| Kategorie | Rolle für TIM | Hinweis |
| --- | --- | --- |
| market updates | lesen, Calls erkennen | Marktlage und Einschätzungen |
| trading lounge | lesen, Calls erkennen | Live-Austausch, viel Rauschen, Note C bleibt Kontext |
| community | lesen, Calls erkennen | allgemeiner Austausch, nur Beiträge mit Richtung und Symbol zählen |
| education | nur Wissen, keine Calls | Lehrmaterial ist kein Wirksamkeitsbeleg; Rechte der Autoren klären |
| bronxc bootcamp | nur Wissen, keine Calls | Katalog siehe `BRONCX_BOOTCAMP_KNOWLEDGE.md`; nur mit Freigabe |

Die IDs stehen hier nicht. Sie werden beim `setup` lokal eingetragen (Entwicklermodus, Rechtsklick
auf den Kategorienamen, „Kategorie-ID kopieren“) und nicht committet.

**Kategorien:** `setup` fragt getrennt nach Kanal- und Kategorie-IDs. Eine Kategorie steht in der
Config mit `"kind": "category"`. Bei jedem `sync` holt der Bot die Text- und Ankündigungskanäle
darin (`GET /channels/{id}`, dann `GET /guilds/{guild}/channels`), auch solche, die später
dazukommen. Jeder Kanal erbt die Rolle der Kategorie; ein eigener Eintrag für einen Kanal hat
Vorrang. Foren, Threads und Sprachkanäle werden nicht gelesen. Der Bot braucht in jedem dieser
Kanäle *View Channels* und *Read Message History*; am einfachsten gibt der Admin die Rechte auf
Kategorie-Ebene und lässt die Kanäle synchronisiert.

**Schritte für Treta (Admin von The Goat Hub)**

1. Dem TIM-Bot nur diese Kategorien freigeben, mit den Rechten *View Channels* und *Read Message History*.
   Keine Schreibrechte, keine privaten Kanäle, keine Direktnachrichten.
2. Im Entwicklerportal den *Message Content Intent* des Bots einschalten.
3. Den Mitgliedern im Server mitteilen, dass TIM ausgewählte Kanäle liest, wofür und wie lange
   gespeichert wird; Löschwunsch einzelner Beiträge muss möglich sein.

**Danach** wie unter Einrichtung: `setup` mit Modus `direct`, dann `sync` (erwartet `stored=… complete=True`).

**Offen vor dem Start:** Zustimmung der Kanalbetreiber und Autoren, Speicherdauer, Löschweg.
Education und Bootcamp laufen erst nach ausdrücklicher Freigabe.

**Kanalrollen:** `setup` fragt nach den Kanälen, die nur Wissen liefern. Sie stehen in der Config
mit `"role": "knowledge"`, alle anderen mit `"role": "calls"` (Standard, auch für ältere Configs).
Nachrichten aus Wissenskanälen werden gespeichert und exportiert (Überschrift „nur Wissen, keine
Calls“), aber nie als Call erkannt und nie im TIM-Bericht gezeigt. `sync` merkt sich die Rolle je
Kanal im Feed (`state.json`): Wird ein Kanal auf Wissen umgestellt, gilt das ab dem nächsten `sync`
auch für seine schon gespeicherten Nachrichten. Umgekehrt bleibt eine einmal als Wissen
gespeicherte Nachricht Wissen. Eine unbekannte Rolle in einer gespeicherten Zeile zählt als Wissen,
nie als Call. `import-screen` nimmt `"channel_role": "knowledge"` je Eintrag an.

Im Modus `forward` gilt die Rolle für den eigenen Weiterleitungskanal: Lehrmaterial nicht in einen
Call-Kanal weiterleiten, sondern in einen eigenen Kanal mit Rolle Wissen.

## Setup-Entwurf für den Setup-Kanal

`ofsc --input … --setup-draft entwurf.md` schreibt zusätzlich zur Analyse einen Text für Discord
(unter 2000 Zeichen). TIM postet ihn nie selbst; ein Mensch liest und entscheidet. Ohne Trade-Plan
steht dort „Kein Setup (NO TRADE)“ mit Gründen und den beobachteten, unbestätigten Szenarien.
Scores erscheinen nicht, der Haftungshinweis steht immer am Ende. Ein Schreib-Bot ist nicht
vorgesehen und bräuchte eine eigene Freigabe.

## Fehlermeldungen

Wie beim Broncx-Feed: `401` Geheimnis falsch, `403` Bot fehlt das Leserecht im Kanal, `404` Kanal-ID
falsch oder Bot nicht im Server, `empty=… hint` Message Content Intent fehlt, `rejected_author`
Nachricht nicht von einer eingetragenen Nutzer-ID (nur Modus `forward`).

## Lesen am Bildschirm

Ohne Bot im GoatHub-Server liest Claude den Kanal über die Bildschirmfreigabe auf dem Mac
(Discord-App oder ein eigenes Chrome-Fenster). Das Gelesene ist eine Abschrift, keine Kopie:
`import-screen <datei.json>` speichert es mit Quelle `discord_screen`, Kennung aus Inhalts-Hash,
dann folgt der Export. Zahlen und Coin-Namen vor einer Entscheidung am Original prüfen.

## Grenzen

- Reaktionszahlen werden beim ersten Abholen gespeichert und danach nicht aktualisiert.
- Bearbeitete oder gelöschte Discord-Nachrichten bleiben im Stand ihres Abholens.
- Chartbilder werden nur als Dateiname geführt, nicht heruntergeladen oder gelesen.
- Die Call-Erkennung arbeitet mit festen Mustern. Der Originaltext steht immer daneben.
