#!/usr/bin/env python3
"""
truth-recovery: init_harness_config — safe merge/init for namespaced harness-state.json

Safely initializes or updates the truth-recovery namespace in a shared
global harness-state.json without destroying other packages' namespaces.

Behavior:
    - If file does not exist → create it with truthRecovery namespace
    - If file exists but truthRecovery is missing → merge it in
    - If file exists and truthRecovery already present → skip (no overwrite, no duplicate)
    - Never destroys other packages' namespaces (autoDream, memoryCoreObserver, etc.)

This pattern is reusable by any package that writes to harness-state.json —
each package only touches its own namespace key.

Usage:
    python3 scripts/init_harness_config.py --file <workspace>/runtime/harness-state/harness-state.json
    python3 scripts/init_harness_config.py --file <path> --nightly-chat true
    python3 scripts/init_harness_config.py --file <path> --hourly-chat true
    python3 scripts/init_harness_config.py --file <path> --force   # overwrite existing truthRecovery
    python3 scripts/init_harness_config.py --file <path> --dry-run
"""

import argparse
import json
import os
import sys
from pathlib import Path

DEFAULT_FILE = 'runtime/harness-state/harness-state.json'


def _default_truth_recovery_config(nightly_chat: bool = False,
                                    hourly_chat: bool = False) -> dict:
    """Build the default truthRecovery namespace config."""
    return {
        'version': '1.0',
        'session_context_level': 'thin',
        'last_correction_check': None,
        'corrections_active': 0,
        'pending_actions_active': 0,
        'reporting': {
            'nightlyChatReport': nightly_chat,
            'sendHourlyChatReport': hourly_chat,
            'delivery': {
                'channel': 'last',
                'to': None,
            },
        },
        'stats': {
            'checks_total': 0,
            'checks_specific': 0,
            'checks_gated': 0,
            'corrections_recorded': 0,
            'recoveries_run': 0,
            'anchored_outputs': 0,
            'tentative_outputs': 0,
            'unanchored_outputs': 0,
        },
    }


def init_harness_config(filepath: str, nightly_chat: bool = False,
                        hourly_chat: bool = False, force: bool = False,
                        dry_run: bool = False) -> dict:
    """Safely initialize or merge the truthRecovery namespace into harness-state.json.

    Returns a result dict describing what happened.
    """
    path = Path(filepath)
    existing = {}
    file_existed = path.exists()

    # Load existing config if present
    if file_existed:
        try:
            with open(path, 'r') as f:
                existing = json.load(f)
            if not isinstance(existing, dict):
                existing = {}
        except (json.JSONDecodeError, IOError):
            existing = {}

    # Check if truthRecovery namespace already exists
    already_present = 'truthRecovery' in existing

    if already_present and not force:
        return {
            'action': 'skipped',
            'reason': 'truthRecovery namespace already exists in harness-state.json',
            'file': filepath,
            'file_existed': file_existed,
            'already_present': True,
            'dry_run': dry_run,
        }

    # Build the new config
    tr_config = _default_truth_recovery_config(nightly_chat, hourly_chat)

    if dry_run:
        action = 'would_overwrite' if already_present else ('would_merge' if file_existed else 'would_create')
        return {
            'action': action,
            'file': filepath,
            'file_existed': file_existed,
            'already_present': already_present,
            'truthRecovery': tr_config,
            'other_namespaces_preserved': list(k for k in existing if k != 'truthRecovery'),
            'dry_run': True,
        }

    # Merge: set truthRecovery, preserve everything else
    existing['truthRecovery'] = tr_config

    # Write
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w') as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)
        f.write('\n')

    action = 'overwritten' if already_present else ('merged' if file_existed else 'created')
    return {
        'action': action,
        'file': filepath,
        'file_existed': file_existed,
        'already_present': already_present,
        'other_namespaces_preserved': list(k for k in existing if k != 'truthRecovery'),
        'dry_run': False,
    }


def main():
    parser = argparse.ArgumentParser(
        description='Truth Recovery: Safe Harness Config Initializer',
        epilog='Safely merges the truthRecovery namespace into a shared harness-state.json without destroying other packages.',
    )
    parser.add_argument('--file', default=DEFAULT_FILE,
                        help='Path to harness-state.json')
    parser.add_argument('--nightly-chat', type=lambda v: v.lower() in ('true', '1', 'yes'), default=False,
                        help='Enable nightly chat report delivery (true/false)')
    parser.add_argument('--hourly-chat', type=lambda v: v.lower() in ('true', '1', 'yes'), default=False,
                        help='Enable hourly chat report delivery (true/false)')
    parser.add_argument('--force', action='store_true',
                        help='Overwrite existing truthRecovery namespace (default: skip if present)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would happen without writing')
    args = parser.parse_args()

    result = init_harness_config(
        args.file,
        nightly_chat=args.nightly_chat,
        hourly_chat=args.hourly_chat,
        force=args.force,
        dry_run=args.dry_run,
    )

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
