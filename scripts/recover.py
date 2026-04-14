#!/usr/bin/env python3
"""
truth-recovery: recover mode — minimal deterministic anchor recovery helper

Searches local deterministic surfaces for an anchor to support a specific
factual claim. Returns the best anchor found and its strength class.

This script handles only the deterministic parts of recovery:
- Correction register lookup
- Pending-action journal lookup
- File-based memory search (grep-level, not semantic)

When local surfaces are insufficient, it signals that the host agent
should perform additional retrieval using its own tools. It does NOT
prescribe which tools to use — that is the host's routing decision.

Usage:
    python3 recover.py --query "Where did the user go last weekend?"
    python3 recover.py --query "What was the decision about the pricing?"
    python3 recover.py --query "Did the deploy succeed?" --check-pending
"""

import argparse
import glob
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

DEFAULT_CORRECTIONS = 'runtime/truth-recovery/recent-corrections.jsonl'
DEFAULT_PENDING = 'runtime/pending-actions/pending-actions.jsonl'
DEFAULT_MEMORY = 'MEMORY.md'
DEFAULT_DAILY_LOG_DIR = 'memory'

STOPWORDS = {
    'what', 'when', 'where', 'which', 'who', 'whom', 'whose', 'why', 'how',
    'the', 'this', 'that', 'these', 'those', 'with', 'from', 'into', 'onto',
    'about', 'over', 'under', 'after', 'before', 'during', 'have', 'has',
    'had', 'does', 'did', 'was', 'were', 'will', 'would', 'should', 'could',
    'can', 'may', 'might', 'must', 'for', 'and', 'but', 'not', 'you', 'your',
    'their', 'them', 'they', 'our', 'ours', 'his', 'her', 'hers', 'its', 'are',
    'is', 'am', 'been', 'being', 'tell', 'give', 'show', 'please',
}

SUBJECT_EXCLUDE = {
    'what', 'when', 'where', 'which', 'who', 'why', 'how', 'did', 'does',
    'is', 'are', 'was', 'were', 'tell', 'show',
}

CALENDAR_EXCLUDE = {
    'january', 'february', 'march', 'april', 'may', 'june', 'july',
    'august', 'september', 'october', 'november', 'december',
    'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday',
    'today', 'tomorrow', 'yesterday', 'week', 'weekend', 'month', 'year',
    'morning', 'afternoon', 'evening', 'night', 'midnight', 'noon',
    'date', 'time', 'day', 'daily', 'hour', 'minute', 'calendar',
}

STRICT_QUERY_TERMS = {
    'favorite', 'likes', 'prefers', 'belongs to', 'from', 'works at', 'date',
    'version', 'status', 'owner', 'ownership',
}

AMBIENT_COLLISION_TERMS = {
    'color', 'blue', 'status', 'date', 'project', 'version', 'favorite',
    'likes', 'prefers', 'owner', 'ownership',
}

META_LOG_TERMS = {
    'test', 'validation', 'smoke', 'example', 'sample', 'dummy', 'debug',
    'note', 'check', 'verify', 'verified', 'query', 'patch', 'compile',
    'compiled', 'mirrored', 'installed', 'plugin', 'recover.py', 'recovery',
}

NAME_LIKE_EXCLUDE = {
    *SUBJECT_EXCLUDE,
    *CALENDAR_EXCLUDE,
    'family', 'birthday', 'version', 'status', 'memory', 'validation', 'test',
}


# --- Anchor Strength ---

STRENGTH_STRONG = 'strong'
STRENGTH_MEDIUM = 'medium'
STRENGTH_WEAK = 'weak'
STRENGTH_NONE = 'none'


def tokenize(text: str) -> list:
    tokens = []
    for raw in re.findall(r"[A-Za-z0-9][A-Za-z0-9'_-]*", text):
        token = raw.lower().strip('_-')
        if token.endswith("'s"):
            token = token[:-2]
        if len(token) >= 3:
            tokens.append(token)
    return tokens


def extract_subject_tokens(query: str) -> set:
    subjects = set()

    for raw in re.findall(r"\b([A-Z][A-Za-z0-9_-]{2,}|[A-Z]{2,}[A-Z0-9_-]*)\b", query):
        token = raw.lower()
        if token not in SUBJECT_EXCLUDE and token not in CALENDAR_EXCLUDE:
            subjects.add(token)

    for raw in re.findall(r"\b([A-Za-z0-9_-]{3,})'s\b", query):
        token = raw.lower()
        if token not in SUBJECT_EXCLUDE and token not in CALENDAR_EXCLUDE:
            subjects.add(token)

    return subjects


def build_query_profile(query: str) -> dict:
    query_lower = query.lower()
    keywords = set(tokenize(query)) - STOPWORDS
    subject_tokens = extract_subject_tokens(query)

    strict_hits = set()
    for term in STRICT_QUERY_TERMS:
        if ' ' in term:
            if term in query_lower:
                strict_hits.add(term)
        elif term in keywords:
            strict_hits.add(term)

    strict_single_terms = {term for term in STRICT_QUERY_TERMS if ' ' not in term}
    support_terms = keywords - subject_tokens - STOPWORDS - AMBIENT_COLLISION_TERMS - strict_single_terms

    return {
        'keywords': keywords,
        'subject_tokens': subject_tokens,
        'support_terms': support_terms,
        'has_named_subject': bool(subject_tokens),
        'requires_strict_binding': bool(subject_tokens) and bool(strict_hits),
        'strict_hits': strict_hits,
    }


def extract_name_like_tokens(text: str) -> list:
    seen = set()
    ordered = []
    for raw in re.findall(r"\b([A-Z][A-Za-z0-9_-]{2,}|[A-Z]{2,}[A-Z0-9_-]*)'?s?\b", text):
        token = raw.lower()
        if token in NAME_LIKE_EXCLUDE:
            continue
        if token not in seen:
            seen.add(token)
            ordered.append(token)
    return ordered


def subject_focus_assessment(profile: dict, candidate_text: str, candidate_keywords: set,
                             subject_overlap: set, supporting_overlap: set) -> dict:
    if not profile['has_named_subject'] or not subject_overlap:
        return {
            'subject_focused': False,
            'meta_or_test_like': False,
            'mixed_subject_line': False,
            'primary_subject_match': False,
            'primary_subject_token': None,
            'subject_support_distance': None,
        }

    text_lower = candidate_text.lower()
    ordered_tokens = tokenize(candidate_text)
    name_like_tokens = extract_name_like_tokens(candidate_text)
    primary_subject_token = name_like_tokens[0] if name_like_tokens else None
    primary_subject_match = primary_subject_token in profile['subject_tokens'] if primary_subject_token else False
    other_named_entities = [token for token in name_like_tokens if token not in profile['subject_tokens']]
    mixed_subject_line = bool(other_named_entities) and not primary_subject_match

    direct_subject_pattern = False
    for subject in subject_overlap:
        if re.search(rf"\b{re.escape(subject)}'s\b", text_lower):
            direct_subject_pattern = True
            break
        if re.search(rf"\b{re.escape(subject)}\s+(is|was|has|had|likes|liked|prefers|preferred|works|worked|owns|owned|belongs)\b", text_lower):
            direct_subject_pattern = True
            break

    subject_positions = [i for i, token in enumerate(ordered_tokens) if token in profile['subject_tokens']]
    support_positions = [i for i, token in enumerate(ordered_tokens) if token in profile['support_terms']]
    subject_support_distance = None
    if subject_positions and support_positions:
        subject_support_distance = min(abs(s - t) for s in subject_positions for t in support_positions)

    subject_near_support = subject_support_distance is not None and subject_support_distance <= 4
    meta_or_test_like = bool(candidate_keywords & META_LOG_TERMS)

    subject_focused = (
        primary_subject_match and (
            direct_subject_pattern or
            subject_near_support or
            (bool(subject_overlap) and bool(supporting_overlap) and not mixed_subject_line)
        )
    )

    return {
        'subject_focused': subject_focused,
        'meta_or_test_like': meta_or_test_like,
        'mixed_subject_line': mixed_subject_line,
        'primary_subject_match': primary_subject_match,
        'primary_subject_token': primary_subject_token,
        'subject_support_distance': subject_support_distance,
        'direct_subject_pattern': direct_subject_pattern,
    }


def assess_candidate(profile: dict, candidate_text: str, base_strength: str) -> dict | None:
    candidate_keywords = set(tokenize(candidate_text))
    text_overlap = profile['keywords'] & candidate_keywords
    if not text_overlap:
        return None

    subject_overlap = profile['subject_tokens'] & candidate_keywords
    supporting_overlap = profile['support_terms'] & candidate_keywords

    text_match_found = True
    entity_aligned = bool(subject_overlap) if profile['has_named_subject'] else len(text_overlap) >= 2
    possible_ambient_collision = False
    usable_anchor = False
    strength = base_strength

    if profile['requires_strict_binding']:
        if not subject_overlap:
            strength = STRENGTH_WEAK
            possible_ambient_collision = bool(text_overlap & AMBIENT_COLLISION_TERMS) or len(text_overlap) <= 2
        else:
            usable_anchor = bool(supporting_overlap)
            if not usable_anchor:
                strength = STRENGTH_WEAK
                possible_ambient_collision = bool(text_overlap & AMBIENT_COLLISION_TERMS) or len(text_overlap) <= 2
    elif profile['has_named_subject']:
        if not subject_overlap:
            strength = STRENGTH_WEAK
            possible_ambient_collision = bool(text_overlap & AMBIENT_COLLISION_TERMS) or len(text_overlap) <= 2
        else:
            usable_anchor = len(text_overlap) >= 2
            if not usable_anchor:
                strength = STRENGTH_WEAK
    else:
        usable_anchor = len(text_overlap) >= 2
        if not usable_anchor:
            strength = STRENGTH_WEAK

    focus = subject_focus_assessment(
        profile,
        candidate_text,
        candidate_keywords,
        subject_overlap,
        supporting_overlap,
    )

    if (
        usable_anchor and
        strength == base_strength == STRENGTH_MEDIUM and
        focus.get('subject_focused') and
        focus.get('direct_subject_pattern') and
        not focus.get('meta_or_test_like')
    ):
        strength = STRENGTH_STRONG

    return {
        'text_match_found': text_match_found,
        'entity_aligned': entity_aligned,
        'usable_anchor': usable_anchor,
        'possible_ambient_collision': possible_ambient_collision,
        'match_keywords': sorted(text_overlap),
        'subject_overlap': sorted(subject_overlap),
        'supporting_overlap': sorted(supporting_overlap),
        'strength': strength,
        **focus,
    }


# --- Surface Searchers ---

def search_corrections(profile: dict, filepath: str) -> list:
    """Search recent corrections register for relevant entries."""
    results = []
    path = Path(filepath)
    if not path.exists():
        return results

    with open(path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                old_lower = entry.get('old', '').lower()
                corrected_lower = entry.get('corrected', '').lower()
                scope_lower = entry.get('scope', '').lower()
                context_lower = entry.get('context', '').lower()

                entry_text = f'{old_lower} {corrected_lower} {scope_lower} {context_lower}'
                assessment = assess_candidate(profile, entry_text, STRENGTH_STRONG)

                if assessment:
                    results.append({
                        'surface': 'recent_corrections',
                        'strength': assessment['strength'],
                        'data': entry,
                        'note': 'User correction — highest priority anchor',
                        **assessment,
                    })
            except (json.JSONDecodeError, ValueError):
                continue

    return results


def search_pending_actions(profile: dict, filepath: str) -> list:
    """Search pending-action journal for relevant entries."""
    results = []
    path = Path(filepath)
    if not path.exists():
        return results

    with open(path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                action_lower = entry.get('action', '').lower()
                status_lower = entry.get('status', '').lower()
                context_lower = entry.get('context', '').lower()

                entry_text = f'{action_lower} {status_lower} {context_lower}'
                assessment = assess_candidate(profile, entry_text, STRENGTH_MEDIUM)

                if assessment:
                    results.append({
                        'surface': 'pending_actions',
                        'strength': assessment['strength'],
                        'data': entry,
                        'note': 'Pending action journal — medium anchor',
                        **assessment,
                    })
            except (json.JSONDecodeError, ValueError):
                continue

    return results


def search_memory_file(profile: dict, filepath: str, surface_name: str = 'durable_memory') -> list:
    """Grep-level search through a markdown memory file."""
    results = []
    path = Path(filepath)
    if not path.exists():
        return results

    if not profile['keywords']:
        return results

    try:
        with open(path, 'r') as f:
            content = f.read()
    except (IOError, UnicodeDecodeError):
        return results

    lines = content.split('\n')
    current_section = 'unknown'

    for i, line in enumerate(lines):
        if line.startswith('## '):
            current_section = line.lstrip('# ').strip()
            continue

        assessment = assess_candidate(profile, line, STRENGTH_MEDIUM)

        # Require at least 2 keyword matches before surfacing a file hit
        if assessment and len(assessment['match_keywords']) >= 2:
            context_lines = []
            if i > 0:
                context_lines.append(lines[i - 1])
            context_lines.append(line)
            if i < len(lines) - 1:
                context_lines.append(lines[i + 1])

            results.append({
                'surface': surface_name,
                'strength': assessment['strength'],
                'data': {
                    'section': current_section,
                    'line_number': i + 1,
                    'text': line.strip(),
                    'context': '\n'.join(context_lines).strip(),
                    'file': str(filepath),
                },
                'note': f'Found in {current_section} section of {filepath}',
                **assessment,
            })

    return results


def search_daily_logs(profile: dict, log_dir: str, days: int = 7) -> list:
    """Search recent daily logs for relevant entries."""
    results = []

    if not profile['keywords']:
        return results

    cutoff = datetime.now().astimezone() - timedelta(days=days)

    pattern = os.path.join(log_dir, '????-??-??.md')
    log_files = sorted(glob.glob(pattern), reverse=True)

    for log_file in log_files:
        basename = os.path.basename(log_file).replace('.md', '')
        try:
            file_date = datetime.strptime(basename, '%Y-%m-%d').replace(tzinfo=datetime.now().astimezone().tzinfo)
            if file_date < cutoff:
                continue
        except ValueError:
            continue

        try:
            with open(log_file, 'r') as f:
                content = f.read()
        except (IOError, UnicodeDecodeError):
            continue

        for i, line in enumerate(content.split('\n')):
            assessment = assess_candidate(profile, line, STRENGTH_MEDIUM)

            if assessment and len(assessment['match_keywords']) >= 2:
                results.append({
                    'surface': 'scoped_daily_memory',
                    'strength': assessment['strength'],
                    'data': {
                        'file': log_file,
                        'date': basename,
                        'line_number': i + 1,
                        'text': line.strip(),
                    },
                    'note': f'Found in daily log {basename}',
                    **assessment,
                })

    return results


# --- Main Recovery ---

def run_recovery(query: str, corrections_file: str, pending_file: str,
                 memory_file: str, log_dir: str, check_pending: bool = False) -> dict:
    """Run deterministic anchor recovery and return results with strength assessment."""
    all_results = []
    profile = build_query_profile(query)

    # Priority 1: Current session — in-context only, not script-searchable

    # Priority 2: Recent corrections
    corrections = search_corrections(profile, corrections_file)
    all_results.extend(corrections)

    # Priority 3: Pending actions (if requested)
    if check_pending:
        pending = search_pending_actions(profile, pending_file)
        all_results.extend(pending)

    # Priority 4: Scoped daily memory
    daily = search_daily_logs(profile, log_dir, days=7)
    all_results.extend(daily)

    # Priority 5: Durable memory (MEMORY.md)
    durable = search_memory_file(profile, memory_file, 'durable_memory')
    all_results.extend(durable)

    # Priority 6: procedures.md
    procedures = search_memory_file(profile, os.path.join(log_dir, 'procedures.md'), 'procedural_memory')
    all_results.extend(procedures)

    # Sort usable anchors ahead of weak text matches, then prefer subject-focused,
    # non-meta, less mixed-subject candidates before overlap breadth.
    strength_order = {STRENGTH_STRONG: 0, STRENGTH_MEDIUM: 1, STRENGTH_WEAK: 2, STRENGTH_NONE: 3}
    all_results.sort(key=lambda r: (
        0 if r.get('usable_anchor') else 1,
        strength_order.get(r['strength'], 3),
        0 if r.get('subject_focused') else 1,
        0 if not r.get('meta_or_test_like') else 1,
        0 if not r.get('mixed_subject_line') else 1,
        0 if r.get('primary_subject_match') else 1,
        r.get('subject_support_distance') if r.get('subject_support_distance') is not None else 999,
        -len(r.get('supporting_overlap', [])),
        -len(r.get('subject_overlap', [])),
        -len(r.get('match_keywords', [])),
    ))

    usable_results = [r for r in all_results if r.get('usable_anchor')]
    best_strength = STRENGTH_NONE
    if usable_results:
        best_strength = usable_results[0]['strength']
    elif all_results:
        best_strength = STRENGTH_WEAK

    # Signal whether additional retrieval is needed
    needs_additional = best_strength in (STRENGTH_NONE, STRENGTH_WEAK)
    suggested_types = []
    host_routing_hint = None
    if best_strength == STRENGTH_NONE:
        suggested_types = ['semantic_memory', 'conversation_archive', 'external_authority']
        host_routing_hint = (
            "use the host's semantic memory retrieval surface first; if still unanchored, "
            "use the host's conversation/session retrieval surface, then the host's external authority path"
        )
    elif best_strength == STRENGTH_WEAK:
        suggested_types = ['semantic_memory', 'conversation_archive']
        host_routing_hint = (
            "use the host's semantic memory retrieval surface first, then the host's conversation/session retrieval surface"
        )
    elif best_strength == STRENGTH_MEDIUM:
        suggested_types = ['semantic_memory']
        host_routing_hint = "use the host's semantic memory retrieval surface"

    return {
        'query': query,
        'named_subjects': sorted(profile['subject_tokens']),
        'anchors_found': len(all_results),
        'usable_anchors_found': len(usable_results),
        'best_strength': best_strength,
        'results': all_results[:10],
        'surfaces_searched': [
            'recent_corrections',
            'pending_actions' if check_pending else '(skipped) pending_actions',
            'scoped_daily_memory',
            'durable_memory',
            'procedural_memory',
        ],
        'needs_additional_retrieval': needs_additional,
        'possible_ambient_collision': any(r.get('possible_ambient_collision') for r in all_results),
        'suggested_surface_types': suggested_types if needs_additional else [],
        'host_routing_hint': host_routing_hint if needs_additional else None,
        'recommended_mode': (
            'anchored' if best_strength == STRENGTH_STRONG else
            'tentative' if best_strength == STRENGTH_MEDIUM else
            'unanchored'
        ),
    }


def main():
    parser = argparse.ArgumentParser(
        description='Truth Recovery: Recover Mode — Minimal Deterministic Anchor Recovery',
    )
    parser.add_argument('--query', required=True, help='The factual question to find an anchor for')
    parser.add_argument('--corrections-file', default=DEFAULT_CORRECTIONS,
                        help='Path to corrections JSONL')
    parser.add_argument('--pending-file', default=DEFAULT_PENDING,
                        help='Path to pending actions JSONL')
    parser.add_argument('--memory-file', default=DEFAULT_MEMORY,
                        help='Path to MEMORY.md')
    parser.add_argument('--log-dir', default=DEFAULT_DAILY_LOG_DIR,
                        help='Directory containing daily logs')
    parser.add_argument('--check-pending', action='store_true',
                        help='Include pending-action journal in search')
    parser.add_argument('--days', type=int, default=7,
                        help='How many days of daily logs to search')

    args = parser.parse_args()

    result = run_recovery(
        args.query,
        args.corrections_file,
        args.pending_file,
        args.memory_file,
        args.log_dir,
        args.check_pending,
    )

    print(json.dumps(result, indent=2, ensure_ascii=False))

    return 0


if __name__ == '__main__':
    sys.exit(main())
