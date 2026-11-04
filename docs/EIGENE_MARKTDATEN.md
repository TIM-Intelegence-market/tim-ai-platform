# Eigene Marktdaten (Stand 04.11.2026)

TIM sammelt Daten, die sich später nicht oder nur kurz nachholen lassen. Jeder Monat davon macht
die Forschung (Orderflow, Gamma, Liquidationen) belastbarer. Diese Seite sagt, was gesammelt wird,
wo es liegt, wie lange es bleibt und wie ein Ausfall auffällt.

| Quelle | Sammler | Ablage auf dem Mac | Nachholbar? | Aufbewahrung |
|---|---|---|---|---|
| BTC-Spot-Trades und Kerzen | Runtime (`com.tim.runtime`) | PostgreSQL `agg_trades`, `candles` | ja, Binance-Archiv | unbegrenzt, tägliches DB-Backup |
| BTC-Perp-Orderflow (Footprint 5 min × 5 $, Bubbles) | Runtime-Task `tim-perp-flow` | `~/TIM-live/data/perp_flow/perp-*.json.gz`, ältere Tage in `archive/` | nur über aggTrades-IDs, praktisch nein | unbegrenzt (Chart zeigt 14 Tage) |
| Open Interest BTCUSDT 1h | Runtime-Task `tim-perp-flow` | `~/TIM-live/data/perp_flow/oi-BTCUSDT-1h.jsonl` | Binance hält nur 30 Tage | unbegrenzt, ab 04.11.2026 |
| Gamma-Walls, Flip, Max Pain (Deribit, alle 5 min) | Runtime (PR #97) | `~/TIM-live/data/options/gamma_levels.jsonl` | nein | unbegrenzt |
| Echte Liquidationen Binance und Bybit (S12) | `com.tim.s12-liquidations` | `~/Library/Application Support/TIM/research-lab/liquidations/raw/` | nein | unbegrenzt |
| Funding | Chart liest live | nicht gespeichert | ja, Binance hält die ganze Historie | — |
| Coinbase-Premium | Chart liest live | nicht gespeichert | ja, aus 1h-Kerzen beider Börsen | — |

## Änderung vom 04.11.2026

- Der Perp-Sammler löschte Tagesdateien nach 14 Tagen (erster Verlust wäre am 13.11.2026 gewesen).
  Jetzt verschiebt er sie nach `data/perp_flow/archive/`. Der Chart und ein Neustart lesen weiter nur
  die letzten 14 Tage; das Archiv bleibt unangetastet.
- Open Interest wird stündlich angehängt, jede Stunde genau einmal (`append_oi_archive`).
- `scripts/tim_db_backup.py files` packt Perp-Orderflow samt Archiv, Open Interest, Gamma und die
  S12-Liquidationen täglich in `tim_files_<Zeit>.tar.gz` mit sha256 neben die DB-Dumps (7 Stände).
  Der tägliche Backup-Job (03:15) ruft das nach dem DB-Dump selbst auf, auch wenn der Dump scheitert.
  Ist die externe Platte `/Volumes/TIM-Backup` eingehängt, geht die Kopie auch dorthin; sonst steht im
  Bericht `mirror: false`. Bericht: `data/operational/backup_files.json`.
- Control Center: Kachel „Eigene Daten" auf der Startseite (schlechteste Quelle entscheidet) und
  Abschnitt „Eigene Marktdaten" unter Betrieb mit einer Kachel je Quelle.

## Wann wird es gelb oder rot?

| Kachel | Gelb, wenn |
|---|---|
| Perp-Orderflow | `state.json` älter als 10 min, Lücke in den letzten 24 h, letzte Stundenprüfung gegen Binance falsch |
| Open Interest 1h | neueste Stunde älter als 3 h |
| Gamma-Walls | neuester Schnappschuss älter als 20 min |
| Liquidationen Binance/Bybit | neueste Zeile älter als 5 min (der Sammler schreibt jede Minute „alive"), letzte Zeile `disconnect` |
| Kopie eigene Daten | Bericht älter als 26 h oder nicht PASS |

Rot bedeutet eine unlesbare Datei. Grau heißt: Quelle hat noch nichts geschrieben, mit Grund.

## Grenze

Alle Kopien liegen bisher auf derselben Mac-Platte. Gegen einen Plattenschaden hilft erst eine
zweite Kopie außerhalb (externe SSD als `/Volumes/TIM-Backup`, dann läuft `mirror` von selbst).
