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
    'diagnostic', 'incorrect', 'error', 'warning', 'failure', 'trace',
}

NAME_LIKE_EXCLUDE = {
    *SUBJECT_EXCLUDE,
    *CALENDAR_EXCLUDE,
    'family', 'birthday', 'version', 'status', 'memory', 'validation', 'test',
    'diagnostic', 'incorrect', 'error', 'warning', 'failure', 'trace',
}

SURFACE_SCORES = {
    'recent_corrections': 1.0,
    'pending_actions': 0.75,
    'scoped_daily_memory': 0.65,
    'durable_memory': 0.55,
    'procedural_memory': 0.45,
}

TIME_TERMS = {
    'today', 'tomorrow', 'yesterday', 'morning', 'afternoon', 'evening', 'night',
    'midnight', 'noon', 'week', 'weekend', 'month', 'year', 'friday', 'monday',
    'tuesday', 'wednesday', 'thursday', 'saturday', 'sunday',
    'january', 'february', 'march', 'april', 'may', 'june', 'july',
    'august', 'september', 'october', 'november', 'december',
}

LOCATION_TERMS = {
    'office', 'home', 'tagaytay', 'manila', 'school', 'house', 'site', 'server',
    'gateway', 'desk', 'room', 'lab', 'clinic', 'hospital', 'vps', 'pi',
}

STATUS_TERMS = {
    'up', 'down', 'online', 'offline', 'stable', 'broken', 'available', 'pending',
    'enabled', 'disabled', 'working', 'failed', 'succeeded', 'healthy',
}

VERSION_TERMS = {
    'version', 'release', 'build', 'upgrade', 'updated', 'patch', 'plugin',
}

PREFERENCE_TERMS = {
    'favorite', 'likes', 'liked', 'prefers', 'preferred', 'color',
}

OWNERSHIP_TERMS = {
    'owner', 'ownership', 'belongs', 'belong', 'whose',
}

ATTRIBUTE_TERMS = {
    'tag', 'birthday', 'color', 'model', 'name', 'status', 'version',
}

EVENT_TERMS = {
    'went', 'was', 'were', 'met', 'visited', 'joined', 'left', 'deployed',
    'installed', 'reported', 'started', 'ended', 'called', 'said',
}

DIAGNOSTIC_NOISE_TERMS = {
    'diagnostic', 'incorrect', 'error', 'warning', 'failure', 'trace', 'debug',
    'validation', 'smoke', 'test', 'verify', 'verified',
}

UNCERTAINTY_TERMS = {
    'unconfirmed', 'uncertain', 'unknown', 'maybe', 'perhaps', 'likely',
}


# --- Anchor Strength ---

STRENGTH_STRONG = 'strong'
STRENGTH_MEDIUM = 'medium'
STRENGTH_WEAK = 'weak'
STRENGTH_NONE = 'none'

STRENGTH_VALUE = {
    STRENGTH_NONE: 0,
    STRENGTH_WEAK: 1,
    STRENGTH_MEDIUM: 2,
    STRENGTH_STRONG: 3,
}


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


def clamp_score(value: float) -> float:
    return max(0.0, min(1.0, round(value, 4)))


def score_to_strength(score: float) -> str:
    if score >= 0.70:
        return STRENGTH_STRONG
    if score >= 0.45:
        return STRENGTH_MEDIUM
    if score >= 0.15:
        return STRENGTH_WEAK
    return STRENGTH_NONE


def stronger_strength(a: str, b: str) -> str:
    return a if STRENGTH_VALUE.get(a, 0) >= STRENGTH_VALUE.get(b, 0) else b


def weaker_strength(a: str, b: str) -> str:
    return a if STRENGTH_VALUE.get(a, 0) <= STRENGTH_VALUE.get(b, 0) else b


def infer_claim_type(query: str, profile: dict) -> str:
    query_lower = query.lower()

    has_time = (
        'when' in query_lower or
        bool(TIME_TERMS & set(tokenize(query_lower))) or
        bool(re.search(r'\b\d{1,2}:\d{2}\s*(?:am|pm)?\b', query_lower)) or
        bool(re.search(r'\b\d{4}-\d{2}-\d{2}\b', query_lower))
    )
    has_location = 'where' in query_lower or bool(LOCATION_TERMS & set(tokenize(query_lower)))
    has_status = bool(STATUS_TERMS & set(tokenize(query_lower)))
    has_version = bool(VERSION_TERMS & set(tokenize(query_lower)))
    has_preference = bool({'favorite', 'likes', 'liked', 'prefers', 'preferred'} & set(tokenize(query_lower)))
    has_ownership = bool(OWNERSHIP_TERMS & set(tokenize(query_lower)))
    has_attribute = bool(ATTRIBUTE_TERMS & set(tokenize(query_lower)))
    has_event = profile['has_named_subject'] and (
        bool(EVENT_TERMS & set(tokenize(query_lower))) or
        'last ' in query_lower or
        'yesterday' in query_lower
    )

    if has_version:
        return 'version'
    if has_status:
        return 'status'
    if has_ownership:
        return 'ownership'
    if has_preference:
        return 'preference'
    if has_attribute:
        return 'attribute'
    if has_event and (has_time or has_location):
        return 'event'
    if has_time:
        return 'time'
    if has_location:
        return 'location'
    if has_event:
        return 'event'
    return 'general'


def extract_query_temporal_hints(query: str) -> dict:
    query_lower = query.lower()
    weekday_match = re.search(
        r'\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b',
        query_lower,
    )
    explicit_date_match = re.search(r'\b(\d{4}-\d{2}-\d{2})\b', query_lower)

    return {
        'is_current': any(term in query_lower for term in ('current', 'currently', 'now', 'latest', 'today')),
        'has_relative_recent': any(term in query_lower for term in ('yesterday', 'last ', 'recent', 'recently', 'tonight', 'this morning', 'this afternoon', 'this evening')),
        'weekday': weekday_match.group(1) if weekday_match else None,
        'explicit_date': explicit_date_match.group(1) if explicit_date_match else None,
    }


def extract_candidate_timestamp(result: dict) -> datetime | None:
    data = result.get('data', {}) or {}

    for key in ('timestamp_local', 'timestamp', 'date'):
        raw = data.get(key)
        if not raw:
            continue
        if key == 'date':
            try:
                return datetime.strptime(raw, '%Y-%m-%d').replace(tzinfo=datetime.now().astimezone().tzinfo)
            except ValueError:
                continue
        try:
            candidate = raw.replace('Z', '+00:00')
            dt = datetime.fromisoformat(candidate)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=datetime.now().astimezone().tzinfo)
            return dt.astimezone(datetime.now().astimezone().tzinfo)
        except ValueError:
            continue

    return None


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
            'direct_subject_pattern': False,
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
        if re.search(rf"\b{re.escape(subject)}\s+(is|was|has|had|likes|liked|prefers|preferred|works|worked|owns|owned|belongs|went|met|visited|joined|left)\b", text_lower):
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
    candidate_lower = candidate_text.lower()
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

    return {
        'text_match_found': text_match_found,
        'entity_aligned': entity_aligned,
        'usable_anchor': usable_anchor,
        'possible_ambient_collision': possible_ambient_collision,
        'uncertain_or_unverified': (
            any(term in candidate_lower for term in UNCERTAINTY_TERMS) or
            'not confirmed' in candidate_lower or
            'not verified' in candidate_lower or
            '?' in candidate_text
        ),
        'match_keywords': sorted(text_overlap),
        'subject_overlap': sorted(subject_overlap),
        'supporting_overlap': sorted(supporting_overlap),
        'strength': strength,
        **focus,
    }


def score_subject_alignment(profile: dict, result: dict) -> float:
    if profile['has_named_subject']:
        if not result.get('entity_aligned'):
            return 0.0

        score = 0.4
        if result.get('primary_subject_match'):
            score += 0.2
        if result.get('subject_focused'):
            score += 0.2
        if not result.get('mixed_subject_line'):
            score += 0.1

        distance = result.get('subject_support_distance')
        if distance is not None:
            if distance <= 2:
                score += 0.1
            elif distance <= 4:
                score += 0.08
            elif distance <= 8:
                score += 0.05

        if result.get('direct_subject_pattern'):
            score = max(score, 0.85)
        if result.get('possible_ambient_collision') and not result.get('subject_focused'):
            score = min(score, 0.25)

        return clamp_score(score)

    overlap = len(result.get('match_keywords', []))
    if result.get('usable_anchor') and overlap >= 3:
        return 0.7
    if result.get('text_match_found') and overlap >= 2:
        return 0.4
    return 0.0


def score_surface(result: dict) -> float:
    return SURFACE_SCORES.get(result.get('surface'), 0.35)


def score_specificity(query: str, result: dict) -> float:
    text = ((result.get('data') or {}).get('text') or result.get('data', {}).get('context') or '')
    if not text:
        entry = result.get('data') or {}
        text = ' '.join(str(entry.get(key, '')) for key in ('old', 'corrected', 'context', 'scope', 'action', 'status'))
    text_lower = text.lower()

    signals = 0
    if re.search(r'\b\d{4}-\d{2}-\d{2}\b', text_lower) or re.search(r'\b\d{1,2}:\d{2}\s*(?:am|pm)?\b', text_lower) or bool(TIME_TERMS & set(tokenize(text_lower))):
        signals += 1
    if re.search(r'\b\d+\b', text_lower):
        signals += 1
    if bool(LOCATION_TERMS & set(tokenize(text_lower))) or re.search(r'\b(?:in|at|to|from)\s+[A-Z][A-Za-z]+', text):
        signals += 1
    if bool(ATTRIBUTE_TERMS & set(tokenize(text_lower))) or re.search(r"\b[A-Z][A-Za-z0-9_-]{2,}'s\b", text):
        signals += 1
        if result.get('subject_focused'):
            signals += 1
    if bool(STATUS_TERMS & set(tokenize(text_lower))) or bool(VERSION_TERMS & set(tokenize(text_lower))):
        signals += 1
    if len(result.get('supporting_overlap', [])) >= 2:
        signals += 1

    if signals >= 3:
        return 1.0
    if signals == 2:
        return 0.7
    if signals == 1:
        return 0.4
    return 0.0


def score_temporal(claim_type: str, query_hints: dict, result: dict) -> float:
    surface = result.get('surface')
    text = ((result.get('data') or {}).get('text') or result.get('data', {}).get('context') or '').lower()
    if surface == 'recent_corrections':
        return 1.0
    if surface == 'pending_actions':
        return 0.85

    candidate_ts = extract_candidate_timestamp(result)
    if query_hints.get('explicit_date') and candidate_ts:
        return 1.0 if candidate_ts.strftime('%Y-%m-%d') == query_hints['explicit_date'] else 0.0

    if candidate_ts:
        now_local = datetime.now().astimezone()
        age_days = abs((now_local - candidate_ts).total_seconds()) / 86400.0

        if query_hints.get('weekday'):
            weekday_match = candidate_ts.strftime('%A').lower() == query_hints['weekday']
            if weekday_match and age_days <= 14:
                return 1.0
            if query_hints['weekday'] not in text and not bool(TIME_TERMS & set(tokenize(text))):
                return 0.1
            if age_days <= 14:
                return 0.4
            return 0.1

        if query_hints.get('is_current'):
            if age_days <= 2:
                return 1.0
            if age_days <= 7:
                return 0.7
            return 0.1

        if query_hints.get('has_relative_recent'):
            if age_days <= 7:
                return 0.7
            if age_days <= 30:
                return 0.4
            return 0.1

        if age_days <= 7:
            return 0.7
        if age_days <= 30:
            return 0.4
        return 0.1

    if surface == 'durable_memory' and not (
        query_hints.get('explicit_date') or query_hints.get('has_relative_recent') or query_hints.get('is_current')
    ):
        return 0.7
    return 0.4 if surface == 'durable_memory' else 0.2


def score_context_focus(result: dict) -> float:
    text = ((result.get('data') or {}).get('text') or result.get('data', {}).get('context') or '').lower()
    diagnostic_noise = bool(DIAGNOSTIC_NOISE_TERMS & set(tokenize(text)))

    if result.get('meta_or_test_like') or diagnostic_noise:
        if result.get('subject_focused') and result.get('direct_subject_pattern'):
            return 0.2
        return 0.0

    if result.get('subject_focused') and not result.get('mixed_subject_line'):
        distance = result.get('subject_support_distance')
        if distance is None or distance <= 4:
            return 1.0
        return 0.6

    if result.get('primary_subject_match') and not result.get('mixed_subject_line'):
        return 0.6

    if result.get('mixed_subject_line'):
        return 0.2

    return 0.2


def score_claim_type_match(claim_type: str, query: str, result: dict) -> float:
    text = ((result.get('data') or {}).get('text') or result.get('data', {}).get('context') or '')
    if not text:
        entry = result.get('data') or {}
        text = ' '.join(str(entry.get(key, '')) for key in ('old', 'corrected', 'context', 'scope', 'action', 'status'))
    text_lower = text.lower()
    tokens = set(tokenize(text_lower))

    has_time = bool(TIME_TERMS & tokens) or bool(re.search(r'\b\d{1,2}:\d{2}\s*(?:am|pm)?\b', text_lower)) or bool(re.search(r'\b\d{4}-\d{2}-\d{2}\b', text_lower))
    has_location = bool(LOCATION_TERMS & tokens) or bool(re.search(r'\b(?:in|at|to|from)\s+[A-Z][A-Za-z]+', text))
    has_status = bool(STATUS_TERMS & tokens)
    has_version = bool(VERSION_TERMS & tokens) or bool(re.search(r'\bv?\d{4}\.\d+(?:\.\d+)?\b', text_lower))
    has_ownership = bool(OWNERSHIP_TERMS & tokens) or 'belongs to' in text_lower or bool(re.search(r"\b[A-Z][A-Za-z0-9_-]{2,}'s\b", text))
    has_preference = bool(PREFERENCE_TERMS & tokens)
    has_attribute = bool(ATTRIBUTE_TERMS & tokens)
    has_event = bool(EVENT_TERMS & tokens)

    if claim_type == 'time':
        return 1.0 if has_time or 'birthday' in tokens else 0.5 if has_event or has_attribute else 0.0
    if claim_type == 'location':
        return 1.0 if has_location else 0.5 if has_event else 0.0
    if claim_type == 'event':
        if has_event and (has_time or has_location or has_status):
            return 1.0
        if has_event or has_time or has_location:
            return 0.5
        return 0.0
    if claim_type == 'status':
        return 1.0 if has_status else 0.5 if has_event else 0.0
    if claim_type == 'version':
        return 1.0 if has_version else 0.5 if has_status else 0.0
    if claim_type == 'ownership':
        return 1.0 if has_ownership else 0.5 if has_attribute else 0.0
    if claim_type == 'preference':
        return 1.0 if has_preference else 0.5 if has_attribute else 0.0
    if claim_type == 'attribute':
        return 1.0 if has_attribute and (result.get('subject_focused') or result.get('direct_subject_pattern')) else 0.5 if result.get('usable_anchor') else 0.0
    return 1.0 if result.get('usable_anchor') and len(result.get('match_keywords', [])) >= 2 else 0.5 if result.get('text_match_found') else 0.0


def apply_strength_caps(profile: dict, claim_type: str, query_hints: dict, result: dict,
                        proposed_strength: str, score_strength: str) -> tuple[str, str | None]:
    final_strength = proposed_strength
    reasons = []

    if profile['requires_strict_binding'] and not result.get('subject_overlap'):
        final_strength = weaker_strength(final_strength, STRENGTH_NONE)
        reasons.append('strict_binding_failed')
    elif profile['has_named_subject'] and not result.get('entity_aligned'):
        final_strength = weaker_strength(final_strength, STRENGTH_WEAK)
        reasons.append('subject_alignment_failed')

    if result.get('possible_ambient_collision') and not result.get('subject_focused'):
        final_strength = weaker_strength(final_strength, STRENGTH_WEAK)
        reasons.append('ambient_collision_cap')

    if result.get('meta_or_test_like'):
        final_strength = weaker_strength(final_strength, STRENGTH_MEDIUM)
        reasons.append('meta_or_test_cap')
        if not result.get('subject_focused'):
            final_strength = weaker_strength(final_strength, STRENGTH_WEAK)

    if not result.get('usable_anchor'):
        final_strength = weaker_strength(final_strength, STRENGTH_WEAK)
        reasons.append('unusable_anchor_cap')

    if result.get('uncertain_or_unverified'):
        final_strength = weaker_strength(final_strength, STRENGTH_WEAK)
        reasons.append('uncertain_statement_cap')

    if claim_type in {'event', 'time', 'location'} and (
        query_hints.get('weekday') or query_hints.get('explicit_date') or query_hints.get('has_relative_recent')
    ) and result.get('temporal', 0.0) < 0.70:
        final_strength = weaker_strength(final_strength, STRENGTH_MEDIUM)
        reasons.append('temporal_specificity_cap')

    if STRENGTH_VALUE.get(final_strength, 0) < STRENGTH_VALUE.get(score_strength, 0):
        return final_strength, ', '.join(sorted(set(reasons))) if reasons else 'hard_safety_cap'

    return final_strength, ', '.join(sorted(set(reasons))) if reasons else None


def enrich_result_with_score(profile: dict, query: str, claim_type: str, query_hints: dict, result: dict) -> dict:
    subject_alignment = score_subject_alignment(profile, result)
    surface = score_surface(result)
    specificity = score_specificity(query, result)
    temporal = score_temporal(claim_type, query_hints, result)
    context_focus = score_context_focus(result)
    claim_type_match = score_claim_type_match(claim_type, query, result)

    score = clamp_score(
        (subject_alignment * 0.30) +
        (surface * 0.20) +
        (specificity * 0.15) +
        (temporal * 0.15) +
        (context_focus * 0.10) +
        (claim_type_match * 0.10)
    )

    score_strength = score_to_strength(score)
    proposed_strength = stronger_strength(result['strength'], score_strength)
    result['temporal'] = clamp_score(temporal)
    final_strength, strength_cap_reason = apply_strength_caps(
        profile,
        claim_type,
        query_hints,
        result,
        proposed_strength,
        score_strength,
    )

    result['score'] = score
    result['score_breakdown'] = {
        'subject_alignment': clamp_score(subject_alignment),
        'surface': clamp_score(surface),
        'specificity': clamp_score(specificity),
        'temporal': clamp_score(temporal),
        'context_focus': clamp_score(context_focus),
        'claim_type_match': clamp_score(claim_type_match),
    }
    result['subject_alignment'] = clamp_score(subject_alignment)
    result['surface_score'] = clamp_score(surface)
    result['specificity'] = clamp_score(specificity)
    result['context_focus'] = clamp_score(context_focus)
    result['claim_type_match'] = clamp_score(claim_type_match)
    result['score_strength'] = score_strength
    result['strength'] = final_strength
    if strength_cap_reason:
        result['strength_cap_reason'] = strength_cap_reason

    return result


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
    claim_type = infer_claim_type(query, profile)
    query_hints = extract_query_temporal_hints(query)

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

    all_results = [enrich_result_with_score(profile, query, claim_type, query_hints, result) for result in all_results]

    # Sort usable anchors ahead of weak text matches, then prefer final strength,
    # composite score, subject focus, non-meta, and lower ambiguity.
    strength_order = {STRENGTH_STRONG: 0, STRENGTH_MEDIUM: 1, STRENGTH_WEAK: 2, STRENGTH_NONE: 3}
    all_results.sort(key=lambda r: (
        0 if r.get('usable_anchor') else 1,
        strength_order.get(r['strength'], 3),
        -r.get('score', 0.0),
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
    best_result = usable_results[0] if usable_results else (all_results[0] if all_results else None)
    best_strength = best_result['strength'] if best_result else STRENGTH_NONE
    best_score = best_result.get('score', 0.0) if best_result else 0.0

    borderline_medium = bool(best_result) and best_strength == STRENGTH_MEDIUM and (
        best_result.get('subject_alignment', 0.0) < 0.70 or
        best_result.get('specificity', 0.0) < 0.70 or
        best_result.get('temporal', 0.0) < 0.70 or
        bool(best_result.get('strength_cap_reason')) or
        best_score < 0.60
    )

    # Signal whether additional retrieval is needed
    needs_additional = best_strength in (STRENGTH_NONE, STRENGTH_WEAK) or borderline_medium
    suggested_types = []
    host_routing_hint = None
    next_action = 'ask_or_escalate'
    if best_strength == STRENGTH_STRONG and best_score >= 0.70 and not (
        best_result.get('possible_ambient_collision') or best_result.get('meta_or_test_like')
    ):
        next_action = 'answer_direct'
    elif best_strength == STRENGTH_MEDIUM and best_result and best_result.get('usable_anchor'):
        next_action = 'tentative_answer'

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
    elif best_strength == STRENGTH_MEDIUM and borderline_medium:
        suggested_types = ['semantic_memory', 'conversation_archive']
        host_routing_hint = (
            "use the host's semantic memory retrieval surface first; if the answer still looks only partially anchored, "
            "use the host's conversation/session retrieval surface before stating it as fact"
        )
    elif best_score < 0.45:
        suggested_types = ['semantic_memory', 'conversation_archive']
        host_routing_hint = (
            "use the host's semantic memory retrieval surface first, then the host's conversation/session retrieval surface"
        )

    return {
        'query': query,
        'claim_type': claim_type,
        'named_subjects': sorted(profile['subject_tokens']),
        'anchors_found': len(all_results),
        'usable_anchors_found': len(usable_results),
        'best_strength': best_strength,
        'best_score': best_score,
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
        'next_action': next_action,
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
