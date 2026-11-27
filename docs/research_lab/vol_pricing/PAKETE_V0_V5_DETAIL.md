# Volatilität und Kontraktbewertung: Pakete V0–V5 im Detail (Entwurf 0.2, nur Planung)

Stand 24.11.2026. Ergänzt `docs/research_lab/vol_pricing/BESTANDSAUFNAHME_UND_FORSCHUNGSPLAN.md` (Draft #385 @462e10d).
Kein Code, kein Datenzugriff, keine Freigabe. Jedes Paket braucht ein eigenes GO des Inhabers. Mission 07 hat Vorrang.
TRADING_AUTHORIZED=NO. Holdout ab 2025 bleibt gesperrt.

## 0. Drei Ebenen, die nie vermischt werden

| Ebene | Frage | Beleg | Pakete |
|---|---|---|---|
| E-M Mathematische Korrektheit | Rechnet die Formel richtig? | Testvektoren, Identitäten, Eigenschaftstests | V0, Teile V5 |
| E-P Prognosequalität | Trifft die Vorhersage die später beobachtete Größe? | Verlustfunktion, Kalibrierung, Vergleich mit Baseline, ungesehene Daten | V2, V3, V4 |
| E-H Handelsvorteil | Bleibt nach Kosten Geld übrig? | eigene eingefrorene Studie mit Kosten, danach Papier | keines dieser Pakete |

Ein PASS auf E-M sagt nichts über E-P, ein PASS auf E-P nichts über E-H. Kein Paket hier darf einen Handelsvorteil behaupten.

Negative Vorergebnisse bleiben stehen und werden in jedem Bericht genannt: S15-1d nicht bestanden, S25 (GARCH-Größe) nicht
bestanden, S40 Training alle 12 Tests nicht bestanden, S24/S26/S27 nicht bestanden. S15-4h ist ein Prognose-PASS (E-P), kein Handelsvorteil.

## 1. Antworten auf die acht Anforderungen von ChatGPT (#issuecomment-7139388361)

| # | Anforderung | Antwort | Festlegung |
|---|---|---|---|
| 1 | RV als Varianzsumme vs. Volatilität, Einheiten, Annualisierung, gleiche Horizonte | ACCEPT | Grundgröße ist **Varianz** je Horizont h: `RVar_h = Σ r_i²` (5m-Log-Renditen, geschlossene Kerzen). Volatilität nur als abgeleitete Anzeige `σ_ann = sqrt(RVar_h · 365·24h/h)`. Jede Zahl trägt `unit` (`var_h`, `var_ann`, `vol_ann`) und `horizon`. IV wird vor jedem Vergleich in Varianz über **denselben** Horizont umgerechnet (Total-Varianz `IV²·T`). Vergleiche mit ungleichem Horizont sind ungültig (Test). |
| 2 | IV²−HV² nur ex ante, IV²−künftige RV ex post | ACCEPT | Zwei getrennte Namen: `vrp_proxy_exante(t) = IVvar_30d(t) − HVvar_30d(t)` (Merkmal, nur Daten ≤ t) und `vrp_realized_expost(t) = IVvar_30d(t) − RVar[t, t+30d]` (nur Zielgröße, erst ab t+30d verfügbar). Der Typ verhindert, dass ein Ex-post-Wert als Merkmal eingeht (Verfügbarkeitszeit = t+30d im PIT-Vertrag). |
| 3 | B76 Forward/Basis und Diskontierung getrennt, Multiplikatoren, inverse Abrechnung, Greeks-Einheiten, Löser-Grenzen | ACCEPT | Siehe V0. Forward je Verfall ist Eingabe (aus Future oder Put-Call-Parität), Diskontfaktor eigene Eingabe; keine stille Null. |
| 4 | DVOL-Kerzenbeginn/-schluss und Verfügbarkeit | ACCEPT | Bis belegt gilt: Zeitstempel = Kerzen**beginn**, Wert verfügbar ab `ts + Auflösung`. Beleg in V1 per Abgleich laufender gegen abgeschlossene Kerze (nur lesend, vorwärts). `dvol_change` bleibt bis dahin gesperrt für jede Nutzung. |
| 5 | Expected Move: Endwert-Abdeckung vs. Pfadberührung, 68 % nur Referenz, Überlappung | ACCEPT | Zwei getrennte Ziele: `cover_terminal` (Schlusskurs am Horizont im Band) und `touch_path` (Band irgendwann berührt). 68 % ist nur der Lognormal-Sollwert für `cover_terminal`; für `touch_path` gibt es keinen 68-%-Sollwert. Auswertung auf nicht überlappenden Horizonten als Hauptanalyse; überlappend nur mit Block-Bootstrap/HAC als Nebenanalyse. |
| 6 | Regime-Interaktion gegen B2, Signal ohne Interaktion als Baseline, passender Test, Mehrfachtests | ACCEPT | Baselines B0 (nichts), B1 (Kurs-Lags), B2 (B1 + Regime), **B3 (B2 + Signal ohne Interaktion)**. Regime-Mehrwert = Kandidat (B3 + Signal×Regime) gegen B3. Clark-West nur für verschachtelte Modelle mit quadratischem Verlust; für Richtung/QLIKE oder nicht verschachtelte Modelle Diebold-Mariano mit HAC bzw. Block-Bootstrap, vorab je Ziel festgelegt. Versuchszähler familienübergreifend (Stand 65) wird in der Präregistrierung fortgeschrieben; Holm je Familie plus Gesamtzahl im Bericht. |
| 7 | 2023–24 nur dann unabhängige Bestätigung, wenn nachweislich unberührt | ACCEPT, Status UNKNOWN | Vor V3 entsteht ein **Berührungsregister**: je Studie (S1–S41), welche Zeiträume für Auswahl, Schwellen oder Hypothesen angesehen wurden. Ist 2023–24 für eine Signalfamilie berührt, gilt sie dort als verbraucht; Bestätigung dann nur auf einem neuen, vorab gesperrten Vorwärtszeitraum (Start nach Einfrieren). Bis das Register vorliegt, wird 2023–24 **nicht** als unabhängiger Nachweis bezeichnet. Holdout 2025 bleibt zu. |
| 8 | beobachtet/modelliert plus Herkunft und Berechnung; Arbitrageprüfung auf Preisen; fehlende Quotes UNKNOWN | ACCEPT | Drei Felder statt einem: `kind` (`observed`, `observed_model_output`, `modelled`), `origin` (Quelle, Endpunkt, Empfangszeit), `method` (Formel, Version, Eingaben). Börsen-IV (`mark_iv`, Trade-IV, DVOL) ist `observed_model_output`. Arbitrageprüfungen laufen auf **Preisen** (Bid/Ask, Forward, Strike), nicht auf geglätteter IV. Fehlende Quote = UNKNOWN, nie 0, nie interpoliert (gleiche Regel wie Mission 07-FINAL). |

## 2. Pakete

Gemeinsam für alle: reine Funktionen, keine neue Options-Engine neben `src/options_gamma/` und
`src/research_lab/options_flow/`; vorhandenes wird erweitert. Zeitvertrag `pit-contract/1`. Fehlende Eingabe = UNKNOWN.

### V0 – Mathematische Grundlage (Ebene E-M, kein Datenzugriff)

**Inhalt.** Preis und IV-Löser für Black-Scholes (Spot, mit Zins und Carry) und Black-76 (Forward), Greeks
(Delta, Gamma, Vega, Theta, Rho, Vanna, Charm), HV 7/14/30/90, lineare und inverse Kontrakte.

**Konventionen (werden festgeschrieben).**
- Zeit: Jahr = 365 Tage, Kalenderzeit, Verfall 08:00 UTC; `T` in Jahren aus Millisekunden.
- B76: `C = DF·[F·N(d1) − K·N(d2)]`, `d1 = [ln(F/K) + σ²T/2]/(σ√T)`. `F` und `DF` sind getrennte Pflichteingaben.
- Einheiten der Greeks ausdrücklich: Delta je 1 Einheit Basiswert; Gamma je 1 USD; Vega je 1,00 Vol (zusätzlich je Vol-Punkt = /100); Theta je Jahr (zusätzlich je Tag = /365).
- Linear (USDT-abgerechnet): Wert = Preis_USD × Menge × Multiplikator.
- Invers (BTC-abgerechnet, Deribit): Prämie in BTC = Preis_USD / S; Delta in BTC = Delta_USD − Prämie_BTC (Prämien-bereinigt); beides als eigene benannte Funktionen, nie stillschweigend.
- IV-Löser: Suchbereich σ ∈ [0,0001; 10], Newton mit Rückfall auf Bisektion, Toleranz 1e-8 im Preis. Preis außerhalb der Arbitragegrenzen (unter innerem Wert, über Forward/Strike-Grenze), Vega nahe 0 oder T ≤ 0 ergeben **kein Ergebnis mit Grund** (`NO_SOLUTION_*`), nie eine Randzahl.
- HV: Stichproben-Std. der Log-Renditen geschlossener 1d-Kerzen (n−1), Faktor √365; n = 7/14/30/90; weniger als n Renditen = UNKNOWN. Parkinson/Garman-Klass/Yang-Zhang nur als gekennzeichnete Nebenschätzer.

**Abnahme.**
1. Referenzvektoren aus mindestens zwei unabhängigen Quellen (Lehrbuchbeispiel Hull, analytische Sonderfälle) auf 1e-10.
2. Identitäten als Eigenschaftstests (Hypothesis): Put-Call-Parität `C − P = DF·(F − K)`; Preis monoton in σ; Rückrechnung `IV(Preis(σ)) = σ` im Löserbereich; Grenzen σ→0 und T→0; Greeks gegen finite Differenzen; B76 = BS bei `F = S·e^{(r−q)T}`.
3. Invers: Rundreise USD ↔ BTC, Delta-Bereinigung gegen Zahlenbeispiel.
4. Bestehende Tests von `greeks.py` und `models.py` laufen unverändert; keine doppelte Formel im Repo.
5. Kein Netz-, Datei- oder Datenbankzugriff im Paket (Test).

**Nicht-Ziele.** Keine Marktdaten, keine Fläche, kein Signal, keine Chart-Anzeige.

### V1 – Datenreife (nur lesen, Bericht; Ebene: Datenqualität)

**Inhalt.** Für jede Eingangsgröße ein Reife-Urteil: HV/RV (Binance-Kerzen), IV (Deribit Trade-IV historisch,
`mark_iv` live, DVOL), Futures-Basis (Quartals-Future, Perp-Prämienindex), Funding.

**Je Quelle wird berichtet.** Zeitraum, Abdeckung in %, Lücken (Liste), Duplikate, Zeitstempel-Bedeutung
(Beginn/Schluss, Börsenzeit/Empfangszeit), Verfügbarkeitszeit nach PIT-Vertrag, Feldtypen (strenge Parser, B2-Befunde
#383 beachten), Revisionen, Herkunftsmanifest (Datei-Hash, Parser-Version, Code-SHA), Zuordnung zu Training /
Validierung / Holdout.

**Regeln.** Nur der Trainingszeitraum (bis 2022) wird inhaltlich geöffnet; für Validierung und Holdout nur
Existenz und Zeilenzahl, keine Werte. Fehlende Werte bleiben fehlend. DVOL-Zeitstempel wird nur vorwärts belegt.

**Abnahme.**
1. Reife-Tabelle je Quelle mit Urteil READY / READY_WITH_LIMITS / NOT_READY und Begründung.
2. Manifest reproduzierbar (zweiter Lauf, gleicher Hash).
3. Der Lader verweigert Zeiträume ab 2025 (Test) und liefert für Validierung keine Werte.
4. Berührungsregister (Anforderung 7) liegt vor.
5. Codex hat die Zeitstempel-Aussagen unabhängig nachvollzogen.

**Abhängigkeit.** V0 nur für Einheiten; B2-Entscheidung zu den nachsichtigen Parsern (#383).

### V2 – Modellkalibrierung (Prognosestudie, Ebene E-P, nur Training)

**Inhalt.** Expected Move, EWMA, GARCH(1,1) (aus S15, nicht neu gebaut), Prognoseintervalle.

**Protokoll (vor dem Lauf eingefroren).**
- Ziele: `RVar_h` für h = 4h, 1d, 7d; Intervall-Abdeckung nominal 50/68/90/95 %.
- Verlust: QLIKE (Hauptmaß) und MSE auf Varianz; Intervalle: Abdeckungsrate mit Kupiec-Test und Unabhängigkeit (Christoffersen), Kalibrierungskurve, mittlere Bandbreite.
- Expected Move: `cover_terminal` und `touch_path` getrennt; nicht überlappende Horizonte als Hauptanalyse.
- Baselines: rollierende Varianz (wie S15), Random-Walk der Varianz.
- Unsicherheit: Block-Bootstrap-Intervalle; Mindeststichprobe je Horizont vorab.
- Nur Training; kein Parameter wird nach Sicht auf Validierung gewählt.

**Abnahme.** Bericht mit allen Horizonten, auch den schlechten; bekannte Vorergebnisse (S15-4h PASS, S15-1d FAIL,
S25 FAIL) stehen im Kopf; Aussage ausdrücklich nur E-P; Lauf aus Manifest reproduzierbar.

**Nicht-Ziele.** Keine Positionsgröße, keine Handelsregel, kein Chart-Band als "Ziel".

### V3 – Volatilitätsregime (Präregistrierung, dann genau ein Lauf; Ebene E-P)

**Inhalt.** Hängt die Prognosegüte von Orderflow- und Optionsflow-Signalen vom Regime ab?

**Regime.** Niedrig/Mittel/Hoch aus Terzilen von `HVvar_30` (Schwellen nur aus Training, fest); Expansion/Kontraktion
aus dem Vorzeichen der Änderung `HVvar_7 − HVvar_30` mit vorab festem Schwellwert. Alles nur aus Daten ≤ t.

**Design.** B0–B3 wie in Anforderung 6; Kandidat = B3 + Signal×Regime. Ziele: Rendite-Richtung und -Betrag 1h/4h/1d.
Testverfahren je Ziel vorab. Signalfamilien: Perp-Orderflow, Deribit-Optionsflow. Wachsendes Fenster mit Purge/Embargo.

**Ehrlichkeit.** S40 hat beide Familien im Training gesehen und nicht bestanden. Eine Regime-Aufteilung derselben
Daten erzeugt nur Hypothesen. Bestätigung nur auf Daten, die laut Berührungsregister unberührt sind; sonst neuer
gesperrter Vorwärtszeitraum. Kein Erfolg wird aus Training berichtet.

**Abnahme.** Präregistrierung von Codex geprüft und eingefroren, bevor irgendein Regime-Ergebnis existiert;
Versuchszähler fortgeschrieben; ein einziger Bestätigungslauf; Ergebnis wird veröffentlicht, egal wie es ausfällt;
"nicht bestanden" ist ein gültiges Endergebnis.

**Abhängigkeit.** V1, Codex-PASS Mission 07 (Seite UNKNOWN, PIT), B2-Parserfrage.

### V4 – Gamma und Liquidationen je Regime (nur Vorwärtsbeobachtung, Ebene E-P)

**Inhalt.** Verhalten an Gamma-Zonen und um Liquidationen in den Regimen aus V3.

**Regeln.** Keine Rückrechnung (OI je Strike und Liquidationen gibt es historisch nicht). Nur Stände mit belegter
Quell- und Empfangszeit (Paket C, E1/E2). Gamma-Größen sind `modelled` (Händler-Vorzeichen ist Annahme), Liquidationen
`observed`. Regel, Schwellen und Mindestzahl (z. B. 30 Ereignisse je Zelle, sonst kein Urteil) vor dem Start eingefroren;
zensierte Besuche zählen nicht. S41 läuft unabhängig weiter und wird nicht verändert.

**Abnahme.** Eingefrorene Präregistrierung, Startzeit nach Einfrieren, Zähler je Regime, Zeitgrenze mit Urteil
NICHT_BESTANDEN_ZEIT, kein Eingriff in laufende Regeln.

**Abhängigkeit.** C-PASS, E2 verdrahtet (eigenes GO), V3-Regime definiert.

### V5 – Fortgeschrittene Bewertung (experimentell, nur beschreibend; Ebene E-M)

**Inhalt.** Volatilitätsfläche, Skew, Term Structure, SABR und SVI, Arbitrageprüfungen.

**Regeln.** Arbitrageprüfungen auf Preisen: Monotonie und Konvexität im Strike (Butterfly ≥ 0), Kalender (Total-Varianz
nicht fallend in T), Put-Call-Parität innerhalb Bid/Ask. Nur gemessene Punkte, keine Extrapolation; fehlende Quote =
UNKNOWN. SABR (β fest) und SVI nur als Fit mit Fehlermaß und Stabilität über die Zeit. Kein Ergebnis wird als
Handelsnutzen formuliert; jede Hypothese daraus bräuchte eine eigene Präregistrierung.

**Abnahme.** Fit-Fehler in Vol-Punkten je Verfall, Anteil arbitragefreier Schnitte, Stabilitätsmaß, dokumentierte
Fehlschläge der Kalibrierung; Kennzeichnung "experimentell" in jeder Ausgabe.

## 3. Reihenfolge und Abhängigkeiten

V0 → V1 → V2 → V3; V4 nach C/E2 und Vorwärtsaufnahme; V5 zuletzt (nur V0 nötig, aber geringster Nutzen).
V0 kann als einziges Paket unabhängig von Mission 07 starten, sobald der Inhaber es freigibt.

## 4. Benötigte Entscheidungen

1. GO je Paket (einzeln), frühestens V0.
2. Bestätigungsdaten für V3: 2023–24 nur nach Berührungsregister, sonst neuer Vorwärtszeitraum (Dauer festlegen).
3. Zinskonvention: Forward aus Future/Parität als Standard (Vorschlag) statt Zins 0.
4. Ob die B2-Parser (#383) vor V1 korrigiert werden.
