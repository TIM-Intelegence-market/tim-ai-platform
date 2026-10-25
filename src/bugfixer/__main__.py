"""Explicit-path, observation-only CLI. No TIM runtime or credential bootstrap."""
import argparse
import json
from pathlib import Path
import signal
import sqlite3
import threading

from src.bugfixer.processing import Event, classify
from src.bugfixer.remediation import dry_run, load_registry
from src.bugfixer.replay import replay
from src.bugfixer.safety import Policy
from src.bugfixer.rotation import RotationSeal
from src.bugfixer.seal import create_seal, write_seal
from src.bugfixer.evidence import export_bundle, load_bundle
from src.bugfixer.reproduction import reproduce_known_case
from src.bugfixer.store import IncidentStore
from src.bugfixer.worker import ErrorLogWorker, ObservationBlocked


def main(argv=None):
    parser = argparse.ArgumentParser(description='TIM Bugfixer — OBSERVE only')
    parser.add_argument('--store', type=Path, required=True)
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('status', 'report', 'verify'):
        sub.add_parser(name)
    listing = sub.add_parser('list')
    listing.add_argument('--limit', type=int, default=100)
    for name in ('inspect', 'classify', 'reproduce', 'remediation-dry-run'):
        command = sub.add_parser(name)
        command.add_argument('incident_id')
        if name == 'reproduce':
            command.add_argument('--cutoff', required=True)
        if name == 'remediation-dry-run':
            command.add_argument('--registry', required=True, type=Path)
    known = sub.add_parser('reproduce-known')
    known.add_argument('case_id')
    exporting = sub.add_parser('export-evidence')
    exporting.add_argument('incident_id')
    exporting.add_argument('--directory', required=True, type=Path)
    evidence = sub.add_parser('replay-evidence')
    evidence.add_argument('--bundle', required=True, type=Path)
    evidence.add_argument('--cutoff', required=True)
    rotation = sub.add_parser('reconcile-rotation')
    rotation.add_argument('--source', type=Path, required=True)
    rotation.add_argument('--rotated-source', type=Path, required=True)
    rotation.add_argument('--seal', type=Path, required=True)
    sealing = sub.add_parser('seal-rotation', help='producer side: seal a closed, renamed log segment')
    sealing.add_argument('--rotated-source', type=Path, required=True)
    sealing.add_argument('--successor', type=Path, required=True)
    sealing.add_argument('--generation', type=int, required=True)
    sealing.add_argument('--out', type=Path, required=True)
    sealing.add_argument('--attest-writer-closed', action='store_true')
    sealing.add_argument('--attest-contiguous-successor', action='store_true')
    observing = sub.add_parser('observe')
    observing.add_argument('--source', type=Path, required=True)
    observing.add_argument('--follow', action='store_true')
    args = parser.parse_args(argv)
    store = None
    try:
        Policy().verify()
        if args.command == 'seal-rotation':
            # Producer side: measures files only, never opens the incident store.
            seal = create_seal(args.rotated_source, args.successor, args.generation,
                               writer_closed=args.attest_writer_closed,
                               contiguous_successor=args.attest_contiguous_successor)
            write_seal(seal, args.out)
            print(json.dumps({'sealed': True, 'generation': seal.generation, 'size': seal.size,
                              'sha256': seal.sha256}, sort_keys=True, indent=2))
            return 0
        if args.command != 'observe' and not args.store.is_file():
            raise ValueError('store does not exist')
        store = IncidentStore(args.store)
        if args.command == 'reproduce-known':
            result = reproduce_known_case(args.case_id)
        elif args.command == 'export-evidence':
            target = export_bundle(store, args.incident_id, args.directory)
            result = {'bundle_name': target.name, 'scope': 'sanitized_event_processing_only'}
        elif args.command == 'replay-evidence':
            result = replay([load_bundle(args.bundle)], cutoff=args.cutoff)
        elif args.command == 'reconcile-rotation':
            if args.seal.stat().st_size > 4096:
                raise ValueError('rotation seal exceeds size limit')
            seal = RotationSeal.from_dict(json.loads(args.seal.read_text()))
            result = ErrorLogWorker(store, args.source).reconcile_rotation(args.rotated_source, seal)
        elif args.command == 'observe':
            worker = ErrorLogWorker(store, args.source)
            if args.follow:
                stop = threading.Event()
                for sig in (signal.SIGTERM, signal.SIGINT):
                    signal.signal(sig, lambda *_: stop.set())
                worker.run(stop)
                result = {'stopped': True}
            else:
                result = worker.poll()
        elif args.command in {'status', 'report'}:
            result = store.status()
        elif args.command == 'list':
            result = store.list(args.limit)
        elif args.command == 'verify':
            result = {'policy': Policy().verify(),
                      'observer_store_integrity': store.db.execute('PRAGMA integrity_check').fetchone()[0],
                      'runtime_gates_verified': False}
        else:
            incident = store.inspect(args.incident_id)
            event = Event(**json.loads(incident['evidence']))
            if args.command == 'inspect':
                result = incident
            elif args.command == 'classify':
                result = vars(classify(event))
            elif args.command == 'reproduce':
                result = replay([event], cutoff=args.cutoff)
            else:
                result = dry_run(event, load_registry(args.registry))
        print(json.dumps(result, sort_keys=True, indent=2))
        return 0
    except (OSError, ValueError, KeyError, sqlite3.Error, ObservationBlocked):
        # Never echo untrusted log lines, paths or database parameters in errors.
        print(json.dumps({'status': 'BLOCKED', 'reason': 'Input, store or policy validation failed; inspect source and checkpoint locally'}))
        return 2
    finally:
        if store:
            store.close()


if __name__ == '__main__':
    raise SystemExit(main())
