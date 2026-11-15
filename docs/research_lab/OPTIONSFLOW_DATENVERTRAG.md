# Optionsflow: Datenvertrag und Recorder (A1/A2)

Stand 13.11.2026. Teil von `SELBSTVERBESSERNDE_KI_PLAN.md`. Uzi am 13.11.2026: „aufzeichnen, A1 und A2 starten, Optionsflow
mehr Daten und Regeln sammeln und dann testen“. **Nur Aufzeichnung und Datenvertrag. Keine Regel, kein Score, kein Journal,
keine Order, kein Schlüssel.** Tests der Daten (Studie) kommen erst mit Präregistrierung (Paket A4).

## Recorder (A1)

`python -m src.research_lab.options_flow record --root ~/TIM-research/options-flow [--currency BTC|ETH]`

Fragt nur drei öffentliche Deribit-Methoden per HTTPS GET ab (kein Konto, kein Key) und speichert jede Antwort unverändert
mit lokaler Empfangszeit (`recv_ms`) als gzip-JSONL, eine Datei je UTC-Tag, Strom und Lauf
(`<root>/BTCOPTTRADES/<Tag>.<Laufstart>.jsonl.gz`, Aufbau wie beim Bitunix-Recorder):

| Strom | Methode | Takt |
|---|---|---|
| `TRADES` | `get_last_trades_by_currency_and_time` (kind=option, sortiert aufsteigend, seitenweise) | 10 s |
| `SUMMARY` | `get_book_summary_by_currency` (Open Interest, Mark-IV, Volumen je Instrument) | 5 min |
| `DVOL` | `get_volatility_index_data` (Auflösung 60 s, letzte 2 h) | 5 min |

Gesundheit: `status.json` im Wurzelordner (Herzschlag, Zähler, Trade-Cursor, letzter Fehler, freier Platz). Netzfehler werden
gezählt und beim nächsten Takt wiederholt; der Cursor springt nicht, ein kurzer Ausfall wird nachgeholt, soweit Deribit den
Zeitraum noch liefert. Speicherfehler oder < 2 GB frei sind fatal (`state: failed`, Exit 2, launchd startet neu). Ein Neustart
schreibt eine `gap`-Zeile von der letzten Empfangszeit bis jetzt. Mehr Trades in einer Millisekunde als eine Seite fasst
(1000) würden übersprungen und stehen dann sichtbar in `cursor_skips`.

**Nicht live geprüft:** Die Cloud kommt nicht an Deribit (Proxy 403). Parameter und Antwortform folgen der Deribit-v2-Doku,
die Tests nutzen Doku-nahe Fixtures. Der erste Lauf am Mac muss mit `audit` geprüft werden (Trades > 0, `rejected` leer,
Latenz plausibel, DVOL-Antwort lesbar). Rohdaten bleiben unverändert, ein Parserfehler lässt sich also später beheben.
Wie weit `get_last_trades_by_currency_and_time` zurückreicht, ist offen und wird aus dem ersten Lauf gemessen.

Dauerbetrieb (LaunchAgent am Mac) ist ein neuer Dienst und startet erst nach Uzis Wort und nach dem Merge.

## Datenvertrag (A2)

Rohzeilen werden nie geändert. Abgeleitete Spalten entstehen getrennt in `contract.normalize_trade`:

| Feld | Bedeutung |
|---|---|
| `trade_id`, `ts_ms`, `recv_ms` | Kennung, Börsenzeit (UTC ms), Empfangszeit. `latency_ms = recv_ms - ts_ms` |
| `instrument`, `currency`, `expiry_ms`, `strike`, `is_call` | aus dem Namen; Verfall 08:00 UTC |
| `side` | **Taker-Seite** (`buy` = Taker hat Ask genommen); bei Orderbuch-Trades der Aggressor |
| `price`, `amount`, `index_price` | Preis in BTC (Basiswert), Menge in BTC, Indexkurs zum Trade |
| `premium_usd` | `price * amount * index_price`; `notional_usd = amount * index_price` |
| `iv` | implizite Vola in %, wenn geliefert |
| `block`, `liquidation` | Blocktrade bzw. Liquidation, markiert statt untergemischt |

Regeln:

1. **Kein Blick in die Zukunft:** Ein Merkmal zum Zeitpunkt t nutzt nur Zeilen mit `recv_ms <= t`, nicht nur `ts_ms <= t`.
2. **Doppelte:** je `trade_id` zählt der erste Empfang; `audit` zählt Duplikate.
3. **Ungültig:** fehlende Felder, `direction` nicht buy/sell, Menge/Index ≤ 0, nicht lesbarer Instrumentname → verworfen und je
   Grund gezählt (`audit.rejected`), nie stillschweigend.
4. **Lücken:** `gap`-Zeilen und `unclean_segments` in `audit`; Studien dürfen Zeiträume mit Lücke nicht als „kein Flow“ lesen.
5. **Trennung:** Live-, historische (Tardis o. Ä.), synthetische und abgeleitete Daten werden nicht in einer Datei gemischt.
6. **Ablage:** Daten außerhalb des Repos; nur Code, Doku und kleine Fixtures liegen im Repo.
7. **Offen (für A3):** Aggressor-Zuverlässigkeit bei Blocktrades, Umgang mit Rolls zwischen Verfällen, Mindestgröße für
   „großer Trade“ (wird aus der ersten Verteilung abgeleitet, vor A4 festgeschrieben, nicht danach).

`python -m src.research_lab.options_flow audit --root ~/TIM-research/options-flow` zeigt Trades, Duplikate, verworfene Zeilen
und Gründe, Lücken, unsaubere Segmente und die Latenz (p50/p95).

Tests: `tests/test_research_lab_options_flow.py`.
