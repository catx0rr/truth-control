#!/usr/bin/env python3
"""
truth-recovery: writeback mode — correction capture

Records a user correction to the recent corrections register.
Optionally marks old assumptions as stale. Provides list and prune modes.

All modes emit exactly one JSON object to stdout.

Usage:
    python3 writeback.py --old "incorrect value" --corrected "correct value" --scope "location"
    python3 writeback.py --old "meeting at 3 PM" --corrected "meeting at 4 PM" --scope "time" --context "Weekly sync"
    python3 writeback.py --list
    python3 writeback.py --prune
    python3 writeback.py --mark-consolidated "incorrect value"
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

DEFAULT_FILE = 'runtime/truth-recovery/recent-corrections.jsonl'
DEFAULT_MAX_AGE_DAYS = 30


def _local_now_iso() -> str:
    """Generate a timezone-aware local ISO 8601 timestamp with explicit offset.

    Uses the host's local timezone at runtime. Never produces naive timestamps.
    Falls back to UTC with explicit offset if local timezone cannot be determined.
    """
    return datetime.now().astimezone().isoformat()


def _timestamp_triple() -> dict:
    """Generate the canonical timestamp triple: local-aware, UTC companion, timezone name.

    Returns:
        {
            "timestamp": "2026-04-12T10:00:00+08:00",
            "timestamp_utc": "2026-04-12T02:00:00Z",
            "timezone": "Asia/Manila"
        }

    If IANA timezone name cannot be determined, falls back to offset label (e.g., "UTC+08:00").
    """
    now_local = datetime.now().astimezone()
    now_utc = now_local.astimezone(timezone.utc)

    # Resolve IANA timezone name
    tz_name = None
    try:
        tz_name = now_local.tzname()
        # Try to get the IANA name from the tzinfo object
        if hasattr(now_local.tzinfo, 'key'):
            tz_name = now_local.tzinfo.key
        elif hasattr(now_local.tzinfo, 'zone'):
            tz_name = now_local.tzinfo.zone
    except (AttributeError, TypeError):
        pass

    # Fallback: use offset label if no IANA name
    if not tz_name or len(tz_name) <= 5:
        offset = now_local.strftime('%z')
        if offset:
            tz_name = f'UTC{offset[:3]}:{offset[3:]}'
        else:
            tz_name = 'UTC'

    return {
        'timestamp': now_local.isoformat(),
        'timestamp_utc': now_utc.isoformat().replace('+00:00', 'Z'),
        'timezone': tz_name,
    }


def _parse_ts(ts: str) -> datetime:
    """Parse an ISO timestamp string to timezone-aware datetime.

    Accepts both Z-suffix and explicit offset formats.
    """
    return datetime.fromisoformat(ts.replace('Z', '+00:00'))


def ensure_runtime_dir(filepath: str):
    """Create runtime directory if it doesn't exist."""
    Path(filepath).parent.mkdir(parents=True, exist_ok=True)


def write_correction(filepath: str, old: str, corrected: str, scope: str,
                     source: str = 'user_correction', context: str = None) -> dict:
    """Append a correction entry to the JSONL file."""
    ensure_runtime_dir(filepath)

    ts = _timestamp_triple()

    entry = {
        'old': old,
        'corrected': corrected,
        'scope': scope,
        'source': source,
        'timestamp': ts['timestamp'],
        'timestamp_utc': ts['timestamp_utc'],
        'timezone': ts['timezone'],
        'consolidated': False,
        'consolidated_at': None,
        'staged': False,
        'staged_at': None,
    }

    if context:
        entry['context'] = context

    with open(filepath, 'a') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')

    return entry


def list_corrections(filepath: str, max_age_days: int = None) -> list:
    """Read and return all corrections, optionally filtered by age."""
    path = Path(filepath)
    if not path.exists():
        return []

    corrections = []
    cutoff = None
    if max_age_days is not None:
        cutoff = datetime.now(tz=timezone.utc) - timedelta(days=max_age_days)

    with open(path, 'r') as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                entry['_line'] = line_no

                if cutoff and entry.get('timestamp'):
                    entry_time = _parse_ts(entry['timestamp'])
                    if entry_time < cutoff:
                        continue

                corrections.append(entry)
            except (json.JSONDecodeError, ValueError):
                continue

    return corrections


def prune_corrections(filepath: str, max_age_days: int = DEFAULT_MAX_AGE_DAYS) -> dict:
    """Remove expired AND consolidated corrections. Returns stats."""
    path = Path(filepath)
    if not path.exists():
        return {'removed': 0, 'kept': 0}

    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=max_age_days)
    kept = []
    removed = 0

    with open(path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                ts = entry.get('timestamp', '')
                consolidated = entry.get('consolidated', False)

                if ts:
                    entry_time = _parse_ts(ts)
                    # Remove if: expired AND consolidated
                    if entry_time < cutoff and consolidated:
                        removed += 1
                        continue

                kept.append(line)
            except (json.JSONDecodeError, ValueError):
                kept.append(line)  # preserve malformed lines

    # Rewrite file with kept entries only
    with open(path, 'w') as f:
        for line in kept:
            f.write(line + '\n')

    return {'removed': removed, 'kept': len(kept)}


def mark_consolidated(filepath: str, old_value: str) -> bool:
    """Mark a correction as consolidated (picked up by the host consolidator)."""
    path = Path(filepath)
    if not path.exists():
        return False

    lines = []
    found = False

    with open(path, 'r') as f:
        for line in f:
            stripped = line.strip()
            if not stripped:
                lines.append(line)
                continue
            try:
                entry = json.loads(stripped)
                if entry.get('old', '').lower() == old_value.lower() and not entry.get('consolidated'):
                    ts = _timestamp_triple()
                    entry['consolidated'] = True
                    entry['consolidated_at'] = ts['timestamp']
                    entry['consolidated_at_utc'] = ts['timestamp_utc']
                    found = True
                lines.append(json.dumps(entry, ensure_ascii=False) + '\n')
            except (json.JSONDecodeError, ValueError):
                lines.append(line)

    if found:
        with open(path, 'w') as f:
            f.writelines(lines)

    return found


def main():
    parser = argparse.ArgumentParser(description='Truth Recovery: Writeback Mode — Correction Capture')

    # Writeback mode
    parser.add_argument('--old', help='The old/incorrect assumption')
    parser.add_argument('--corrected', help='The corrected value from the user')
    parser.add_argument('--scope', help='Scope of the correction (location, time, person, event, decision, etc.)')
    parser.add_argument('--source', default='user_correction',
                        help='Source of the correction (default: user_correction)')
    parser.add_argument('--context', help='Optional context for the correction')

    # List mode
    parser.add_argument('--list', action='store_true', help='List recent corrections')

    # Prune mode
    parser.add_argument('--prune', action='store_true', help='Remove expired+consolidated corrections')

    # Mark consolidated
    parser.add_argument('--mark-consolidated', metavar='OLD_VALUE',
                        help='Mark a correction as consolidated')

    # Common
    parser.add_argument('--file', default=DEFAULT_FILE, help='Path to corrections JSONL file')
    parser.add_argument('--max-age-days', type=int, default=DEFAULT_MAX_AGE_DAYS,
                        help='Max age for listing/pruning')

    args = parser.parse_args()

    if args.list:
        corrections = list_corrections(args.file, args.max_age_days)
        result = {
            'corrections': corrections,
            'count': len(corrections),
            'max_age_days': args.max_age_days,
            'file': args.file,
        }
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    if args.prune:
        stats = prune_corrections(args.file, args.max_age_days)
        print(json.dumps(stats, indent=2))
        return 0

    if args.mark_consolidated:
        found = mark_consolidated(args.file, args.mark_consolidated)
        result = {
            'action': 'mark_consolidated',
            'old_value': args.mark_consolidated,
            'found': found,
        }
        print(json.dumps(result, indent=2))
        return 0 if found else 1

    # Writeback mode
    if not args.old or not args.corrected:
        parser.error('--old and --corrected are required for writeback')

    if not args.scope:
        parser.error('--scope is required for writeback')

    entry = write_correction(args.file, args.old, args.corrected, args.scope,
                             args.source, args.context)

    print(json.dumps({
        'action': 'correction_recorded',
        'entry': entry,
        'file': args.file,
    }, indent=2, ensure_ascii=False))

    return 0


if __name__ == '__main__':
    sys.exit(main())
