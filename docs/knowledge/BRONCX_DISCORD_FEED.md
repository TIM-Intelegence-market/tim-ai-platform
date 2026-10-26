# Broncx-Discord-Feed: aktuelle Sicht als Leitfaden für TIM

Status: externe Meinung, fließt gewichtet in die Analyse ein. Ergänzt den
Bootcamp-Wissen (Katalog nicht öffentlich) um Broncx' aktuellen Gedankengang.

## Wofür TIM die Beiträge nutzt

| Darf | Darf nicht |
| --- | --- |
| Richtung (SHORT/LONG), Symbol und Timeframe als Hypothese nennen | als CONFIRMATION zählen |
| Scores gewichten: Szenarien in seiner Richtung +0,08, Gegenszenarien −0,08 | Szenario-Status, Bestätigungen oder Invalidierungen ändern |
| Level mit Rolle LEVEL, die höchstens 1 % vom Kurs entfernt sind, als eigene Szenarien in seiner Richtung anlegen (höchstens zwei, Kennung nach Level, z. B. `X-SHORT-83800`) | allein einen Trade-Plan auslösen: der braucht weiter ein von TIM bestätigtes Szenario, Datenqualität, Risiko und Kill Switch |
| Ziel- und Prüf-Level nennen, die TIM gegen die Kerzen prüft (TOUCHED / NOT_REACHED, Abstand in %) | älter als die Frist (Standard 24 h) noch wirken |
| Invalidierung anzeigen; mit Zahl („invalid below 83,000“) prüft TIM sie per Schlusskurs, auch aus Folgebeiträgen. Ausgelöst heißt: keine Wirkung mehr. Stop- und Invalidierungspreise (Rolle STOP) werden nie zu Einstiegs-Szenarien | Beiträge verwenden, die erst nach dem Analysezeitpunkt gepostet oder weitergeleitet wurden |
| offen zeigen, ob TIMs eigene Szenarien übereinstimmen (ALIGNED) oder widersprechen (CONFLICT) | wirken, wenn sein neuester Beitrag mit Richtung beide Seiten nennt (MIXED) |

Maßgeblich ist sein neuester aktiver Beitrag mit Richtung („This might play out again“
erneuert ihn) zusammen mit den Folgebeiträgen ohne eigene Richtung. Nur deren Level
zählen, ältere Ideen nicht. Verneinte oder geschlossene Positionen („not shorting“,
„closed my short“) gelten nicht als Richtung. Die Wirkung steht im Audit (`engine: external_context`, Felder `influences_scores` und `influence`:
Sicht, Score-Änderungen je Szenario, Level-Szenarien) und im Bericht unter
**BRONCX-LEITFADEN**. Tests stellen sicher, dass Entscheidung, Szenario-Status,
Orderflow und Datenqualität gleich bleiben und ohne TIMs eigene Bestätigung kein
Trade-Plan entsteht. Level-Szenarien liegen nicht innerhalb von 0,2 % eines
TIM-eigenen Triggers und zählen beim Abgleich ALIGNED/CONFLICT nicht mit.

Zusammenhänge im Thread:

- Kurz aufeinanderfolgende Beiträge (bis 30 Minuten) gelten als ein Gedanke: „Fc btc 15“
  und danach „tp2 at 82.6“ werden BTC 15m zugeordnet.
- „This might play out again“ erneuert die letzte Richtungsaussage der vergangenen
  7 Tage. Die Frist beginnt damit neu.
- Kurzschreibweisen wie „82.6“ werden nur dann als 82 600 gelesen, wenn das höchstens
  30 % vom aktuellen Preis entfernt ist. Das gilt auch für „1.5k“. Prozentangaben,
  Stückzahlen und Beträge gelten nicht als Level.
- „short squeeze“ oder „longs liquidated“ werden nicht als Richtung gewertet.
- Als Timeframe zählen nur übliche Werte (etwa „btc 15“ oder „btc 4h“). „btc 83“ wird als Preis gelesen.
- Ein Level gilt nur dann als erreicht, wenn eine Kerze es nach dem Beitrag berührt hat.
  Kerzen, die schon vor dem Beitrag begonnen haben, zählen nicht.
- Chartbilder liest ein lokales Bildmodell aus (siehe [Chartbilder](#chartbilder)).

## Chartbilder

Der Bot lädt Chartbilder beim Abholen herunter (`data/broncx_feed/images/<Nachrichten-ID>/`),
weil Discord-Bildlinks nach etwa einem Tag ablaufen. Heruntergeladen wird nur vom Discord-CDN
über HTTPS, höchstens 10 MB, und ohne das Bot-Geheimnis. Danach liest ein lokales Bildmodell über
Ollama (Standard `qwen3.5:9b`, einstellbar mit `TIM_BRONCX_VISION_MODEL`) das Bild aus. Kein Bild
verlässt den Mac. Im Dauerbetrieb wird pro Minute höchstens ein Bild gelesen, das dauert etwa eine
Minute. Das Ergebnis wird in `chart_readings.jsonl` gespeichert. Eine Analyse ruft das Modell
also nie selbst auf, und eine Wiederholung liest dieselben Werte.

Aus einem Bild gelesene Werte sind Schätzungen. Für sie gelten dieselben Grenzen wie für den Text,
dazu strengere Regeln:

| Regel | Warum |
| --- | --- |
| Eine Richtung hat ein Chart nur mit Positions-Werkzeug (rote und grüne Box am Einstieg). Das Modell liest nur Einstieg und die äußeren Boxkanten ab, die Richtung berechnet TIM daraus: Rot oben und Grün unten ist SHORT. | Im Test hat das Modell dieselbe Short-Position einmal als LONG gedeutet und bei einem reinen Kurschart die Hoch/Tief-Pfeile als Richtung gelesen. |
| Die Chart-Richtung zählt, wenn der Beitrag keinen Text hat, wenn der Text keine eigene Richtung nennt („Took this“) oder wenn sie zur Richtung im Text passt. Sie zählt nicht, wenn der Text etwas anderes sagt, eine Richtung zurücknimmt („closed my short“, „no longs“, „shorts got squeezed“), einen Trade verwaltet („stopped out“, „tp1 hit“, „if taken“, „moved sl to be“) oder eine frühere Idee erneuert („still valid“). Ist für das Symbol noch eine frühere Sicht offen (jünger als die Frist und nicht mit „closed“, „stopped out“ o. Ä. beendet), gilt ein Beitrag ohne eigene Richtung, auch ein reines Bild, als Folgebeitrag: Das Bild ersetzt dann weder seine geschriebene Richtung noch seine Level oder Invalidierung. | Der Text ist verlässlicher als ein gelesenes Bild. „Took this“ plus Chart ist aber Broncx' üblicher Stil. |
| Der Stop des Positions-Werkzeugs wirkt nur als Invalidierung, wenn die Chart-Richtung auch zählt. | Ein falsch gelesener Stop darf keine anders lautende Sicht beenden. |
| Chart-Level zählen nur innerhalb von 30 % vom Kurs, tragen `source: chart`, stehen im Bericht als „aus Bild, geschätzt“ und werden gegen die Kerzen geprüft. Eigene Level-Szenarien werden daraus nie. | Das Modell liest gelegentlich auch Kursanzeigen mit. |
| Symbol und Timeframe aus dem Bild füllen nur Lücken im Text. | |

`show --price 83365` zeigt je Beitrag die Zeile `chart (estimated, …)` mit dem Gelesenen und
Hinweise wie `chart agrees with text bias SHORT`. Bilder aus der Zeit vor dieser Funktion holt
`fetch-images` nach, solange Discord sie noch verlinkt. `read-charts` liest alle offenen Bilder
auf einmal. Läuft Ollama nicht, bleiben die Bilder ungelesen und werden später gelesen.

## Ablauf

1. Broncx postet in The Goat Hub.
2. Du klickst auf **Weiterleiten** (↪) und wählst deinen Kanal `#broncx-feed` im TIM-Server.
3. Der Bot `scripts/broncx_discord_bot.py` liest den Kanal jede Minute und speichert neue
   Beiträge in `data/broncx_feed/posts.jsonl`. Das Verzeichnis ist lokal und wird nicht committet.
4. `ofsc --broncx-feed data/broncx_feed` nimmt die Beiträge in die Analyse auf.

Der Bot liest nur, schreibt nichts nach Discord und ist nur in deinem eigenen Server.
Er übernimmt ausschließlich Nachrichten von den eingetragenen Nutzer-IDs, also von dir.
Andere Mitglieder deines Servers können deshalb keine falschen „Broncx“-Beiträge
einschleusen. Weil Discord beim Weiterleiten den ursprünglichen Autor nicht mitschickt,
gilt: Leite in `#broncx-feed` nur Broncx-Beiträge weiter.

Den Text einfach selbst in den Kanal zu schreiben oder einzufügen funktioniert auch.
Dann zählt der Zeitpunkt deiner Nachricht.

## Einrichtung (einmalig, etwa 10 Minuten)

1. **Kanal:** Lege im TIM-Server einen Textkanal `#broncx-feed` an.
2. **Bot anlegen:** Öffne <https://discord.com/developers/applications>, wähle
   *New Application* (Name z. B. „TIM Feed“) und dann links *Bot*.
   - Schalte **Message Content Intent** ein. Ohne diese Einstellung kommen die Nachrichten leer an.
   - Klicke auf *Reset Token* und kopiere das Bot-Geheimnis. Es gehört nur in Schritt 5,
     nicht in einen Chat, eine Datei im Repo oder einen Commit.
3. **Bot einladen:** Wähle unter *OAuth2 → URL Generator* den Scope `bot` und die
   Rechte *View Channels* und *Read Message History*. Öffne den erzeugten Link und
   wähle den TIM-Server.
4. **IDs kopieren:** Aktiviere in Discord *Einstellungen → Erweitert → Entwicklermodus*.
   Kopiere dann per Rechtsklick auf `#broncx-feed` die **Kanal-ID** und per Rechtsklick
   auf deinen Namen die **Nutzer-ID**.
5. **Einrichten:** Führe auf dem Mac im TIM-Ordner aus:

   ```sh
   .venv/bin/python scripts/broncx_discord_bot.py setup
   ```

   Das Skript fragt Kanal-ID, Nutzer-ID und das Bot-Geheimnis ab. Das Geheimnis wird
   verdeckt eingegeben. Beides wird mit Rechten 0600 gespeichert unter
   `~/Library/Application Support/TIM/`.
6. **Testen:** Leite einen Broncx-Beitrag weiter und führe dann aus:

   ```sh
   .venv/bin/python scripts/broncx_discord_bot.py once   # erwartet: stored=1
   .venv/bin/python scripts/broncx_discord_bot.py show   # zeigt, wie TIM den Beitrag liest
   .venv/bin/python scripts/broncx_discord_bot.py read-charts   # Chartbilder lesen (Ollama muss laufen)
   ```

7. **Dauerbetrieb** (startet mit der Anmeldung und läuft dann durchgehend):

   ```sh
   sed -e "s|/Users/tim/Documents/TIM/tim|$PWD|g" -e "s|/Users/tim/|$HOME/|g" -e "s|<string>tim-user</string>|<string>$USER</string>|g" ops/launchd/com.tim.broncx-discord-feed.plist > ~/Library/LaunchAgents/com.tim.broncx-discord-feed.plist
   launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.tim.broncx-discord-feed.plist
   ```

   Das Log steht in `data/operational/broncx_discord_feed.log`.

## Fehlermeldungen

| Meldung | Ursache |
| --- | --- |
| `empty=… hint: … Message Content Intent` | Schritt 2: Intent ist nicht eingeschaltet |
| `rejected_author=…` | Die Nachricht kam nicht von einer eingetragenen Nutzer-ID |
| `401` | Das Bot-Geheimnis ist falsch oder wurde zurückgesetzt: `setup` erneut ausführen |
| `403` | Dem Bot fehlen im Kanal *View Channel* oder *Read Message History* |
| `404` | Die Kanal-ID ist falsch oder der Bot ist nicht im Server |
| `ERROR: chart reading: Ollama not reachable` | Ollama läuft nicht: die Ollama-App starten, die Bilder werden dann nachgelesen |
| `image_errors=…` | Ein Bild ließ sich nicht laden: später `fetch-images` ausführen |

Einstellbar per Umgebungsvariable: `TIM_BRONCX_FEED_DIR`, `TIM_BRONCX_DISCORD_CONFIG`,
`TIM_BRONCX_DISCORD_SECRET_FILE`, `TIM_BRONCX_VISION_MODEL` und `TIM_OLLAMA_URL`.

## Grenzen

- Die Auswertung der Texte arbeitet mit festen Mustern und kann Aussagen verfehlen. Der
  Originaltext steht deshalb immer im Audit, und `show` zeigt, was TIM erkannt hat.
- Die Chart-Auswertung ist an zwei echten Bildern erprobt, nicht statistisch geprüft. Ein kleines
  lokales Modell verliest sich. Deshalb stehen Bildwerte immer getrennt im Audit.
- Invalidierungen ohne Zahl, etwa „flip poc for higher“, kann TIM nicht automatisch
  prüfen. Sie bleiben `NOT_EVALUATED` und müssen von Hand geprüft werden.
- Die Frist, die Schwelle von 30 % für Kurzschreibweisen, die 7 Tage für eine
  Erneuerung, das Gewicht 0,08 und das 1-%-Fenster für Level-Szenarien sind Startwerte.
  Sie sind nicht statistisch geprüft.
- Beiträge ohne Symbol (etwa „shorts are in“) gelten nur für BTC, weil in `#broncx-feed`
  BTC-Beiträge landen. Symbole werden exakt verglichen (SOL wirkt nicht auf SOLV).
