# R-KI-1: KI entscheidet an starken Zonen (Papier) – Präregistrierung, Entwurf 0.1

Stand 23.11.2026. Auslöser: Uzi 23.11.2026 ("wenn viele Sachen übereinander lappen muss gewichtet werden …
TIM muss verstehen und nicht einzelne Regeln testen, wir haben ja theoretisch die KI"; danach "go KI").
Nur Papier, nur vorwärts (live). Kein Echtgeld, der Live-Trader liest das Protokoll nicht. Kein Holdout.

## Frage

Trifft die lokale KI (Ollama, `qwen3.5:9b`, wie KI1), die an einer starken Zone das ganze Bild sieht, nach
Kosten bessere Papier-Entscheidungen als die festen Kreis-Regeln R-ABS-2 0.6 (mit Zone / ohne Zone)?

## Ablauf (Code `src/research_lab/ki_entry/`)

1. **Zonen-Stärke** (`zones.py`, fest, nicht angepasst): jede aktuelle Chart-Marke im Umkreis von 4 % bekommt
   ein Gewicht: Gamma-Zone mit Orderbuch-Mauer 4; Call/Put Wall 3; OI-Wand und Gamma-Flip 2; Max Pain und
   erwartete Spanne 1; Jahr/Quartal/Monat 3; Woche 2; naked POC 2; Tag 1,5; Liquidations-Cluster 1,5;
   Strong/Weak High/Low 1,5; laufender POC, Session, IB, VWAP je 1; meistgehandelter Preis der letzten
   48 Footprint-Kerzen 2. Marken innerhalb 0,4 % bilden eine Zone. Früheres Abprallen (Docht in die Zone,
   Schluss zurück; letzte 96 Kerzen) +0,5 je Mal, höchstens +1,5. **Stark ab 6.**
2. **Auslöser**: die neueste geschlossene 15m-Perp-Kerze berührt eine starke Zone; gefragt wird nur bis
   7 Minuten nach Kerzenschluss; kein Papier-Trade offen; keine überlappende Zone in den letzten 6 Stunden
   gefragt; jede Kerze höchstens einmal. Laufende Kerze und laufende Footprint-Kerze zählen nie.
3. **KI-Entscheidung**: die KI sieht Zone (Marken, Stärke, Annäherung von oben/unten, frühere Abpraller),
   die nächsten Zonen darüber/darunter, die letzten 12 Kerzen mit Delta und Volumen, große Orders ≥50 BTC
   der letzten 3 Stunden, Trend (4 h, 24 h, 3 Tage, letzter Strukturbruch), Funding, OI-Änderung 24 h.
   Antwort LONG/SHORT/NICHTS mit Einstieg, Stop, Ziel, Vertrauen, Grund.
4. **Prüfung**: Einstieg ≤0,5 % vom Preis, Stop 0,15–3 %, Stop und Ziel auf der richtigen Seite, Ziel ≥1,5× Stop.
   Sonst UNGUELTIG (wird geschrieben, nie gehandelt).
5. **Papier**: Die Kerze, in der die KI antwortet, wird übersprungen. Limit-Einstieg in den 4 Kerzen danach (1 h),
   sonst "nicht gefüllt". Risiko = geplanter Abstand Einstieg–Stop. Berührt eine Kerze Stop und Ziel, zählt der
   Stop; in der Füll-Kerze zählt nur der Stop; öffnet eine Kerze jenseits des Stops, Ausstieg zum Eröffnungskurs.
   Spätestens nach 24 h Schluss zum Kerzenschluss. Fehlen die Kerzen dafür dauerhaft: "Daten fehlen", nicht gezählt.
   Kosten 0,10 % vom Einstieg (Bitunix, Maker rein, Taker raus, Spread/Schlupf), in R abgezogen.
6. **Protokoll**: append-only mit Hash-Kette und Kopf-Datei (wie KI1). Entscheidung wird geschrieben, bevor das
   Ergebnis bekannt ist; das Ergebnis kommt als eigener Eintrag. Ein Fehler der KI schreibt nichts.

## Urteil (Entwurf, wird vor dem ersten Urteil eingefroren)

- Frühestens ab **30 gefüllten Papier-Trades**.
- Bestanden, wenn Mittel netto ≥ +0,10 R und die untere Grenze des 90-%-Bootstrap-Intervalls > 0.
- Vergleich mit R-ABS-2 0.6 (mit Zone, ohne Zone) im selben Zeitraum; drei Läufe = Mehrfachtest, so berichtet.
- NICHTS und UNGUELTIG werden mitgezählt und berichtet (wie oft die KI auslässt).

## Grenzen

- Ein kleines lokales Modell, Temperatur 0. Seine Antworten können schwanken, wenn sich Ollama oder das Modell
  ändern; Modellname steht in jedem Eintrag.
- Zonen-Gewichte sind eine Setzung vor jedem Ergebnis, kein Optimum. Änderungen nur als neue Version mit neuem PR.
- 15m-Kerzen: innerhalb einer Kerze ist die Reihenfolge von Stop und Ziel unbekannt, daher Stop zuerst (vorsichtig).
- Das Chart-Modell zeigt die Marken von jetzt; der Auslöser nutzt nur die neueste geschlossene Kerze, also nichts aus
  der Zukunft.

## Betrieb

Mac-Agent `com.tim.ki-entry` (Vorlage `ops/launchd/com.tim.ki-entry.plist`, alle 5 Minuten), Protokoll
`~/Library/Application Support/TIM/ki-entry/ki_entry_decisions.jsonl`. Auswertung:
`python -m src.research_lab.ki_entry report`. Einrichten erst auf Uzis "einrichten".

## Zusatz 0.1-hermes (Uzi 23.11.2026 "go hermes")

- **Zweitmeinung**: Nach jeder KI-Entscheidung bekommt Hermes (DeepSeek, Cloud) die öffentlichen Zahlen (Preis, Zone und
  Marken, Aktion, Einstieg/Stop/Ziel, Grund, letzte Kerzen mit Delta, große Orders, Trend, Funding, OI) und antwortet
  DAFÜR / DAGEGEN / URTEIL. Keine Schlüssel, keine Kontodaten, kein Code. Höchstens 20 Minuten nach der Entscheidung,
  höchstens ein Aufruf je Lauf. Die Meinung ändert nichts am Papier-Trade. Ausgewertet wird, ob DAFÜR/DAGEGEN die
  Ergebnisse trennt (ab 30 Trades, zusätzlicher Test, so berichtet).
- **Bitunix-Papierkonto**: jeder beendete KI-Papier-Trade wird auf 1.000 USDT gebucht: 1 % Risiko, Maker 0,02 % rein,
  Taker 0,06 % raus (Uzis VIP0-Angaben, nicht amtlich bestätigt), 0,05 % Schlupf am Stop, Marge höchstens 5 % des
  Kontos (Hebel daraus), Prüfung gegen die Bitunix-Hebelstufen. Kein Auftrag, der Bitunix-Schlüssel wird nicht benutzt.


## Änderung 0.2 (24.11.2026, Entwurf)

Anlass: Uzi 24.11.2026 10:14 „so jetzt sollte die KI smart money und das london sell off sehen sollen. short einstieg
waere reasonable und moeglich gewesen". Die KI wurde um 08:00 an der Zone gefragt (NICHTS); den Abverkauf zur
London-Eröffnung ab 09:00 hat sie nicht mehr gesehen, weil die Zone noch 6 Stunden gesperrt war.

- Neues Bild für die KI (`ki-einstieg/2`): `sitzung` (jetzige Sitzung, Asia-Hoch/-Tief 00:00–08:00 UTC, London-
  und New-York-Eröffnung, Änderung seit Eröffnung, Hoch/Tief seither, ob Asia-Hoch oder -Tief genommen wurde) und
  `smart_money` (Spot- und Perp-CVD über 1 h und 4 h, OI 1 h und 4 h, Liquidationen der letzten 3 h nach Seite,
  die zwei größten Liquidations-Cluster je Seite innerhalb 3 %, große Orders je Seite, Premium). Alles nur aus
  Werten vor dem Schluss der Entscheidungskerze; der laufende Balken wird nicht gezeigt.
- `zone.schluss`: Schluss der Kerze in, unter oder über der Zone (Bruch sichtbar).
- Antwortfeld `lesart` (HAELT / BRICHT / UNKLAR) vor der Aktion; NICHTS nur bei UNKLAR oder ohne sinnvollen
  Stop/Ziel. Grund: Nachspielen des Morgens 24.11. (09:15, 09:30, 09:45) mit dem neuen Bild ergab dreimal NICHTS,
  zweimal mit dem eigenen Grund „klarer Bruch nach unten“. Das ist ein Nachspielen, kein Beleg.
- Anweisung ergänzt um Sitzung (Stops über Asia-Hoch/unter Asia-Tief, Fortsetzung oder falscher Bruch) und Smart
  Money (Spot vs. Perp, OI mit Preis, Liquidationen, Cluster als Ziel); ein klarer Bruch in Trendrichtung zählt
  wie ein Abpraller.
- Sperre je Zone: weiter 6 h, aber eine neue Sitzung (Asia, London, London+New York, New York, nach New York)
  darf dieselbe Zone wieder fragen.
- Entscheidungen 0.1 und 0.2 stehen im selben Protokoll und werden über `prompt_version` getrennt gezählt
  (`by_prompt` im Bericht). Bisher (24.11. 10:00) nur drei Entscheidungen 0.1, alle NICHTS, kein Trade.
- Nicht eingefroren. Ein Urteil gibt es erst mit genügend 0.2-Trades; die Grenze steht noch aus.

## R-KI-2 0.1 (24.11.2026, Entwurf): DeepSeek entscheidet selbst

Anlass: Uzi 24.11.2026 11:03 „go deepseek“. Beim Nachspielen des Morgens (09:15, 09:30, 09:45, Zonen von heute,
also kein Beleg) antwortete DeepSeek SHORT, SHORT, LONG; das lokale Modell dreimal NICHTS.

- Gleiche Auslöser, gleiches Bild und gleiche Anweisung wie R-KI-1 0.2 (`ki-einstieg/2`), Entscheider ist DeepSeek
  über Hermes (`deepseek.py`). Eigenes Protokoll `ki_entry_decisions_deepseek.jsonl`, eigenes Bitunix-Papierkonto
  (1.000 USDT, 1 % Risiko). DeepSeek ist ein Cloud-Dienst: im Auftrag stehen nur öffentliche Marktzahlen.
- Zweimal gefragt; Trade nur, wenn beide Antworten dieselbe Aktion nennen, sonst NICHTS („Antworten uneinig“).
  Plan (Einstieg, Stop, Ziel) aus der ersten Antwort.
- Feste Schutzregeln (`decide.DEEPSEEK_PROFILE`), von der KI nicht änderbar: Stop mindestens 0,5 %, Ziel mindestens
  2 × Stop, höchstens 3 Trades je Tag (Ortszeit), nach 2 Verlusten in Folge am selben Tag keine Frage mehr.
- Papier-Abwicklung, Kosten und Protokoll wie R-KI-1. Keine Orders, kein Schlüssel.
- R-KI-1 und R-KI-2 sind zwei Tests nebeneinander (Mehrfachtest, so berichten). Urteil je Lauf frühestens ab
  30 gefüllten Trades; Grenze (Entwurf): Mittel ≥ +0,10 R und untere Grenze > 0. Nicht eingefroren.

## Zusatz 24.11.2026: Summen-Blasen als Zonenmarke

Uzi 24.11.2026 12:25 „go summe“ (Bild der Signalgruppe: dort sind Orders am selben Preis zusammengezählt, Absorption klar
sichtbar). `src/dashboard/bubble_sum.py`: Binance-Perp-Orders ab 100.000 $ einer Seite, binnen 5 min und 0,10 %
um den Durchschnittspreis, zusammen mindestens 400 BTC aus mindestens 3 Orders = Summen-Blase; die 8 größten der
letzten 48 h als Linie im Chart (Gruppe `absorb`). Schwellen am Bild vom 23./24.11. nach Augenmaß gesetzt, nicht
getestet. Für R-KI-1 und R-KI-2 zählt eine solche Linie ab diesem Stand als Zonenmarke mit Gewicht 2
(`zones.GROUP_WEIGHT`, steht je Entscheidung in `rules`). Entscheidungen davor hatten diese Marke nicht.

## Änderung 24.11.2026 15:00: Stop-Regel (R-KI-1 0.3, R-KI-2 0.2, `ki-einstieg/3`)

Uzi 24.11.2026 15:01 „der Stop sollte wie der Einstieg gut kalkuliert werden“. Anlass: Der erste Papier-Trade von
R-KI-2 (LONG, Fill 60.218, Stop 59.890, also 110 USD unter der runden 60.000) wurde in einer Kerze mit Tief 59.712
ausgestoppt; danach stand der Preis wieder über 60.000. Ein Trade, kein Beleg.

- Neues Feld `stop_hilfe` im Bild: ATR der letzten 14 geschlossenen 15m-Kerzen, Puffer = 0,5 ATR, für LONG das Tief
  aus Zone und den letzten 12 Kerzen, für SHORT das Hoch; `stop_spaetestens` = Struktur ± Puffer. Liegt dieser Wert
  näher als der Puffer an einem Vielfachen von 500 USD jenseits des Preises, rückt er um den Puffer hinter die runde Marke.
- Prüfung im Code (die KI kann sie nicht ändern): Ein Stop vor `stop_spaetestens` wird als UNGUELTIG geschrieben und
  nicht gehandelt. Mindest- und Höchstabstand, Mindest-Ziel und Kosten bleiben.
- Anweisung: Stop so sorgfältig wie der Einstieg; wird er zu weit für das Mindest-Ziel, Einstieg näher an die Struktur
  legen oder NICHTS.
- Nachrechnung am Auslöser (kein Test, eine Beobachtung): `stop_spaetestens` wäre 59.212 gewesen (Tief 59.366, ATR 308);
  das Tief danach war 59.712. Ob DeepSeek mit diesem weiten Stop (1,9 %) überhaupt einen Trade gegeben hätte, ist offen.
- Erwartete Nebenwirkung: weniger Trades, weitere Stops, kleinere Positionsgröße je Risiko. Die Auswertung trennt die
  Versionen über `rule` und `prompt_version`; Entscheidungen vor der Änderung zählen nicht zur neuen Version.
