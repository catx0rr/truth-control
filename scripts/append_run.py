#!/usr/bin/env python3
"""
truth-recovery: append_run — deterministic JSONL run record writer

Appends a single structured run record to the distiller telemetry log.
Produces the canonical timestamp triple (local-aware, UTC, timezone).
Supports daily-sharded telemetry output via --telemetry-dir.

Usage:
    python3 scripts/append_run.py --telemetry-dir <telemetry-root> --mode hourly --success
    python3 scripts/append_run.py --telemetry-dir <telemetry-root> --mode nightly-preconsolidation --success \
        --corrections-loaded 4 --corrections-unstaged 2 --corrections-staged 2 --would-stage 2
    python3 scripts/append_run.py --telemetry-dir <telemetry-root> --mode hourly --error "distill.py failed"
    python3 scripts/append_run.py --runs-file path/to/runs.jsonl --mode hourly --success  # explicit override

Telemetry root resolution:
    1. --runs-file
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


def _timestamp_triple() -> dict:
    """Generate the canonical timestamp triple."""
    now_local = datetime.now().astimezone()
    now_utc = now_local.astimezone(timezone.utc)

    tz_name = None
    try:
        if hasattr(now_local.tzinfo, 'key'):
            tz_name = now_local.tzinfo.key
        elif hasattr(now_local.tzinfo, 'zone'):
            tz_name = now_local.tzinfo.zone
        else:
            tz_name = now_local.tzname()
    except (AttributeError, TypeError):
        pass

    if not tz_name or len(tz_name) <= 5:
        offset = now_local.strftime('%z')
        tz_name = f'UTC{offset[:3]}:{offset[3:]}' if offset else 'UTC'

    return {
        'timestamp': now_local.isoformat(),
        'timestamp_utc': now_utc.isoformat().replace('+00:00', 'Z'),
        'timezone': tz_name,
    }


def _today_str() -> str:
    """Return today's date as YYYY-MM-DD in the host's local timezone."""
    return datetime.now().astimezone().strftime('%Y-%m-%d')


def resolve_telemetry_root(telemetry_dir: str = None) -> str:
    """Resolve the telemetry root with env + fallback support."""
    return (
        telemetry_dir
        or os.environ.get('TRUTH_CONTROL_TELEMETRY_ROOT')
        or os.environ.get('TRUTH_RECOVERY_TELEMETRY_ROOT')
        or os.path.expanduser('~/.openclaw/telemetry')
    )


def resolve_runs_file(telemetry_dir: str = None, runs_file: str = None) -> str:
    """Resolve the target JSONL file path.

    Priority:
        1. Explicit --runs-file override
        2. --telemetry-dir → daily-sharded path
        3. telemetry env vars → daily-sharded path
        4. default fallback root → daily-sharded path
    """
    if runs_file:
        return runs_file

    telemetry_root = resolve_telemetry_root(telemetry_dir)
    if telemetry_root:
        distiller_dir = os.path.join(telemetry_root, 'truth-recovery', 'distiller')
        os.makedirs(distiller_dir, exist_ok=True)
        return os.path.join(distiller_dir, f'distiller-runs-{_today_str()}.jsonl')

    return None


def append_run_record(target_file: str, mode: str, success: bool,
                      corrections_loaded: int = 0, corrections_unstaged: int = 0,
                      corrections_staged: int = 0, would_stage: int = 0,
                      error: str = None) -> dict:
    """Append a single run record to the JSONL file."""
    ts = _timestamp_triple()

    record = {
        'timestamp': ts['timestamp'],
        'timestamp_utc': ts['timestamp_utc'],
        'timezone': ts['timezone'],
        'mode': mode,
        'success': success,
        'corrections_loaded': corrections_loaded,
        'corrections_unstaged': corrections_unstaged,
        'corrections_staged': corrections_staged,
        'would_stage': would_stage,
        'error': error,
    }

    Path(target_file).parent.mkdir(parents=True, exist_ok=True)

    with open(target_file, 'a') as f:
        f.write(json.dumps(record, ensure_ascii=False) + '\n')

    return record


def main():
    parser = argparse.ArgumentParser(
        description='Truth Recovery: Deterministic JSONL Run Record Writer',
    )
    parser.add_argument('--telemetry-dir', default=None,
                        help='Telemetry root directory (overrides env vars; otherwise uses TRUTH_CONTROL_TELEMETRY_ROOT, then TRUTH_RECOVERY_TELEMETRY_ROOT, then ~/.openclaw/telemetry as a common local-host fallback)')
    parser.add_argument('--runs-file', default=None,
                        help='Explicit runs file path (overrides --telemetry-dir)')
    parser.add_argument('--mode', required=True, choices=['hourly', 'nightly-preconsolidation'],
                        help='Run mode')
    parser.add_argument('--success', action='store_true', default=False,
                        help='Mark run as successful')
    parser.add_argument('--corrections-loaded', type=int, default=0)
    parser.add_argument('--corrections-unstaged', type=int, default=0)
    parser.add_argument('--corrections-staged', type=int, default=0)
    parser.add_argument('--would-stage', type=int, default=0)
    parser.add_argument('--error', default=None, help='Error message if run failed')

    args = parser.parse_args()

    target_file = resolve_runs_file(args.telemetry_dir, args.runs_file)
    if not target_file:
        print(json.dumps({'error': 'Could not resolve runs file path'}, indent=2))
        return 1

    record = append_run_record(
        target_file,
        mode=args.mode,
        success=args.success and not args.error,
        corrections_loaded=args.corrections_loaded,
        corrections_unstaged=args.corrections_unstaged,
        corrections_staged=args.corrections_staged,
        would_stage=args.would_stage,
        error=args.error,
    )

    record['_target_file'] = target_file
    print(json.dumps(record, indent=2, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
