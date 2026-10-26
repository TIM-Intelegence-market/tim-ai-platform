# Öffentliche Nur-Lese-Ansicht (Cloudflare Tunnel)

Ziel: Andere sehen über einen öffentlichen Link, was TIM auf dem Chart zeigt, ohne Zugang zum
Control Center. Die Ansicht ist englisch und trägt auf jeder Seite den Hinweis
„Research, not financial advice“.

## Was öffentlich ist

`src/dashboard/public_server.py` läuft im Runtime-Prozess auf **127.0.0.1:8780** (nur Loopback) und
liefert ausschließlich:

| Pfad | Inhalt |
| --- | --- |
| `/chart?symbol=&tf=` | interaktiver Chart (BTC/ETH/SOL, alle Zeitrahmen, Level, TPO, Volume Profile, Footprint) |
| `/journal?rule=` | Papier-Journale: Regelvergleich und die letzten 100 Pläne |
| `/api/chart/live`, `/api/plan-journal` | die Daten dieser beiden Seiten |
| `/assets/chart/*.js`, `/robots.txt` | Chart-Skripte, Suchmaschinen-Sperre |

Alles andere ist 404 (Mac, System, Betrieb, Freigaben, Worker, `/api/state`, LLM, Research-Router,
Exporte, Trader-Journal). POST/PUT/DELETE sind 405. Je Besucher 120 Anfragen pro Minute (danach 429),
höchstens 8 gleichzeitige Berechnungen (danach 503), Seiten 10 s und Daten 5 s im Cache.
Das Control Center auf 8765 bleibt unverändert und lokal.

## Einschalten (einmalig, Uzi am Mac)

Voraussetzung: der PR mit dieser Datei ist gemergt und vom Dashboard-Agent ausgerollt.

```bash
brew install cloudflared
touch "$HOME/Library/Application Support/TIM/public-dashboard.enabled"
launchctl kickstart -k gui/$(id -u)/com.tim.runtime
sleep 20
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8780/chart
```

Erwartet: `200`. Dann den Tunnel als LaunchAgent starten (startet nach Neustart des Macs wieder):

```bash
cat > "$HOME/Library/LaunchAgents/com.tim.public-tunnel.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.tim.public-tunnel</string>
  <key>ProgramArguments</key><array><string>$(brew --prefix)/bin/cloudflared</string><string>tunnel</string><string>--no-autoupdate</string><string>--url</string><string>http://127.0.0.1:8780</string></array>
  <key>KeepAlive</key><true/><key>RunAtLoad</key><true/>
  <key>StandardErrorPath</key><string>$HOME/Library/Logs/tim-public-tunnel.log</string>
  <key>StandardOutPath</key><string>$HOME/Library/Logs/tim-public-tunnel.log</string>
</dict></plist>
PLIST
launchctl bootstrap gui/$(id -u) "$HOME/Library/LaunchAgents/com.tim.public-tunnel.plist"
sleep 10
grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' "$HOME/Library/Logs/tim-public-tunnel.log" | tail -1
```

Die letzte Zeile ist der öffentliche Link (`…/chart` anhängen ist nicht nötig, `/` leitet dorthin).

## Grenzen des Schnellstarts

- Die `trycloudflare.com`-Adresse ist zufällig und **ändert sich bei jedem Neustart** des Tunnels
  (Mac-Neustart, Absturz). Den aktuellen Link liefert jederzeit der `grep`-Befehl oben.
- Cloudflare gibt für Schnell-Tunnel keine Verfügbarkeitszusage. Für eine feste Adresse: Cloudflare-Konto
  mit eigener Domain und benanntem Tunnel (`cloudflared tunnel login`, `create`, `route dns`); das ist
  der nächste Schritt, wenn der Link dauerhaft geteilt werden soll.
- Die Daten kommen vom Mac: Ist der Mac aus oder TIM gestoppt, ist die Seite nicht erreichbar.

## Ausschalten

```bash
launchctl bootout gui/$(id -u) "$HOME/Library/LaunchAgents/com.tim.public-tunnel.plist"
rm "$HOME/Library/Application Support/TIM/public-dashboard.enabled"
launchctl kickstart -k gui/$(id -u)/com.tim.runtime
```

Der erste Befehl nimmt den Link sofort vom Netz; die beiden anderen schalten auch den lokalen Port 8780 ab.
