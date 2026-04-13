#!/usr/bin/env python3
"""
truth-recovery: check mode — pre-output gate classifier

Classifies a statement as specific or general, looks up the recent
corrections register, and returns the recommended output mode.

Usage:
    python3 check.py --claim "You went to the resort last weekend"
    python3 check.py --claim "How's your project going?"
    python3 check.py --claim "The meeting was at 3 PM yesterday" --corrections-file path/to/recent-corrections.jsonl
    python3 check.py --claim "specific claim" --specificity specific --claim-type location
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# --- Claim Classification ---

# Patterns that indicate a specific factual claim
SPECIFIC_PATTERNS = [
    # Locations
    (r'\b(?:went to|visited|traveled to|was in|arrived at|headed to|drove to|flew to)\s+[A-Z]', 'location'),
    (r'\b(?:in|at|from|near)\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*', 'location'),

    # Dates and times
    (r'\b(?:on|last|this|next)\s+(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)', 'date'),
    (r'\b(?:yesterday|today|tomorrow|last\s+week|last\s+month|last\s+weekend)', 'date'),
    (r'\b(?:at|around|by)\s+\d{1,2}(?::\d{2})?\s*(?:AM|PM|am|pm)', 'time'),
    (r'\b\d{4}-\d{2}-\d{2}\b', 'date'),

    # People — specific names
    (r'\b(?:you told|you said|you mentioned|you asked|you decided)\b', 'prior_statement'),
    (r'\b(?:told me|said that|mentioned that|decided to|agreed to)\b', 'prior_statement'),
    (r'\b(?:Sir|Mr|Ms|Mrs|Dr)\s+[A-Z]', 'person'),

    # Prior events / decisions
    (r'\b(?:last time|previously|before|earlier|we decided|we agreed|we said)\b', 'prior_event'),
    (r'\b(?:the decision was|the plan was|we were going to|you were working on)\b', 'prior_event'),

    # Specific quantities / details
    (r'\b(?:exactly|precisely|specifically)\s+\d', 'quantity'),
    (r'\b[₱$€£]\s*[\d,]+', 'quantity'),

    # Corrected details — referencing something that was corrected
    (r'\b(?:actually|correction|corrected|updated|changed to|not .+ but)\b', 'corrected_detail'),

    # Prior action outcomes
    (r'\b(?:did that work|how did it go|what happened after|result of|outcome of)\b', 'prior_action'),
]

# Patterns that indicate a NON-specific statement (skip)
GENERAL_PATTERNS = [
    r'^(?:hi|hello|hey|good morning|good evening|how are you)',
    r'^(?:thanks|thank you|ok|okay|sure|got it|understood)',
    r'\b(?:generally|usually|often|sometimes|might|maybe|probably|could be)\b',
    r'^(?:what is|how does|can you explain|tell me about)\b',
]


def classify_claim(claim: str, specificity_override: str = None,
                   claim_type_override: str = None) -> dict:
    """Classify whether a claim is specific or general.

    Args:
        claim: The statement to classify.
        specificity_override: 'specific', 'general', or None (auto-detect).
        claim_type_override: Optional claim type when host already knows.
    """
    # Host can override regex classification
    if specificity_override == 'specific':
        return {
            'is_specific': True,
            'claim_type': claim_type_override or 'host_override',
            'matched_pattern': None,
            'classification_source': 'host_override',
        }
    if specificity_override == 'general':
        return {
            'is_specific': False,
            'claim_type': 'general',
            'matched_pattern': None,
            'classification_source': 'host_override',
        }

    claim_lower = claim.lower().strip()

    # Check general patterns first (fast exit)
    for pattern in GENERAL_PATTERNS:
        if re.search(pattern, claim_lower):
            return {
                'is_specific': False,
                'claim_type': 'general',
                'matched_pattern': pattern,
                'classification_source': 'regex',
            }

    # Check specific patterns
    for pattern, claim_type in SPECIFIC_PATTERNS:
        if re.search(pattern, claim, re.IGNORECASE):
            return {
                'is_specific': True,
                'claim_type': claim_type_override or claim_type,
                'matched_pattern': pattern,
                'classification_source': 'regex',
            }

    # Default: not specific enough to gate
    return {
        'is_specific': False,
        'claim_type': 'general',
        'matched_pattern': None,
        'classification_source': 'regex',
    }


# --- Correction Lookup ---

def load_corrections(corrections_file: str, max_age_days: int = 30) -> list:
    """Load recent corrections from JSONL file."""
    corrections = []
    path = Path(corrections_file)

    if not path.exists():
        return corrections

    cutoff = datetime.now().astimezone() - timedelta(days=max_age_days)

    with open(path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                ts = entry.get('timestamp', '')
                if ts:
                    entry_time = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                    if entry_time < cutoff:
                        continue
                corrections.append(entry)
            except (json.JSONDecodeError, ValueError):
                continue

    return corrections


def find_matching_corrections(claim: str, corrections: list) -> list:
    """Find corrections that are relevant to the given claim."""
    matches = []
    claim_lower = claim.lower()

    for correction in corrections:
        old_val = correction.get('old', '').lower()
        corrected_val = correction.get('corrected', '').lower()

        # Check if the claim mentions the old (incorrect) value
        if old_val and old_val in claim_lower:
            matches.append({
                'old': correction.get('old'),
                'corrected': correction.get('corrected'),
                'timestamp': correction.get('timestamp'),
                'confidence': correction.get('source', 'unknown'),
                'scope': correction.get('scope'),
                'match_type': 'old_value_in_claim',
            })

        # Check if the claim mentions the corrected value (good — using correct info)
        elif corrected_val and corrected_val in claim_lower:
            matches.append({
                'old': correction.get('old'),
                'corrected': correction.get('corrected'),
                'timestamp': correction.get('timestamp'),
                'confidence': correction.get('source', 'unknown'),
                'scope': correction.get('scope'),
                'match_type': 'corrected_value_in_claim',
            })

    return matches


# --- Output Mode Decision ---

def determine_output_mode(classification: dict, corrections: list) -> dict:
    """Determine the recommended output mode based on classification and corrections."""

    if not classification['is_specific']:
        return {
            'recommended_mode': 'normal',
            'reason': 'Claim is not specific — no gating needed',
            'needs_recovery': False,
            'correction_conflict': False,
        }

    # Check if any corrections contradict the claim
    contradicting = [c for c in corrections if c['match_type'] == 'old_value_in_claim']
    confirming = [c for c in corrections if c['match_type'] == 'corrected_value_in_claim']

    if contradicting:
        return {
            'recommended_mode': 'unanchored',
            'reason': f"Active correction exists: '{contradicting[0]['old']}' was corrected to '{contradicting[0]['corrected']}'",
            'needs_recovery': False,
            'correction_conflict': True,
        }

    if confirming:
        return {
            'recommended_mode': 'anchored',
            'reason': f"Claim uses corrected value '{confirming[0]['corrected']}' — matches recent correction",
            'needs_recovery': False,
            'correction_conflict': False,
        }

    # Specific claim with no correction data — needs anchor check
    return {
        'recommended_mode': 'needs_anchor_check',
        'reason': f"Specific claim (type: {classification['claim_type']}) — requires anchor verification",
        'needs_recovery': True,
        'correction_conflict': False,
    }


# --- Main ---

def main():
    parser = argparse.ArgumentParser(description='Truth Recovery: Check Mode — Pre-Output Gate')
    parser.add_argument('--claim', required=True, help='The statement to classify')
    parser.add_argument('--corrections-file', default='runtime/truth-recovery/recent-corrections.jsonl',
                        help='Path to corrections JSONL file')
    parser.add_argument('--max-age-days', type=int, default=30,
                        help='Max age of corrections to consider (days)')
    parser.add_argument('--specificity', choices=['auto', 'specific', 'general'], default='auto',
                        help='Override regex classification (default: auto-detect)')
    parser.add_argument('--claim-type', default=None,
                        help='Claim type when host already knows (e.g., location, date, person)')
    args = parser.parse_args()

    # Resolve specificity override
    specificity_override = None if args.specificity == 'auto' else args.specificity

    # Step 1: Classify
    classification = classify_claim(args.claim, specificity_override, args.claim_type)

    # Step 2: Load and search corrections
    corrections_list = load_corrections(args.corrections_file, args.max_age_days)
    matching_corrections = find_matching_corrections(args.claim, corrections_list)

    # Step 3: Determine output mode
    mode_decision = determine_output_mode(classification, matching_corrections)

    # Build result
    result = {
        'claim': args.claim,
        'is_specific': classification['is_specific'],
        'claim_type': classification['claim_type'],
        'corrections_found': matching_corrections,
        'corrections_checked': len(corrections_list),
        'recommended_mode': mode_decision['recommended_mode'],
        'reason': mode_decision['reason'],
        'needs_recovery': mode_decision['needs_recovery'],
        'correction_conflict': mode_decision['correction_conflict'],
    }

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
