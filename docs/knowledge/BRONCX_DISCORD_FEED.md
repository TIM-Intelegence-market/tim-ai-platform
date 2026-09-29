# Broncx-Discord-Feed: aktuelle Sicht als Leitfaden für TIM

Status: externe Meinung, nur Beobachtung. Ergänzt den
[Bootcamp-Katalog](BRONCX_BOOTCAMP_KNOWLEDGE.md) um Broncx' aktuellen Gedankengang.

## Wofür TIM die Beiträge nutzt

| Darf | Darf nicht |
| --- | --- |
| Richtung (SHORT/LONG), Symbol und Timeframe als Hypothese nennen | als CONFIRMATION zählen |
| Ziel- und Prüf-Level nennen, die TIM gegen die Kerzen prüft (TOUCHED / NOT_REACHED, Abstand in %) | Scores, Szenarien, Trade-Plan oder Entscheidung ändern |
| Invalidierung anzeigen; mit Zahl („invalid below 83,000“) prüft TIM sie per Schlusskurs | älter als die Frist (Standard 24 h) noch als aktuell gelten |
| offen zeigen, ob TIMs Szenarien übereinstimmen (ALIGNED) oder widersprechen (CONFLICT) | Beiträge verwenden, die erst nach dem Analysezeitpunkt gepostet oder weitergeleitet wurden |

Die Sicht landet im Audit (`engine: external_context`, `influences_decision: false`)
und im Bericht unter **BRONCX-LEITFADEN**. Ein Test stellt sicher, dass Entscheidung,
Szenarien, Orderflow und Datenqualität mit und ohne Broncx-Beiträge identisch bleiben.

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
- Chartbilder werden gespeichert und gezählt, aber nicht ausgewertet.

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
   ```

7. **Dauerbetrieb** (startet mit der Anmeldung und läuft dann durchgehend):

   ```sh
   cp ops/launchd/com.tim.broncx-discord-feed.plist ~/Library/LaunchAgents/
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

Einstellbar per Umgebungsvariable: `TIM_BRONCX_FEED_DIR`, `TIM_BRONCX_DISCORD_CONFIG`
und `TIM_BRONCX_DISCORD_SECRET_FILE`.

## Grenzen

- Die Auswertung der Texte arbeitet mit festen Mustern und kann Aussagen verfehlen. Der
  Originaltext steht deshalb immer im Audit, und `show` zeigt, was TIM erkannt hat.
- Invalidierungen ohne Zahl, etwa „flip poc for higher“, kann TIM nicht automatisch
  prüfen. Sie bleiben `NOT_EVALUATED` und müssen von Hand geprüft werden.
- Die Frist, die Schwelle von 30 % für Kurzschreibweisen und die 7 Tage für eine
  Erneuerung sind Startwerte. Sie sind nicht statistisch geprüft.
