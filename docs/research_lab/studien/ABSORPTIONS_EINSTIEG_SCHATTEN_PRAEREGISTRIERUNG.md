# Absorption als Einstieg, Ausstieg an der nächsten Gegen-Absorption: Schattenregel R-ABS-2 (Präregistrierung 0.1, ENTWURF, nicht eingefroren)

Auftrag Uzi 17.11.2026 ("Die Absorption könnte doch getradet werden"). Anlass: BTCUSDT 1h, 17.11. (Handy-Screenshot). Bei ~65.200 (1D-VAH-Bereich) zeigt der Chart eine Kauf-Absorption (Kreis "500"), danach fällt der Preis bis ~63.300 nahe der Opt Put Wall 63.000; unten steht ein Kreis nahe 63.600. Uzi: Absorption als Einstieg ist "auf jeden Fall ein guter Ansatz"; **bei der nächsten Absorption werden je nach Long/Short die Gewinne realisiert**; wichtige Zonen und vor allem **Akkumulation** sollen erkennbar sein. **Nichts gerechnet, kein Ergebnis gesehen. Ob der Fall vom 17.11. von den unten definierten Schwellen überhaupt erfasst würde, ist ungeprüft.**

Status: Entwurf. Einfrieren (1.0) erst auf Uzis "einfrieren", Zeitplan erst auf "Zeitplan an", Merge nur auf "merge". Nur Papier/Schatten, kein Echtgeld, Holdout 2025 tabu, kein Backtest (Orderflow nur vorwärts).

## Abgrenzung
- R-ABS-1 (eingefroren) **blockiert** Pläne, die in ein absorbierendes Level laufen. R-ABS-2 **handelt** gegen die Absorption. Eigene Hypothese, eigene Pläne, eigenes Urteil; R-ABS-1 bleibt unberührt.
- Es wird kein bestehendes Journal, Score oder Limit verändert. R-ABS-2 hat ein eigenes Papier-Journal.

## Hypothese H2 (neu, ungeprüft)
Wird eine **Absorption an einer wichtigen Zone** nach Bestätigung gegen die absorbierte Seite gehandelt (Verkaufs-Absorption an Unterstützung → Long, Kauf-Absorption am Widerstand → Short), und die Position an der **nächsten Absorption in Gegenrichtung** geschlossen, ist das Mittel Netto-R nach Bitunix-Kosten > 0.

## Bausteine (Schwellen sind Entwurf, bis zum Einfrieren änderbar)
1. **Absorptions-Ereignis** (je Zeitrahmen 15m und 1h, Kerzenschluss): Level-/Kerzenvolumen ≥ 3× Median (wie `absorption_volume_factor` der Live-Lage), Preis kommt nicht durch (Schluss zurück auf der Gegenseite des Extrems, Range ≤ 0,8× Median-Range), Delta-Seite = absorbierte Seite. *Kauf-Absorption* = aggressive Käufer, Preis steigt nicht; *Verkaufs-Absorption* = spiegelbildlich. Datenquelle: Binance-Spot-aggTrades des PS5-Recorders (`OF_LIVE`, Minutenbars mit Profil), gleiche Kette wie das OF-Live-Journal.
2. **Wichtige Zone:** Absorptions-Ereignis liegt innerhalb ±0,15 % eines Levels aus der Level-Tabelle (1D/1W VAH, VAL, POC, Opt-Wand, Swing-Hoch/-Tief). Ohne Zone kein Einstieg.
3. **Einstieg** (kausal): erst nach Bestätigung, d. h. die nächste Kerze schließt vom Extrem weg (Long: Schluss über dem Absorptionsschluss; Short: darunter). Papier-Fill zum Open der Folgekerze plus Slippage; kein Look-ahead.
4. **Stop:** knapp hinter dem Extrem der Absorptionszone (Docht-Ende) + 0,1 × ATR(14) des Zeitrahmens. Pläne mit Stopp-Abstand < 0,4 % (Kostentor ~0,15 R bei Bitunix) werden **mitgezählt, aber als "kostenblockiert" getrennt ausgewiesen**, nicht still verworfen.
5. **Ausstieg (Kern, Uzi):** erste **Gegen-Absorption** nach dem Einstieg (Long: Kauf-Absorption an Zone/Level oberhalb; Short: Verkaufs-Absorption darunter), Exit zum Close der Ereigniskerze. Gleiche Erkennung wie Baustein 1, kausal.
   - Rückfall (fest): Stop; Zeitstopp 48 Kerzen; Ziel = nächstes wichtiges Level, falls vorher erreicht.
   - Referenzvarianten nur zum Vergleich, **nicht** im Urteil: fixes 2R; Exit am nächsten Level.
6. **Kontext-Flag Akkumulation** (nur mitgeschrieben, nicht im Urteil): Range ≥ 8 Kerzen (1h), Breite ≤ 3 × ATR, ≥ 2 Verkaufs-Absorptionen nahe dem Boden der Range, kumuliertes Delta der Range ≥ 0 (Spiegelbild: Distribution am Dach). Auswertung nur deskriptiv (n, Mittel R mit/ohne Flag). Ein Effekt der Akkumulation wäre H3, eine eigene Version mit neuen Plänen.
7. **Kosten:** Bitunix-Futures: Taker-Gebühr je Seite, 1–2 bps Slippage angenommen, Funding nach tatsächlichen Intervallen, Cross-Margin 0,5–5 % Marge. Die konkreten Sätze aus der Bitunix-Studie vor dem Einfrieren eintragen (**Wert hier nicht erfunden, offen**).

## Datenerfassung (Lücke aus R-ABS-1)
Der Orderflow-Schatten speichert nur 3 nächste Level. R-ABS-2 braucht je Ereignis: Zeit, Zeitrahmen, Seite, Volumen, Delta, Range, Extrem, Zone/Level-Name, Distanz. Eigenes Journal `data/journal/tim_absorption_entry_shadow.json`, nur Anhängen, Hash-Kette wie die anderen Schatten. Der Footprint-Kreis im Chart ("500") ist **nicht** zwingend dasselbe wie die Level-Absorption der Live-Lage; welche Chart-Definition genau dahintersteht, ist vor dem Einfrieren im Chart-Code nachzulesen (offen).

## Auswertung (Entwurf, fest ab Einfrieren)
- Beurteilbar bei **≥ 30 geschlossenen R-ABS-2-Trades** (nicht kostenblockiert), Netto-R inkl. Kosten.
- **Bestanden**, wenn Mittel ≥ +0,10 R **und** die einseitige untere 95-%-Bootstrap-Grenze > 0 (10.000 Ziehungen, Seed 17). Sonst nicht bestanden; Fehlschlag wird berichtet, keine Nachjustierung auf denselben Trades.
- Immer zeigen: alle Ereignisse, Einstiege, kostenblockierte, Long/Short, Zeitrahmen, Anteil Exit durch Gegen-Absorption/Stop/Zeitstopp/Level, Referenzvarianten, Flag Akkumulation ja/nein.
- Erwartung ehrlich: 15m/1h an Zonen ergibt wenige Ereignisse pro Woche; 30 Trades können Monate dauern. Seit 11.11. verwirft das OF-/Kostentor im alten Pfad fast alles, deshalb eigenes Journal.

## Offen vor dem Einfrieren
Schwellen (Zone ±0,15 %, Stop-Puffer, Zeitstopp), Bitunix-Kostensätze, Chart-Definition des Kreises, Akkumulations-Parameter, Ort der Ausführung (PS5-Dienst neben `OF_LIVE` vs. Mac). Alles Uzis Entscheidung bzw. aus Code zu belegen.
