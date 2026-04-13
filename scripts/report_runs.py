#!/usr/bin/env python3
"""
truth-recovery: report_runs — distiller report generator

Reads distiller run logs from telemetry, generates nightly or hourly
reports using explicit templates. Uses parsed timezone-aware datetime
comparison for correct cross-timezone ordering.

Supports daily-sharded telemetry via --telemetry-dir, telemetry-root env vars, or explicit
--runs-file for backward compatibility.

Usage:
    python3 scripts/report_runs.py --telemetry-dir <telemetry-root> --mode nightly
    python3 scripts/report_runs.py --telemetry-dir <telemetry-root> --mode hourly
    python3 scripts/report_runs.py --telemetry-dir <telemetry-root> --mode nightly --dry-run
    python3 scripts/report_runs.py --runs-file path/to/runs.jsonl --mode nightly --report-file path/to/report.md

Telemetry root resolution:
    1. --runs-file / --report-file
    2. --telemetry-dir
    3. TRUTH_CONTROL_TELEMETRY_ROOT
    4. TRUTH_RECOVERY_TELEMETRY_ROOT
    5. ~/.openclaw/telemetry  (common local-host fallback example)
"""

import argparse
import glob
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# Timestamp parsing
# ---------------------------------------------------------------------------

def _parse_ts(ts: str) -> datetime:
    """Parse an ISO timestamp string to timezone-aware datetime.

    Accepts both Z-suffix and explicit offset formats.
    Returns None if parsing fails.
    """
    if not ts or not isinstance(ts, str):
        return None
    try:
        return datetime.fromisoformat(ts.replace('Z', '+00:00'))
    except (ValueError, AttributeError):
        return None


def _local_now_iso() -> str:
    """Generate a timezone-aware local ISO 8601 timestamp with explicit offset."""
    return datetime.now().astimezone().isoformat()


# ---------------------------------------------------------------------------
# Run loading
# ---------------------------------------------------------------------------

def resolve_telemetry_root(telemetry_dir: str = None) -> str:
    """Resolve the telemetry root with env + fallback support."""
    return (
        telemetry_dir
        or os.environ.get('TRUTH_CONTROL_TELEMETRY_ROOT')
        or os.environ.get('TRUTH_RECOVERY_TELEMETRY_ROOT')
        or os.path.expanduser('~/.openclaw/telemetry')
    )


def load_runs_from_telemetry(telemetry_dir: str) -> list:
    """Load all run records from daily-sharded telemetry files.

    Scans <telemetry-dir>/truth-recovery/distiller/distiller-runs-*.jsonl,
    merges all entries, and sorts by parsed timestamp ascending.
    """
    telemetry_root = resolve_telemetry_root(telemetry_dir)
    distiller_dir = os.path.join(telemetry_root, 'truth-recovery', 'distiller')
    pattern = os.path.join(distiller_dir, 'distiller-runs-*.jsonl')
    files = sorted(glob.glob(pattern))

    runs = []
    for filepath in files:
        with open(filepath, 'r') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    entry['_parsed_ts'] = _parse_ts(entry.get('timestamp', ''))
                    runs.append(entry)
                except (json.JSONDecodeError, ValueError):
                    continue

    # Sort by parsed timestamp — entries with unparseable timestamps go last
    runs.sort(key=lambda r: r['_parsed_ts'] or datetime.max.replace(tzinfo=timezone.utc))
    return runs


def load_runs_from_file(runs_file: str) -> list:
    """Load all run records from a single JSONL file (backward compat).

    Sorts by parsed timestamp ascending.
    """
    path = Path(runs_file)
    if not path.exists():
        return []

    runs = []
    with open(path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                entry['_parsed_ts'] = _parse_ts(entry.get('timestamp', ''))
                runs.append(entry)
            except (json.JSONDecodeError, ValueError):
                continue

    runs.sort(key=lambda r: r['_parsed_ts'] or datetime.max.replace(tzinfo=timezone.utc))
    return runs


def resolve_report_file(telemetry_dir: str = None, report_file: str = None) -> str:
    """Resolve report output path."""
    if report_file:
        return report_file

    telemetry_root = resolve_telemetry_root(telemetry_dir)
    if telemetry_root:
        report_dir = os.path.join(telemetry_root, 'truth-recovery', 'latest-report')
        os.makedirs(report_dir, exist_ok=True)
        return os.path.join(report_dir, 'nightly-distill-report.md')

    return None


# ---------------------------------------------------------------------------
# Run selection helpers (parsed datetime comparison)
# ---------------------------------------------------------------------------

def get_latest_nightly(runs: list) -> dict:
    """Get the latest nightly run record by parsed timestamp."""
    nightly_runs = [r for r in runs if r.get('mode') == 'nightly-preconsolidation' and r.get('_parsed_ts')]
    return nightly_runs[-1] if nightly_runs else None


def find_previous_nightly(runs: list) -> dict:
    """Find the second-to-last nightly run (the one before the current nightly)."""
    nightly_runs = [r for r in runs if r.get('mode') == 'nightly-preconsolidation' and r.get('_parsed_ts')]
    return nightly_runs[-2] if len(nightly_runs) >= 2 else None


def get_latest_hourly(runs: list) -> dict:
    """Get the latest hourly run record by parsed timestamp."""
    hourly_runs = [r for r in runs if r.get('mode') == 'hourly' and r.get('_parsed_ts')]
    return hourly_runs[-1] if hourly_runs else None


def count_hourly_since(runs: list, since_dt: datetime) -> dict:
    """Count hourly runs since a given parsed datetime."""
    fired = 0
    success = 0
    failed = 0

    for run in runs:
        if run.get('mode') != 'hourly':
            continue
        parsed = run.get('_parsed_ts')
        if not parsed:
            continue
        if parsed > since_dt:
            fired += 1
            if run.get('success'):
                success += 1
            else:
                failed += 1

    return {'fired': fired, 'success': success, 'failed': failed}


# ---------------------------------------------------------------------------
# Report templates
# ---------------------------------------------------------------------------

def _format_time_block(run: dict) -> list:
    """Format the time display lines from a run record."""
    ts = run.get('timestamp', 'unknown')
    ts_utc = run.get('timestamp_utc', 'unknown')
    tz = run.get('timezone', 'unknown')
    return [
        f'Local Time: {ts}',
        f'UTC Time: {ts_utc}',
        f'Timezone: {tz}',
    ]


def generate_nightly_report(runs: list) -> str:
    """Generate the full nightly report using the exact nightly template."""
    latest = get_latest_nightly(runs)
    if not latest:
        latest = {
            'success': False,
            'timestamp': 'unknown',
            'timestamp_utc': 'unknown',
            'timezone': 'unknown',
            'corrections_loaded': 0,
            'error': 'No nightly run records found',
        }

    prev = find_previous_nightly(runs)
    if prev and prev.get('_parsed_ts'):
        hourly_stats = count_hourly_since(runs, prev['_parsed_ts'])
    else:
        hourly_stats = {'fired': 0, 'success': 0, 'failed': 0}

    success = latest.get('success', False)
    loaded = latest.get('corrections_loaded', 0)
    unstaged = latest.get('corrections_unstaged', 0)
    staged = latest.get('corrections_staged', 0)
    error = latest.get('error') or 'unknown'

    lines = [
        '⌛ Truth-Recovery Distiller — Nightly Pre-Consolidation',
        '',
        f'Nightly run: {"SUCCESS" if success else "FAILED"}',
    ]
    lines.extend(_format_time_block(latest))
    lines.append('')
    lines.extend([
        'Hourly sweeps since last nightly run:',
        f'- Fired: {hourly_stats["fired"]}',
        f'- Success: {hourly_stats["success"]}',
        f'- Failed: {hourly_stats["failed"]}',
        '',
        'Nightly staging result:',
    ])

    if success:
        lines.extend([
            f'- Corrections loaded: {loaded}',
            f'- Unstaged before run: {unstaged}',
            f'- Staged tonight: {staged}',
            '',
            'Status:',
            '- Distiller bridge ran before consolidation',
        ])
        if staged == 0:
            lines.append('- Nothing needed staging')
        else:
            lines.append(f'- Staged {staged} correction(s) for later consolidation')
    else:
        lines.extend([
            '- Corrections loaded: 0',
            '- Unstaged before run: unknown',
            '- Staged tonight: 0',
            '',
            'Status:',
            '- Nightly distiller failed before consolidation',
            f'- Last error: {error}',
        ])

    return '\n'.join(lines) + '\n'


def generate_hourly_report(runs: list) -> str:
    """Generate the short hourly report using the exact hourly template."""
    latest = get_latest_hourly(runs)
    if not latest:
        latest = {
            'success': False,
            'timestamp': 'unknown',
            'timestamp_utc': 'unknown',
            'timezone': 'unknown',
        }

    status = 'SUCCESS' if latest.get('success', False) else 'FAILED'
    lines = [
        '⏳ Truth-Recovery Distiller — Hourly Consolidation',
        '',
        f'Hourly run: {status}',
    ]
    lines.extend(_format_time_block(latest))
    return '\n'.join(lines) + '\n'


# ---------------------------------------------------------------------------
# File writer
# ---------------------------------------------------------------------------

def write_report(report_file: str, content: str, dry_run: bool = False) -> None:
    """Write the report to file."""
    if dry_run:
        return

    Path(report_file).parent.mkdir(parents=True, exist_ok=True)
    with open(report_file, 'w') as f:
        f.write(content)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='Truth Recovery: Distiller Report Generator',
    )
    parser.add_argument('--telemetry-dir', default=None,
                        help='Telemetry root directory (scans daily-sharded run files)')
    parser.add_argument('--runs-file', default=None,
                        help='Explicit single runs file (backward compat, overrides --telemetry-dir)')
    parser.add_argument('--report-file', default=None,
                        help='Explicit report output file (overrides --telemetry-dir default)')
    parser.add_argument('--mode', required=True, choices=['nightly', 'hourly'],
                        help='Report mode: nightly (full) or hourly (short)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Print report to stdout without writing file')
    args = parser.parse_args()

    # Load runs
    if args.runs_file:
        runs = load_runs_from_file(args.runs_file)
    elif args.telemetry_dir:
        runs = load_runs_from_telemetry(args.telemetry_dir)
    else:
        print(json.dumps({'error': 'Either --telemetry-dir or --runs-file is required'}, indent=2))
        return 1

    # Resolve report path
    report_file = resolve_report_file(args.telemetry_dir, args.report_file)

    # Generate report based on mode
    if args.mode == 'nightly':
        report = generate_nightly_report(runs)
    else:
        report = generate_hourly_report(runs)

    if args.dry_run:
        print(report, end='')
        return 0

    if report_file:
        write_report(report_file, report)

    result = {
        'runs_loaded': len(runs),
        'mode': args.mode,
        'report_file': report_file,
        'dry_run': args.dry_run,
    }
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
