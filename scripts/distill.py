#!/usr/bin/env python3
"""
truth-recovery: distill — runtime-to-memory staging bridge

Reads unstaged corrections from runtime/truth-recovery/recent-corrections.jsonl,
normalizes and deduplicates them, appends distilled correction notes
into the daily memory file (memory/YYYY-MM-DD.md), and optionally
mirrors them to a monthly audit file (memory/corrections/YYYY-MM.md).

This is a stager, not a consolidator. It marks entries as staged,
never as consolidated. Durable promotion remains the responsibility
of the host's consolidation cycle.

Usage:
    python3 scripts/distill.py
    python3 scripts/distill.py --corrections-file runtime/truth-recovery/recent-corrections.jsonl
    python3 scripts/distill.py --memory-dir memory
    python3 scripts/distill.py --audit-dir memory/corrections
    python3 scripts/distill.py --dry-run
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_CORRECTIONS = 'runtime/truth-recovery/recent-corrections.jsonl'
DEFAULT_MEMORY_DIR = 'memory'
DAILY_LOG_HEADING = '## Truth Recovery Corrections'


def _local_now_iso() -> str:
    """Generate a timezone-aware local ISO 8601 timestamp with explicit offset."""
    return datetime.now().astimezone().isoformat()


def _timestamp_triple() -> dict:
    """Generate the canonical timestamp triple: local-aware, UTC companion, timezone name.

    Returns dict with timestamp, timestamp_utc, timezone.
    """
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


def _month_str() -> str:
    """Return current month as YYYY-MM in the host's local timezone."""
    return datetime.now().astimezone().strftime('%Y-%m')


# ---------------------------------------------------------------------------
# 1. Load unstaged corrections
# ---------------------------------------------------------------------------

def load_unstaged_corrections(filepath: str) -> list:
    """Load correction entries where staged != true.

    Ignores malformed and blank lines.
    """
    path = Path(filepath)
    if not path.exists():
        return []

    corrections = []
    with open(path, 'r') as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if entry.get('staged') is True:
                    continue
                entry['_line'] = line_no
                corrections.append(entry)
            except (json.JSONDecodeError, ValueError):
                continue

    return corrections


# ---------------------------------------------------------------------------
# 2. Deduplicate corrections
# ---------------------------------------------------------------------------

def dedupe_corrections(corrections: list) -> list:
    """Deduplicate corrections by (old, corrected, scope) key.

    Keeps the most recent entry per key (last in list wins).
    """
    seen = {}
    for entry in corrections:
        key = (
            entry.get('old', '').strip().lower(),
            entry.get('corrected', '').strip().lower(),
            entry.get('scope', '').strip().lower(),
        )
        seen[key] = entry  # last wins

    return list(seen.values())


# ---------------------------------------------------------------------------
# 3. Format correction note
# ---------------------------------------------------------------------------

def format_correction_note(correction: dict) -> str:
    """Transform raw correction JSON into a compact distilled memory note."""
    old = correction.get('old', '?')
    corrected = correction.get('corrected', '?')
    scope = correction.get('scope', 'other')
    source = correction.get('source', 'unknown')
    ts = correction.get('timestamp', '')

    note = f'- Correction noted: "{old}" -> "{corrected}" (scope: {scope}; source: {source}'
    if ts:
        note += f'; recorded: {ts}'
    note += ')'

    return note


# ---------------------------------------------------------------------------
# 4. Append to daily log
# ---------------------------------------------------------------------------

def append_to_daily_log(memory_dir: str, notes: list, dry_run: bool = False) -> tuple:
    """Append correction notes to today's daily memory file.

    Creates the file and heading if they don't exist.
    Appends under the existing heading if it already exists.
    Does not create duplicate headings or duplicate notes in one file.

    Returns (path_to_daily_log, count_of_notes_written, list_of_new_notes).
    """
    os.makedirs(memory_dir, exist_ok=True)
    daily_file = os.path.join(memory_dir, f'{_today_str()}.md')

    if dry_run:
        return daily_file, len(notes), notes

    # Read existing content
    existing = ''
    if os.path.exists(daily_file):
        with open(daily_file, 'r') as f:
            existing = f.read()

    # Cross-run dedupe: skip notes whose correction key (old→corrected) already exists
    # Extract the "old" -> "corrected" signature from each note to match regardless of timestamp
    def _correction_key(note: str) -> str:
        """Extract 'old -> corrected (scope)' from a note for dedupe comparison."""
        # Note format: - Correction noted: "old" -> "corrected" (scope: ...; ...)
        import re
        m = re.search(r'"(.+?)"\s*->\s*"(.+?)"\s*\(scope:\s*(\w+)', note)
        return f'{m.group(1)}|{m.group(2)}|{m.group(3)}' if m else note

    existing_keys = {_correction_key(line) for line in existing.split('\n') if line.strip().startswith('- Correction noted:')}
    new_notes = [n for n in notes if _correction_key(n) not in existing_keys]
    if not new_notes:
        return daily_file, 0, []

    notes_block = '\n'.join(new_notes)

    if DAILY_LOG_HEADING in existing:
        # Find the heading and append notes after the last line under it
        lines = existing.split('\n')
        insert_idx = None
        for i, line in enumerate(lines):
            if line.strip() == DAILY_LOG_HEADING:
                # Find the end of this section (next heading or end of file)
                insert_idx = i + 1
                while insert_idx < len(lines):
                    next_line = lines[insert_idx]
                    if next_line.startswith('## ') and next_line.strip() != DAILY_LOG_HEADING:
                        break
                    if next_line.strip():
                        insert_idx += 1
                    else:
                        # Skip blank lines within the section
                        insert_idx += 1
                break

        if insert_idx is not None:
            # Insert before the next section or at end
            lines.insert(insert_idx, notes_block)
            with open(daily_file, 'w') as f:
                f.write('\n'.join(lines))
        else:
            # Heading found but couldn't locate insert point — append at end
            with open(daily_file, 'a') as f:
                f.write(f'\n{notes_block}\n')
    else:
        # No heading yet — append heading + notes
        with open(daily_file, 'a') as f:
            if existing and not existing.endswith('\n'):
                f.write('\n')
            if existing:
                f.write('\n')
            f.write(f'{DAILY_LOG_HEADING}\n\n{notes_block}\n')

    return daily_file, len(new_notes), new_notes


# ---------------------------------------------------------------------------
# 5. Mirror to audit (optional)
# ---------------------------------------------------------------------------

def mirror_to_audit(audit_dir: str, notes: list, dry_run: bool = False) -> str:
    """Append correction notes to the monthly audit file.

    Returns the path to the audit file, or None if audit_dir is not provided.
    """
    if not audit_dir:
        return None

    if dry_run:
        return os.path.join(audit_dir, f'{_month_str()}.md')

    os.makedirs(audit_dir, exist_ok=True)
    audit_file = os.path.join(audit_dir, f'{_month_str()}.md')

    notes_block = '\n'.join(notes)

    with open(audit_file, 'a') as f:
        f.write(f'\n### {_today_str()}\n\n{notes_block}\n')

    return audit_file


# ---------------------------------------------------------------------------
# 6. Mark staged
# ---------------------------------------------------------------------------

def _dedupe_key(entry: dict) -> tuple:
    """Compute the dedupe key for a correction entry."""
    return (
        entry.get('old', '').strip().lower(),
        entry.get('corrected', '').strip().lower(),
        entry.get('scope', '').strip().lower(),
    )


def mark_staged(corrections_file: str, staged_entries: list, all_unstaged: list) -> None:
    """Rewrite the corrections JSONL so staged entries and their duplicates get staged=true.

    When deduped corrections collapse multiple runtime entries into one staged note,
    ALL entries sharing the same dedupe key are marked staged — not just the winner.
    This prevents stale unstaged residue from accumulating.

    Does not touch consolidated or consolidated_at.
    """
    # Build the set of dedupe keys that were staged
    staged_keys = {_dedupe_key(e) for e in staged_entries}

    # Collect ALL line numbers whose dedupe key was staged (winners + duplicates)
    lines_to_stage = set()
    for entry in all_unstaged:
        if _dedupe_key(entry) in staged_keys:
            lines_to_stage.add(entry['_line'])

    ts = _timestamp_triple()

    path = Path(corrections_file)
    if not path.exists():
        return

    new_lines = []
    with open(path, 'r') as f:
        for line_no, line in enumerate(f, 1):
            stripped = line.strip()
            if not stripped:
                new_lines.append(line)
                continue

            if line_no in lines_to_stage:
                try:
                    entry = json.loads(stripped)
                    entry['staged'] = True
                    entry['staged_at'] = ts['timestamp']
                    entry['staged_at_utc'] = ts['timestamp_utc']
                    new_lines.append(json.dumps(entry, ensure_ascii=False) + '\n')
                except (json.JSONDecodeError, ValueError):
                    new_lines.append(line)
            else:
                new_lines.append(line if line.endswith('\n') else line + '\n')

    with open(path, 'w') as f:
        f.writelines(new_lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='Truth Recovery: Distiller Bridge — Runtime-to-Memory Staging',
    )
    parser.add_argument('--corrections-file', default=DEFAULT_CORRECTIONS,
                        help='Path to corrections JSONL file')
    parser.add_argument('--memory-dir', default=DEFAULT_MEMORY_DIR,
                        help='Directory for daily memory logs')
    parser.add_argument('--audit-dir', default=None,
                        help='Directory for monthly audit mirror (optional)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would be staged without writing')
    parser.add_argument('--max-age-days', type=int, default=None,
                        help='Only stage corrections newer than N days (optional)')
    parser.add_argument('--limit', type=int, default=None,
                        help='Maximum number of corrections to stage (optional)')
    args = parser.parse_args()

    # Load unstaged
    all_unstaged = load_unstaged_corrections(args.corrections_file)
    total_loaded = _count_all_entries(args.corrections_file)

    # Optional age filter
    if args.max_age_days is not None:
        from datetime import timedelta
        cutoff = datetime.now().astimezone() - timedelta(days=args.max_age_days)
        filtered = []
        for entry in all_unstaged:
            ts = entry.get('timestamp', '')
            if ts:
                try:
                    entry_time = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                    if entry_time < cutoff:
                        continue
                except (ValueError, AttributeError):
                    pass
            filtered.append(entry)
        all_unstaged = filtered

    # Dedupe
    deduped = dedupe_corrections(all_unstaged)

    # Optional limit
    if args.limit is not None:
        deduped = deduped[:args.limit]

    # Format notes
    notes = [format_correction_note(c) for c in deduped]

    # Stage
    daily_log_file = None
    audit_file = None
    notes_written = 0

    if notes:
        daily_log_file, notes_written, new_notes = append_to_daily_log(args.memory_dir, notes, dry_run=args.dry_run)

        # Only mirror notes that were actually newly appended to the daily log
        if notes_written > 0:
            audit_file = mirror_to_audit(args.audit_dir, new_notes, dry_run=args.dry_run)

        if not args.dry_run and notes_written > 0:
            mark_staged(args.corrections_file, deduped, all_unstaged)

    result = {
        'corrections_loaded': total_loaded,
        'corrections_unstaged': len(all_unstaged),
        'corrections_deduped': len(deduped),
        'corrections_staged': notes_written if not args.dry_run else 0,
        'would_stage': notes_written if not args.dry_run else len(notes),
        'daily_log_file': daily_log_file,
        'audit_file': audit_file,
        'notes_appended': notes_written if not args.dry_run else 0,
        'dry_run': args.dry_run,
    }

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def _count_all_entries(filepath: str) -> int:
    """Count total valid entries in the corrections file."""
    path = Path(filepath)
    if not path.exists():
        return 0

    count = 0
    with open(path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                json.loads(line)
                count += 1
            except (json.JSONDecodeError, ValueError):
                continue
    return count


if __name__ == '__main__':
    sys.exit(main())
