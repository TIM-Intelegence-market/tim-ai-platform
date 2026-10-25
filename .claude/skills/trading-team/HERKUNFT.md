# Herkunft

* **Quelle:** PDF „MSB INTEL | THE SETUP – Build a 24/7 AI Trading Team With Claude Code“ (@msbintel),
  von Uzi am 23.10.2026 im Projekt geschickt. Das PDF enthält nur Prompts, keinen Code.
* **Code:** in TIM neu geschrieben (23.10.2026), nur Python-Standardbibliothek. Keine fremden Pakete,
  keine fremden Repos, keine Installationsbefehle.
* **Übernommen:** Bot 1 Scanner, Bot 2 Buzz-Tracker, Bot 3 Papier-Bot mit fiktiven 1.000 USD, 1 % Risiko,
  Stop und Ziel, Gebühren, max. 10 Trades/Tag, `trades.csv`, Lauf alle 5 Minuten, ehrlicher Bericht.
* **Präzisiert:**
  - Volumenregel: „2x Tagesdurchschnitt“ als Stundenumsatz gegen durchschnittlichen Stundenumsatz der
    letzten 7 Tage gelesen (sonst wäre die Regel praktisch nie erfüllt).
  - Nur Long (Spot-Logik); Abwärts-Treffer werden protokolliert, aber nicht gehandelt.
  - Ausstieg an 5-Minuten-Kerzen; Stop und Ziel in derselben Kerze zählen als Stop.
  - Schatten-Buch für Buzz < 7, damit der Bericht den Nutzen des Buzz-Scores messen kann.
  - Strenges Urteil im Bericht: unter 30 Trades oder ohne Gewinn nach Gebühren immer „Nein“.
* **Weggelassen:**
  - Alles zu Echtgeld: Börsen-API-Schlüssel, „Trading an, Abheben aus“, Start mit echtem Betrag.
    TIM V2 handelt kein Echtgeld, Binance Testnet ist bewusst nicht verbunden.
  - X (Twitter): Datenzugang kostenpflichtig, Scraping gegen die Regeln; Buzz kommt aus CoinGecko und RSS.
  - Cloud-Server: der Server ist vorerst raus, TIM läuft nur auf dem Mac. Statt Server-Anleitung gibt es
    eine launchd-Vorlage (nicht eingerichtet).
* **Geprüft (23.10.2026):** eigene Tests offline grün (Python 3.13). Live-Abruf in der Cloud nicht möglich
  (Binance, CoinGecko und Feeds gesperrt).
* **Live auf dem Mac (24.10.2026, Uzis „ja“):** Binance, CoinGecko-Trends und die drei Feeds liefern Daten.
  Dauerbetrieb per launchd `com.tim.trading-team` aus eigenem Checkout `~/TIM-trading-team`, alle 5 Minuten.
  Gefunden und behoben: Binance führt Paare mit chinesischen Zeichen (z. B. `牛来USDT`); Symbole werden jetzt
  URL-kodiert.
* **Grenzen für TIM:** nur Papier und Research. Kein Echtgeld, keine Anbindung an Order-Pfade, keine
  Zugangsdaten im Repo. Nicht in `~/TIM-live` einspielen.
