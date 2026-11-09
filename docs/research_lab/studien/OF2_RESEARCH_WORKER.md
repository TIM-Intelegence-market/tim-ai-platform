# OF2: Research-Worker auf der PS5

Stand 09.11.2026. Beschreibt, wie die PS5 mit Ubuntu als Rechner für die OF2-Studie eingerichtet ist und was bis zu
einem regulären Studienlauf fehlt. Die Regeln der Studie stehen in
[`OF2_ORDERFLOW_ENGINE_PRAEREGISTRIERUNG_ENTWURF.md`](OF2_ORDERFLOW_ENGINE_PRAEREGISTRIERUNG_ENTWURF.md) und gehen
diesem Dokument immer vor. Adressen, Hostkeys und Schlüssel gehören nicht in dieses Repo.

## Grenzen

- Nur Forschung auf Papier. Kein Live-Handel, keine Orders.
- Holdout ab 2025-01-01 bleibt gesperrt, der S8-Store verweigert diese Tage selbst.
- Kein regulärer Lauf auf Training oder Validierung vor Freigabe 1.0 und Uzis ausdrücklichem Wort.
- Die Präregistrierung nennt den Mac als Rechenort. Ein regulärer Lauf auf der PS5 braucht deshalb Uzis Zustimmung.
- Keine privaten Schlüssel auf der Konsole. Sie trägt nur öffentliche Schlüssel, Daten werden zu ihr hingeschoben.

## Aktueller Stand

| Bereich | Stand |
|---|---|
| Rechner | Ubuntu 26.04, 16 Kerne, 14 GB RAM, 7 GB zram, 1,8 TB USB-Platte |
| Netz | WLAN, gemessen rund 11 bis 12 MB/s. Die Ethernet-Buchse ist ohne Link |
| Code | Checkout auf Commit `102d767b` (`platform-main` vom 08.11.), nur M1 bis M3 |
| Tests | `tests/test_research_lab_of2.py` auf dem Worker am 09.11.: 27 von 27 bestanden |
| Daten | S8-Minutenbalken und Tagesprofile 2020-01-01 bis 2024-12-31, 1.827 Tage, 641 MB, aus den Binance-Tagesarchiven |
| Zugang | Über das Bastion-Gateway auf dem Server, eigene Rolle nur für das Konto ohne sudo |
| Betrieb | Kein Dienst. Die CLI wird von Hand in `screen` gestartet |

Am 09.11.2026 wurde ein **Vorlauf** nur auf dem Abschnitt Training gerechnet, auf Basis von Entwurf 0.2 und Commit
`102d767b`. Er ist kein gültiger Studienlauf nach Protokoll. Die Ergebnisse liegen nur auf dem Worker und sind
bewusst nicht in diesem Repo. Wer den regulären Lauf freigibt, muss wissen, dass der Trainingsabschnitt damit
bereits einmal gesehen wurde.

## Einrichtung nachbauen

Der OF2-Code und der S8-Datenaufbau kommen mit der Standardbibliothek aus. Zusatzpakete braucht nur `pytest`.

```bash
export ROOT="$HOME/research"
git clone https://github.com/TIM-Intelegence-market/tim-ai-platform.git "$ROOT/tim-of2"
cd "$ROOT/tim-of2"
python3 -m venv .venv
.venv/bin/python -m pip install pytest
```

Fehlt `ensurepip`, die Umgebung mit `--without-pip` anlegen und `pip.pyz` von PyPA benutzerlokal verwenden.

Die Tests laufen außerhalb des Ordners `tests/`, weil `tests/conftest.py` `asyncpg` lädt:

```bash
mkdir -p "$ROOT/of2-smoke"
cp tests/test_research_lab_of2.py "$ROOT/of2-smoke/"
cd "$ROOT/of2-smoke"
PYTHONPATH="$ROOT/tim-of2" "$ROOT/tim-of2/.venv/bin/python" -m pytest -q -p no:cacheprovider test_research_lab_of2.py
```

Datenaufbau, auf dem WLAN rund 7,5 Stunden:

```bash
cd "$ROOT/tim-of2"
screen -dmS of2-data bash -c ".venv/bin/python -m src.research_lab.orderflow_ml --root $ROOT/data/orderflow_ml fetch --from 2020-01-01 --to 2024-12-31 >> $ROOT/data/fetch.log 2>&1; echo EXIT \$? >> $ROOT/data/fetch.log"
```

Lauf, erst nach Abschluss des Datenaufbaus und nur innerhalb der Grenzen oben. Die CLI bricht ab, solange Tage
fehlen. Auf dem Worker dauerte `run` 45 Sekunden und `random` rund 2 Minuten.

```bash
.venv/bin/python -m src.research_lab.of2 run --bars "$ROOT/data/orderflow_ml" --section training --out training.json
.venv/bin/python -m src.research_lab.of2 random --bars "$ROOT/data/orderflow_ml" --section training --trades training.json --draws 1000 --out random_training.json
```

Die Validierung läuft erst, wenn das Training vollständig ausgewertet ist, und ohne Änderung an `Config` dazwischen.

## Bis zum regulären Lauf

Studie:

- [ ] P0 auf mehr als 40 Tagen wiederholen
- [ ] Footprint-Schwellen auf dem Trainingsabschnitt messen und einfrieren
- [ ] Präregistrierung auf 1.0 heben, mit Uzis Wort
- [ ] Uzi entscheidet, wie der Vorlauf vom 09.11. zu werten ist und ob der Lauf auf der PS5 stattfinden darf

Worker:

- [ ] Code auf den für 1.0 festgelegten Commit bringen, inklusive M4 bis M6, und den Commit vor dem Lauf festhalten
- [ ] Gemeinsamen Ablageordner für Uploads anlegen, das Upload-Konto und das Arbeitskonto können sich gegenseitig nicht lesen
- [ ] Zugang des Servers auf den Worker einrichten und testen
- [ ] Ersten echten Login und Upload mit Uzis eigenem Schlüssel bestätigen
- [ ] `rsync` nachinstallieren, falls Daten doch vom Mac kommen sollen
- [ ] Client-Schlüssel des Gateways tauschen

Lauf:

- [ ] Training regulär rechnen und vollständig auswerten
- [ ] Validierung rechnen
