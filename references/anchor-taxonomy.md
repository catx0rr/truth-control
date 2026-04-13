# Anchor Taxonomy — Detailed Classification

How to classify the strength of an anchor supporting a specific factual claim.

---

## Strength Classes

### Strong — supports confident specifics

The agent can state the fact directly.

| Anchor Type | Example | Why Strong |
|-------------|---------|------------|
| Explicit statement in current session | User just said "the meeting is at 3 PM" | Direct, current, unambiguous |
| Explicit recent user correction | User said "no, it was Laguna not Batangas" | User authority + recency |
| Exact retrieval with provenance | Semantic search returned entry with date and source file | Traceable to a specific event |
| Current external authoritative source | API returned live data, tool output verified | External ground truth |
| Deterministic tool result in session | `ls` output shows the file exists right now | Observable, repeatable |

### Medium — supports careful specifics

The agent can state the fact but should hedge or verify.

| Anchor Type | Example | Why Medium |
|-------------|---------|------------|
| Durable memory entry (stable fact) | MEMORY.md says "user works at Company X" | Stable but could be outdated |
| Repeated scoped memory with provenance | Same fact in 3 different daily logs | Consistent but not explicitly confirmed this session |
| Pending-action journal state | Journal says "deploy initiated at 10:00" | Recorded state but outcome unknown |
| Conversation archive match | Transcript or archive excerpt returned | Verbatim but potentially old context |

### Weak — cannot support confident specifics alone

The agent must NOT assert the specific. Must retrieve, ask, or generalize.

| Anchor Type | Example | Why Weak |
|-------------|---------|----------|
| Ambient relationship memory | "I think they usually go to Batangas" | Pattern, not fact |
| Old recalled association | "Months ago they mentioned something about X" | Stale, no recent confirmation |
| Soft preference memory | "They seem to prefer Python" | Inference, not statement |
| Inference from similar situations | "Last time this happened, they did Y" | Analogical, not specific |

### None — no anchor

No evidence found. The agent is guessing.

**Output rule:** Ask or answer generally. Never assert.

---

## Decision Matrix

| Claim Type | Strong Anchor | Medium Anchor | Weak/None |
|------------|---------------|---------------|-----------|
| Location | "You went to Laguna" | "I believe you went to Laguna — is that right?" | "How was the outing?" |
| Date/Time | "The meeting was at 3 PM" | "I think it was scheduled for 3 PM?" | "When was the meeting?" |
| Person | "Sir Alex reviewed it" | "I believe Alex was involved — correct?" | "Who handled the review?" |
| Prior decision | "We decided on ₱5,000/month" | "If I recall, the pricing was around ₱5,000?" | "What pricing did we settle on?" |
| Prior action outcome | "The deploy succeeded" | "I think the deploy went through — did it?" | "How did the deploy go?" |

---

## Correction Priority Rule

When a correction exists in `recent-corrections.jsonl`, it **always** takes priority:

```
Correction for "Batangas" → "Laguna" exists

Agent wants to say "How was Batangas?"
→ Correction found → old value matches → BLOCK
→ Use corrected value or ask generically

Agent wants to say "How was Laguna?"
→ Correction found → corrected value matches → PERMIT (strong anchor)
```

Even if MEMORY.md still says the old value (not yet consolidated), the correction register wins.

---

## Edge Cases

### Multiple anchors at different strengths

Use the strongest anchor. If strong + weak conflict, strong wins. If two medium anchors agree, treat as strong.

### Anchor is strong but stale

A strong anchor degrades over time:
- Tool output from current session → strong
- Tool output from yesterday's session → medium
- Tool output from 2 weeks ago → weak

### User corrects a correction

The newest correction wins. `writeback.py` appends; `check.py` reads in order and uses the latest matching entry.

### Claim spans multiple specifics

"You went to Batangas on Tuesday at 3 PM" — each specific (location, day, time) needs its own anchor. If any one is unanchored, either drop that specific or ask about it.

### Agent is uncertain whether claim is specific

When in doubt, classify as specific. False positives (unnecessary gate checks) are cheap. False negatives (unanchored assertions) erode trust.

---

## Scope Categories

Used in the `scope` field of corrections and for claim classification:

| Scope | Description | Examples |
|-------|-------------|---------|
| `location` | Physical place or venue | "Batangas", "the office", "Starbucks BGC" |
| `date` | Calendar date | "March 15", "last Tuesday", "yesterday" |
| `time` | Clock time | "3 PM", "morning", "after lunch" |
| `person` | Individual's name or role | "Sir Alex", "the dentist", "your cousin" |
| `event` | An occurrence or activity | "the outing", "the meeting", "the deploy" |
| `decision` | A choice that was made | "pricing at ₱5K", "using n8n", "the pilot deal" |
| `quantity` | A number or amount | "₱5,000", "8 agents", "3 months" |
| `preference` | User's stated preference | "prefers Sonnet", "wants English output" |
| `status` | State of something | "completed", "in progress", "blocked" |
| `other` | Anything else | Catch-all |
