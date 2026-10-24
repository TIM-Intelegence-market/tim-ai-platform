"""Zusatzstudie S-K aus der täglichen Backup-Datei rechnen, nur lesend.

Liest die Tabellen mit ``pg_restore -a -t <tabelle> -f -`` direkt aus der
Backup-Datei. Keine Datenbankverbindung, keine Zugangsdaten, nichts wird
wiederhergestellt; ~/TIM-live bleibt unberührt.

    # einmal vor T0: Terzilgrenzen kalibrieren und einfrieren
    python scripts/sk_study.py calibrate --dump BACKUP.dump --out artifacts/v2_completion/sk_regime_thresholds.json

    # danach, z. B. wöchentlich: Zwischenstand ohne Ergebnisse
    python scripts/sk_study.py status --dump BACKUP.dump --t0 2026-10-23T08:00:00Z

Die Backup-Datei stammt aus PostgreSQL 18; auf dem Mac liegt das passende
pg_restore unter /Library/PostgreSQL/18/bin/pg_restore.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.v2_completion import control_regime_study as sk  # noqa: E402
from src.v2_completion import sk_report  # noqa: E402
from src.v2_completion.independent_cases import UTC  # noqa: E402

DEFAULT_PG_RESTORE = "/Library/PostgreSQL/18/bin/pg_restore"
THRESHOLDS_PATH = Path("artifacts/v2_completion/sk_regime_thresholds.json")


def table_lines(pg_restore: str, dump: Path, table: str) -> Iterator[str]:
    command = [pg_restore, "-a", "-n", "public", "-t", table, "-f", "-", str(dump)]
    with subprocess.Popen(command, stdout=subprocess.PIPE, text=True, encoding="utf-8") as process:
        assert process.stdout is not None
        yield from process.stdout
    if process.returncode:
        raise SystemExit(f"pg_restore failed for {table} (exit {process.returncode})")


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise SystemExit("times need a timezone, e.g. 2026-10-23T08:00:00Z")
    return parsed.astimezone(UTC)


def calibrate(args: argparse.Namespace) -> None:
    spec = sk.load_spec()
    bars = sk_report.minute_bars(table_lines(args.pg_restore, args.dump, "candles"))
    payload = sk.calibrate_thresholds(bars, spec)
    out = Path(args.out)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    print(f"source backup: {args.dump.name}", file=sys.stderr)


def status(args: argparse.Namespace) -> None:
    spec = sk.load_spec()
    thresholds = json.loads(Path(args.thresholds).read_text(encoding="utf-8"))
    bars = sk_report.minute_bars(table_lines(args.pg_restore, args.dump, "candles"))
    triggers = sk_report.trigger_minutes_by_kind(table_lines(args.pg_restore, args.dump, "orderflow_observations"))
    if args.end:
        end = _parse_time(args.end)
    else:
        end = max(bar.open_time for bar in bars).astimezone(UTC) + timedelta(minutes=1)
    result = sk_report.study_status(
        triggers_by_kind=triggers, bars=bars, thresholds=thresholds, t0=_parse_time(args.t0), study_end=end, spec=spec,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pg-restore", default=DEFAULT_PG_RESTORE)
    sub = parser.add_subparsers(dest="command", required=True)
    cal = sub.add_parser("calibrate")
    cal.add_argument("--dump", type=Path, required=True)
    cal.add_argument("--out", default=str(THRESHOLDS_PATH))
    cal.set_defaults(run=calibrate)
    st = sub.add_parser("status")
    st.add_argument("--dump", type=Path, required=True)
    st.add_argument("--t0", required=True)
    st.add_argument("--end")
    st.add_argument("--thresholds", default=str(THRESHOLDS_PATH))
    st.set_defaults(run=status)
    args = parser.parse_args()
    args.run(args)


if __name__ == "__main__":
    main()
