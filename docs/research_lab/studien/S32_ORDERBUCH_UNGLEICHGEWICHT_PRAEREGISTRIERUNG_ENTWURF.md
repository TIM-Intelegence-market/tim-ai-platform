# S32: Orderbuch-Ungleichgewicht in einer verteidigten Range („Pfad des geringsten Widerstands“) (Präregistrierung, Entwurf 0.2)

| Feld | Wert |
|---|---|
| Studie | S32 (nächste freie Nummer nach S31/S31b) |
| Version | **0.2, Entwurf.** Regeln als Code: `src/research_lab/studies/s32.py` (`Config`, SHA-256 in jeder Ergebnisdatei), Tests `tests/test_research_lab_s32.py`. `evaluate` ist gesperrt, bis die Version 1.x ist |
| Anlass | Barti 12./13.11.2026: Setup aus dem Video „The Only Orderflow Guide You'll Ever Need“ (6:22–9:55, S&P-Future) prüfen und, falls es trägt, in TIM einbauen. Beschreibung der Kette: `/mnt/project-files/s32-orderbuch/Was-der-Trader-macht-2026-11-12.md` (Projektdateien) |
| Protokoll | `../PROTOKOLL.md` Version 1.3, Kosten aus `src/research_lab/protocol.py` |
| Daten | Binance USDⓈ-M BTCUSDT, Tardis.dev `incremental_book_L2`, **nur die kostenlosen Tage (1. jedes Monats)**. Buchnachbau `src/research_lab/depth/` (PR #251), geprüft in `../reports/depth_p2_tardis_2020-06-01.md` |
| Holdout | ab 2025-01-01, wird nicht geladen (`depth.tardis` verweigert). Training 2020-06 bis 2022-12 (31 Tage), Validierung 2023–2024 (24 Tage) |
| Einordnung | Beobachtungsstudie mit gedachten Trades, ohne Registerplatz. Auch bei Bestehen kein Filter für S7b oder Engine (Abschnitt 9) |

## 1. Die Kette des Traders (fest, keine Variation)

Der Trader im Video reagiert nicht auf eine einzelne Zahl, sondern auf eine Kette. S32 übersetzt sie in feste
Regeln; jede Zeile ist **ein** Wert.

| Nr | Schritt | Regel in S32 |
|---|---|---|
| P1 | Buchmenge | je Sekunde die Menge im Band **±5 bp** um die Mitte, getrennt für Bid und Ask |
| P2 | „deutlich dünner“ | eigene Seite mindestens **2-mal** so groß wie die Gegenseite (Video: 1,7 bis 2,8) |
| P3 | hält an | **3 Sekunden** ohne Unterbrechung (gegen kurz aufblitzende Orders) |
| P4 | Range-Fenster | Hoch und Tief der Mitte in den letzten **15 Minuten** |
| P5 | Range-Breite | **20–60 bp** |
| P6 | verteidigt | Berührung = Mitte höchstens 10 % der Breite vom Rand; Abprall = danach mindestens 25 % der Breite weg. Jeder Rand mindestens **1 Abprall**, zusammen mindestens **3 Berührungen** |
| P7 | nahe am Rand | Mitte im **unteren Viertel** (Long) oder **oberen Viertel** (Short) |
| P8 | Marktorders (Video: 53 aggressive Verkäufe) | nicht Teil der Regel, spart Versuche |
| P9 | Ziel, Stop, Zeit | Einstieg 1 s später zur Mitte; Ziel **Range-Mitte**; Stop **5 bp jenseits des Rands**; höchstens **300 s** |
| – | Abstand | höchstens ein Ereignis je 300 s und Gruppe; die ersten 15 Minuten jedes Tages sind Anlauf; mindestens 95 % gültige Sekunden im Fenster |

**Kontrolle („Range-Lage allein“):** dieselben Schritte P4–P7, aber das Buch zeigt im Auslösemoment **nicht** zur
dünnen Seite. Sie misst, was Range und Rand ohne das Buch leisten.

Bartis Wahl: **P2 = 2:1, bestätigt am 13.11.2026.** Noch offen: P5 (20–60 bp) und P9 (Mitte oder
gegenüberliegender Rand). Ohne Änderung gelten die Werte oben. Jede Änderung nur **vor** dem Einfrieren.

## 2. Kosten vorab (Arithmetik, keine Messung)

Im Video bewegt sich der Preis 2–3 ES-Ticks, etwa 1 bp. TIM rechnet bei BTC (Protokoll 1.3) Taker-Gebühr 5 bp je
Seite und 3 bp Slippage beim Einstieg, beim Stop 5 bp mehr: **13 bp** pro Trade, **18 bp** mit Stop, Stress das
Doppelte. Beispiel Range 40 bp, Einstieg 5 bp über dem Rand: Ziel +15 bp, Stop −10 bp. Der Gewinn bei Treffer
deckt gerade die Kosten. Ehrliche Erwartung: H1 vielleicht, H2 kaum.

## 3. Fragestellung

| | Frage | Messung | Bestehen |
|---|---|---|---|
| H1 | Bringt das Buch etwas zur Range dazu? | Anteil „Ziel zuerst“ der Kette minus Anteil der Kontrolle | untere Grenze > 0 in Training **und** Validierung |
| H2 | Bleibt nach Kosten etwas? | mittleres Netto-R der Kette (R = Abstand zum Stop, Basiskosten) | untere Grenze > 0 in Training **und** Validierung; Stress berichtet |

- Untere Grenze: einseitig, Block-Bootstrap über Tage (9 999 Ziehungen, Seed 32), Bonferroni über H1 und H2
  (je α/2 = 0,025).
- Mindestmenge: 100 Ereignisse je Abschnitt in Kette **und** Kontrolle, sonst „nicht prüfbar“.
- Gezählt werden nur Ausgänge Ziel, Stop, Zeit. „Kein Platz“ (Einstieg schon hinter dem Ziel) und „fehlt“ (Tag
  endet im Horizont, Buch ungültig beim Einstieg) werden ausgewiesen, nicht gewertet.
- Deflated Sharpe: H2 zählt als **1 neuer Versuch** (N 64 → 65).
- Nur beschreibend: Long/Short getrennt, Sitzungen (Asien 00–07, London 07–13:30, New York 13:30–20 UTC), Spread.

## 4. Vorbelastung

- Keine TIM-Studie hat bisher Orderbuchdaten ausgewertet. Trade-basierter Orderflow ist gesehen (S2, S8, S19, S21,
  OF2, OFX): ohne belegten Vorteil.
- Gesehen ist **ein** Trainingstag (2020-06-01), technisch: Buchnachbau gegen Trades (P2-Bericht) und die
  **Ereigniszahl** dieses Tages (Kette 53, Kontrolle 129). Kein Ergebnis, kein Ausgang, keine Rendite.
- Die Parameter stammen aus dem Video und aus Überlegungen zu den Kosten, nicht aus Daten.
- Der 1. eines Monats ist kein zufälliger Tag; das wird als Grenze berichtet.
- Zeitversatz Buch/Trades (P2: 90 % der Trades genau am besten Preis) spielt keine Rolle, weil S32 nur das Buch
  nutzt.

## 5. Daten und Rechenaufwand

55 Tage × etwa 0,4 GB gepackt, je Tag etwa 4 Minuten (Python, eine CPU). Rohdaten nie ins Repo (Tardis-Lizenz
Klausel 9.2), nur Zählungen und Ergebnisse. Die Preisstufe war 2020 0,01 USDT, heute 0,1; S32 rechnet nur in bp.

## 6. Ablauf und Prüfbefehle

1. Barti (Parameter) und Uzi lesen den Entwurf. Änderungen nur jetzt.
2. `pytest tests/test_research_lab_s32.py` grün (Pflicht vor jedem Lauf).
3. Zähllauf (ergebnisblind): `python -m src.research_lab.studies.s32 count --dir ~/TIM-research/tardis --out DIR --fetch`
4. Einfrieren als 1.0 nur mit Uzis Wort **und** Bartis Go (Digest in die Doku).
5. Auswertung einmal: `python -m src.research_lab.studies.s32 evaluate --dir ... --out DIR`. Kein Nachbessern.

## 7. Nicht Teil von S32

Andere Schwellen, Bänder, Fenster oder Ziele (wären neue Versuche), Marktorder-Bestätigung (P8), Spot-Buch, andere
Börsen, Maker-Einstieg, Echtgeld, Live-Orders.

## 8. Sperre

`evaluate` verweigert jeden Lauf, solange `VERSION` mit „0.“ beginnt.

## 9. Was bei Bestehen folgt

- Kein Einbau als Handelsregel. Nächster Schritt: Schattenlauf mit dem eigenen Recorder (Issue #253) und vorab
  festgelegten Zeitgrenzen.
- Besteht nur H1, kann TIM die Situation im Chart **anzeigen** (Barti 12.11.: „erkennen, wann man die Regel
  anwenden könnte“), als Hinweis, nicht als Signal.
- Fällt H1 durch, bringt das Buch in dieser Form nichts; dann auch keine Anzeige.
