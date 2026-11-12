# V2.8 Papierhandel: Schein-Adapter, Not-Aus, Abgleich

Stand 12.11.2026. Code: `src/tim_v2/paper/`, Tests: `tests/test_tim_v2_paper.py`.
Meilenstein laut `docs/tim_v2/milestones.md`: isolierter Schein-Ausführungsadapter, Betriebskennzahlen und
Not-Aus, Abgleich und Vorfallablauf. Ausgang: technischer Nachweis, dass kein echter Order-Endpunkt erreichbar ist.

## Was gebaut ist

| Teil | Datei | Kurz |
|---|---|---|
| Schein-Adapter | `adapter.py` | Market, Limit, Stop, Reduce-only, Stop-Loss/Take-Profit je Position, Funding, ein Netto-Bestand je Symbol |
| Not-Aus | `kill_switch.py` | von Hand, per Datei (`TIM_PAPER_KILL_FILE`), automatisch bei Tagesverlust 3 %, Drawdown 10 %, 5 Ablehnungen in Folge, Abgleichfehler |
| Abgleich | `reconcile.py` | baut Bestand und Kasse nur aus den Fills neu auf, vergleicht mit dem Adapter; jede Abweichung löst den Not-Aus aus |
| Kennzahlen | `models.Metrics` | Orders, Fills, Ablehnungen samt Grund, Gebühren, Schlupf, Funding, Spitze, Drawdown, Not-Aus-Ereignisse, Abgleiche |
| Nachweis | `isolation.py` | liest jede Quelldatei des Pakets und schlägt fehl bei Netz-, Prozess-, Datenbank- oder TIM-Fremdimporten, URL-Texten und dynamischen Importen |
| Lauf | `runner.py`, `__main__.py` | `python -m src.tim_v2.paper replay --bars B.jsonl --orders O.jsonl --out DIR` schreibt `journal.jsonl` und `summary.json` |

## Füllregeln (vorsichtig gewählt)

- Eine Order sieht nur Kerzen, die zu oder nach ihrer Abgabezeit öffnen. Damit gibt es keinen Blick in die Zukunft.
- Market: Eröffnung der nächsten Kerze plus Schlupf, Taker-Gebühr.
- Stop: Auslösepreis oder schlechtere Lücken-Eröffnung, plus Schlupf und Stop-Zuschlag.
- Limit: zum Limit (Maker, ohne Schlupf), aber nur, wenn die Kerze es berührt. Bei einer Lücke über das Limit hinaus
  Taker zur Eröffnung.
- Berührt eine Kerze Stop-Loss und Take-Profit, zählt der Stop-Loss. Die Klammern werden schon auf der Kerze geprüft,
  auf der der Einstieg füllt.
- Kosten-Vorgaben wie S24/OF2: Taker 6 bp, Maker 2 bp, Schlupf 3 bp, Stop-Zuschlag 5 bp. Die Gebühren sind
  Annahmen, bis ein Kontoauszug sie bestätigt.
- Hebel höchstens 10x (Repo-Grenze, Uzi 20.10.). Eine höhere Einstellung lehnt der Adapter beim Start ab.

## Nachweis: kein echter Order-Endpunkt

1. **Statisch:** `python -m src.tim_v2.paper isolation` gibt bei jeder Verletzung Exit 1 zurück. Erlaubt sind nur
   die Standardbibliothek-Module in `ALLOWED_STDLIB` und Importe innerhalb des Pakets. Exchange-Clients, der
   Bitunix-Forschungsclient, der Live-Trader und die Datenbank liegen alle außerhalb des Pakets.
2. **Zur Laufzeit:** Ein Test startet eine eigene Python-Instanz mit gesperrten Sockets, lässt einen ganzen
   Replay laufen und prüft, dass kein Netz-, Prozess- oder Datenbankmodul geladen wurde.
3. **Im Objekt:** `FakeExecutionAdapter.live_execution` ist `False` und lässt sich nicht umstellen. Der Adapter hat
   kein Feld für Schlüssel, Konto, Endpunkt oder URL.
4. Jeder Replay prüft die Isolation zuerst und schreibt das Ergebnis samt SHA-256 der Quellen in `summary.json`.

Grenze: Die statische Prüfung erkennt keine bewusst versteckten Umgehungen, etwa per `getattr` mit
zusammengesetztem Namen. Darum gibt es die Laufzeitprüfung, und Änderungen an `src/tim_v2/paper/` gehören ins Review.

## Vorfallablauf (Papier)

| Auslöser | Was passiert | Wer macht weiter |
|---|---|---|
| Not-Aus aus beliebigem Grund | neue Eröffnungen werden abgelehnt, offene Eröffnungs-Orders storniert; Schließen und `flatten` bleiben möglich | Mensch prüft `summary.json` → `kill_switch.events` |
| Abgleichfehler | Not-Aus mit Quelle `RECONCILIATION`, Eintrag `RECONCILIATION_MISMATCH` im Journal | Ursache klären; der Lauf zählt nicht als Beleg |
| Kill-Datei | Not-Aus mit Quelle `FILE`; Freigabe erst nach Entfernen der Datei | wer die Datei gesetzt hat |
| Freigabe | nur `KillSwitch.release(at, released_by=<Name>)`, der Name wird im Ereignis-Log gespeichert | Uzi |

## Was V2.8 nicht ist

- **Kein Edge-Nachweis.** S24, S26 und S27 haben nach Kosten keinen robusten Edge gezeigt. Der Adapter misst die
  Ausführung, nicht die Strategie.
- Der Adapter allein kennt keine Live-Pläne. Die Anbindung übernimmt der V2.9-Schatten (unten).
- Keine Freigabe von V2. Laut `docs/v2_readiness/authoritative_readiness_definition.md` dürfen Software und KI V2
  nicht selbst freigeben.

## V2.9 Schatten (ab 12.11.2026)

`src/tim_v2/shadow.py`, aufgerufen in der Runtime (`main.py`, Plan-Journal-Schleife) neben Orderflow-Schatten und
Chart-Urteil. Er liest die 15m- und 1h-Plan-Journale und die geschlossenen 5m-Kerzen der Runtime und spielt jeden neuen
Plan auf einem eigenen Papier-Adapter durch:

- Order zum Zeitpunkt `created_at`, Limit oder Stop am Einstieg, Stop-Loss am Plan-Stop, Risiko 0,25 % von
  1.000 USD Papier.
- Das Ende bestimmt das Journal. Schließt das Journal, wird auf Papier zur nächsten Kerze glattgestellt. Endet ein Plan
  ohne Füllung (EXPIRED, INVALIDATED, REPLACED), wird die Order storniert. Teilziele werden nicht nachgebildet.
- Ergebnis in `data/journal/tim_v2_shadow.json`:
  - Füll-Übereinstimmung mit dem Journal
  - Einstiegsabweichung in bp
  - Papier-R gegen Journal-R
  - Verzögerung von der Planerstellung bis der Schatten den Plan sieht und bis zur Füllung
  - Isolationsnachweis je Schritt
  - `orders_sent_to_exchange: 0`
- Fällt die Isolationsprüfung durch, hält der Schatten an (`halted`) und simuliert nichts mehr.
- Kerzen werden nur angehängt, nie überschrieben. Die gespeicherten Kerzen sind bei 20.000 gedeckelt; Kerzen, die
  ein offener Plan noch braucht, bleiben erhalten.

Ausgang V2.9 laut Meilenstein: dauerhafter Nachweis von null Orders **und Freigabe durch Menschen**. Den Nachweis
liefert der Schatten, die Freigabe bleibt bei Uzi und Chris.
