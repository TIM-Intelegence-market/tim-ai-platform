# Gamma-Trading lernen (Gamma Scalping und GEX)

Lernunterlage für TIM. Sie erklärt Gamma aus dem Optionshandel und zeigt, wie TIM daraus
eine **Beobachtung** macht. TIM handelt nicht: kein Order-, Hedge- oder Kontopfad (siehe
`src/options_gamma/`). Keine Anlageberatung.

## 1. Die vier Greeks, die man braucht

| Greek | Frage | Faustregel |
|---|---|---|
| Delta (Δ) | Wie viel bewegt sich der Optionspreis, wenn der Basiswert um 1 steigt? | Call 0 bis 1, Put −1 bis 0, at the money ungefähr ±0,5 |
| Gamma (Γ) | Wie stark ändert sich Delta, wenn der Basiswert um 1 steigt? | Am größten at the money und kurz vor Verfall |
| Theta (Θ) | Wie viel Zeitwert verliert die Option pro Tag? | Wer Gamma kauft, zahlt Theta |
| Vega | Wie stark reagiert der Preis auf implizite Volatilität? | Wichtig für Gamma Scalping, weil man Volatilität kauft |

Formel (Black-Scholes, ohne Dividende, Zins r):

```
d1    = (ln(S/K) + (r + σ²/2)·T) / (σ·√T)
Γ     = φ(d1) / (S · σ · √T)          gleich für Call und Put
Δcall = N(d1),   Δput = N(d1) − 1
```

`S` Kurs, `K` Strike, `T` Restlaufzeit in Jahren, `σ` implizite Volatilität, `φ` Dichte und
`N` Verteilungsfunktion der Normalverteilung. Im Code: `src/options_gamma/greeks.py`.

## 2. Gamma Scalping (Variante a)

Idee: Man kauft Gamma (zum Beispiel einen at-the-money Straddle) und hält das Delta per
Hedging bei null. Steigt der Kurs, wird man Long-Delta und verkauft den Basiswert. Fällt er,
wird man Short-Delta und kauft nach. So verkauft man immer oben und kauft unten.

- Gewinn aus dem Hedging pro Bewegung `ΔS`: ungefähr **½ · Γ · ΔS²**
- Kosten: Theta, ungefähr **½ · Γ · S² · σ² · dt** pro Zeitschritt `dt`

Beides gleicht sich genau dann aus, wenn sich der Kurs so stark bewegt, wie die implizite
Volatilität es einpreist. Daraus folgt die wichtigste Regel:

> Gamma Scalping verdient nur, wenn die **realisierte** Volatilität höher ist als die
> **implizite**, die man beim Kauf bezahlt hat. Gebühren und Slippage kommen noch dazu.

Break-even-Bewegung pro Tag: `S · σ / √365`.

In TIM gibt es dafür später höchstens eine Simulation auf historischen Daten (Paket 5), nie
Live-Hedging.

## 3. Gamma Exposure, GEX (Variante b)

Market Maker sichern ihre Optionsbestände per Delta-Hedging ab. Ihr Gamma bestimmt, in welche
Richtung sie dabei handeln müssen:

| Dealer-Gamma | Hedging | Wirkung auf den Markt |
|---|---|---|
| positiv | gegen die Bewegung (oben verkaufen, unten kaufen) | dämpft, eher Range und Rückkehr |
| negativ | mit der Bewegung (oben kaufen, unten verkaufen) | verstärkt, eher Trend und Ausbrüche |

GEX pro Option in USD pro 1 % Kursbewegung:

```
GEX = Γ · Open Interest · Multiplikator · S² · 0,01
Calls zählen positiv, Puts negativ
```

Das Vorzeichen ist eine **Annahme**: Kunden kaufen Calls und Puts, Dealer sind also Long Calls
und Short Puts. Open Interest verrät nicht, wer wirklich Long oder Short ist. GEX ist deshalb
immer eine Schätzung.

Die Marken, die man daraus liest:

| Marke | Bedeutung | Im Code |
|---|---|---|
| Net GEX | Summe über alle Strikes, Vorzeichen = Regime | `GexProfile.net_gex`, `regime` |
| Gamma Flip | Kurs, bei dem Net GEX das Vorzeichen wechselt | `gamma_flip` (Raster über die Strikes) |
| Call Wall | Strike mit dem größten Call-GEX, oft Widerstand | `call_wall` |
| Put Wall | Strike mit dem größten Put-GEX, oft Unterstützung | `put_wall` |

Ergänzend auf dem Chart: VWAP, Vortageshoch und -tief, Implied Move aus dem Straddle-Preis,
DVOL oder VIX, Volumen und Orderflow (in TIM vorhanden), ATR für Stops.

## 4. Was TIM daraus macht

`src/options_gamma/` rechnet aus einem Snapshot einer Options-Chain ein GEX-Profil und die
Beobachtung `gex_regime` (`POSITIVE_GAMMA_REGIME`, `NEGATIVE_GAMMA_REGIME` oder
`NEUTRAL_GAMMA_REGIME`) mit Regel-ID, Version, Input-Hash und Modus `OBSERVE`. Die
Beobachtung beschreibt Kontext. Sie ist kein Signal und keine Prognose.

Beispiel mit der **synthetischen** Chain `tests/fixtures/options_gamma/btc_chain_sample.json`
(Spot 67 000, keine echten Marktdaten):

```
python -c "import json; from src.options_gamma import *; \
p = compute_gex_profile(*load_chain_snapshot(json.load(open('tests/fixtures/options_gamma/btc_chain_sample.json')))); \
print(p.regime, round(p.net_gex), p.call_wall, p.put_wall, round(p.gamma_flip))"
```

Ergebnis: `POSITIVE_GAMMA 2857362 70000.0 65000.0 64196`. Der Kurs liegt über dem Gamma Flip,
zwischen Put Wall 65 000 und Call Wall 70 000.

### Echte Daten im Control Center (seit 27.10.2026)

Die Runtime liest alle 5 Minuten Deribits öffentliches Optionsbuch (`get_book_summary_by_currency`
und `get_index_price`, kein Key, kein Konto; `src/dashboard/gamma_data.py`) und rechnet daraus mit
`src/options_gamma/snapshot.py` einen Schnappschuss (Strikes ±35 % um den Preis):

- **Gamma Flip**: der Preis, an dem das geschätzte Händler-Gamma das Vorzeichen wechselt, der
  Schnittpunkt nächst am aktuellen Preis (Suche ±15 %).
- **Call Wall / Put Wall**: größtes Call-Gamma über dem Preis, größtes Put-Gamma unter dem Preis.
  Zusätzlich die drei größten Open-Interest-Strikes je Seite.
- **Max Pain** und **Expected Move** (ATM-IV × √Zeit) des Hauptverfalls, das ist der Verfall mit
  dem meisten Open Interest in den nächsten 7 Tagen.

Wo es auftaucht:

- `/api/gamma?symbol=BTCUSDT`: ganzer Schnappschuss mit Alter (`stale` nach 20 Minuten).
- `/api/prep` → `gamma`: Regime, Level, `analysis_input`.
- Chart `/chart`: Gruppe „Options-Gamma (Deribit)“ (Flip orange, Call Wall grün, Put Wall rot,
  Max Pain grau gestrichelt, Expected Move gepunktet). Nicht in der öffentlichen englischen Ansicht.
- Orderflow-Analyse: Eingabefeld `gamma` (der `analysis_input`-Block). Daraus werden Aussagen
  wie `above_gamma_flip_dealer_hedging_dampens_moves`, ohne Punkte, ohne Einfluss auf
  Konfidenz oder Entscheidung.

Alle Werte beruhen auf der Annahme „Händler long Calls, short Puts“. IBIT- und CME-Optionen
fehlen. Ohne Studie bekommt Gamma kein Gewicht.

Noch offen und bewusst nicht gebaut:

- Einbindung in die Observation Engine.
- Gamma-Scalping-Simulation als Backtest.
- Ob GEX bei BTC überhaupt etwas erklärt, ist nicht belegt. Der Optionsmarkt ist dünner als
  bei SPX. Das muss eine Studie zeigen, bevor die Beobachtung Gewicht bekommt.

## 5. Übungen

Rechne zuerst selbst, dann vergleiche mit den Lösungen unten.

1. **Gamma:** S = K = 100, Restlaufzeit 30 Tage, σ = 50 %, r = 0. Wie groß ist Gamma? Um
   wie viel ändert sich Delta ungefähr, wenn der Kurs um 2 steigt?
2. **GEX eines Strikes:** BTC-Spot 67 000. Call mit Strike 70 000, 30 Tage, σ = 48 %,
   Open Interest 1 000 BTC. Wie groß ist das GEX in USD pro 1 %? Positiv oder negativ?
3. **Gamma Scalping:** Du hältst einen at-the-money Straddle (S = 100, 30 Tage, σ = 50 %) auf
   1 Einheit. Gamma der Position = 2 × Gamma aus Aufgabe 1.
   a) Wie groß ist die Break-even-Bewegung pro Tag?
   b) Wie viel Theta zahlst du ungefähr pro Tag?
   c) Was bringt das Hedging an einem Tag mit einer Bewegung von 4? Und mit 1?

<details>
<summary>Lösungen</summary>

1. d1 = 0,5 · 0,5 · √(30/365) ≈ 0,0717, φ(d1) ≈ 0,3979, σ√T ≈ 0,1433.
   Γ ≈ 0,3979 / (100 · 0,1433) ≈ **0,0278**. Delta steigt um etwa 2 · 0,0278 ≈ **0,056**.
2. Γ ≈ 0,0000419. GEX = 0,0000419 · 1 000 · 67 000² · 0,01 ≈ **1,88 Mio. USD pro 1 %**.
   Positiv, weil es ein Call ist.
3. a) 100 · 0,5 / √365 ≈ **2,62** pro Tag.
   b) ½ · 0,0555 · 2,62² ≈ **0,19** pro Tag.
   c) Bewegung 4: ½ · 0,0555 · 16 ≈ **0,44**, also 0,25 Gewinn nach Theta.
      Bewegung 1: ½ · 0,0555 · 1 ≈ **0,03**, also 0,16 Verlust nach Theta.

Die Zahlen prüft `tests/test_options_gamma.py` mit (`bs_gamma(100, 100, 30/365, 0.5)`).

</details>
