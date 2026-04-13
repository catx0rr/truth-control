---
name: truth-control
description: Final factual-claim gate and correction-capture layer for past-specific details. Use when the agent is about to state a specific prior fact, decision, quote, outcome, date, time, person, version, status, or corrected detail, or when a user is explicitly correcting a prior detail and that correction should outrank stale memory.
---

# Truth Control

Pre-output truth gate plus correction-capture support.

Use this skill when a turn may require **anchored recall before making a specific factual claim**, or when the user is explicitly correcting a prior detail.

Compatibility note:
- bundled path remains `skills/truth-recovery/`
- native tool id remains `truth_recovery`
- plugin id remains `truth-recovery`

This skill stays intentionally narrow.

It does:
- enforce output discipline for specific past-facing claims
- prioritize recent explicit corrections over stale memory
- explain anchored / tentative / unanchored output modes
- describe the two trigger paths
- point to the bundled runtime prompts for the distiller side

It does **not**:
- own the global retrieval ladder
- decide full retrieval routing policy
- replace the future memory-retrieval plugin
- act as a consolidator or reconciliator
- become one deployment's private doctrine package

## Fire conditions

Fire when any of these are true:
- about to state a specific prior fact
- about to state a prior decision, promise, quote, version, status, date, time, or named detail
- the user asks what happened earlier / before / yesterday / last time
- the agent is turning vague memory into a concrete claim
- the user corrects the agent and the correction should outrank stale memory

Do not fire on:
- generic pleasantries
- broad non-specific answers
- purely current in-session visible facts
- emotional responses with no factual specificity requirement

## Two trigger paths

### 1. Recall-risk path
Use this path when the user asks something recall-sensitive.

Flow:
- retrieval routing runs first
- then truth-control gates specificity
- then `recover` helps only if local anchors are still missing

Law:
if a claim is specific and not anchored, do not state it as fact.

### 2. Correction-capture path
Use this path when the inbound user turn itself looks like a correction.

Flow:
- inbound hook detects a correction-shaped turn
- `before_prompt_build` injects a short truth-control nudge
- `truth_recovery` writeback records a runtime correction when the correction is clear enough
- distiller stages it later for host consolidation

Law:
hooks detect, prompt hook nudges, truth-control decides.

## Modes

### Anchored
Strong support exists. Answer directly.

### Tentative
Only medium support exists. Hedge or verify.

### Unanchored
No adequate anchor exists. Do not assert the specific. Ask, retrieve, or stay general.

## Native tool surface

This plugin exposes the native `truth_recovery` tool for:
- `check`
- `recover`
- `writeback`
- `list-corrections`
- `prune-corrections`
- `mark-consolidated`

`distill` is intentionally not exposed as a native tool action in this version. It remains runtime-prompt / cron-driven.

`recover` remains a helper surface inside truth-control. It is not the headline identity anymore.

## Runtime prompts

For the distiller side, use:
- `../../runtime/create-cron-prompt.md`
- `../../runtime/correction-distiller-prompt.md`
- `../../runtime/sync-cron-delivery-prompt.md`

## Operating law

If a claim is specific and not anchored, do not state it as fact.

Recent explicit corrections outrank stale memory.
