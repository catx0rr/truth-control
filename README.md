# Truth Control Plugin

Compatibility surfaces in this phase:
- package name: `truth-control`
- plugin id: `truth-recovery`
- native tool: `truth_recovery`
- bundled skill path: `skills/truth-recovery/`

This is a **soft rename** from truth-recovery to **truth-control**.
The behavior is being widened into a narrow control-plane package, but runtime ids stay compatibility-safe for now.

## What this plugin is

Standalone OpenClaw plugin for **turn-level truth control**.

It packages:
- native plugin runtime
- bundled skill
- bundled scripts
- bundled runtime prompts
- bundled references

It still depends on:
- Python 3 on the Gateway host
- host memory surfaces under the active workspace
- host cron support for the distiller side

## What this plugin owns

This plugin stays intentionally narrow.

It owns:
- pre-answer truth gating for specific factual claims
- correction-intent trigger support for inbound turns
- prompt-time truth nudges
- correction precedence support
- correction register writeback support
- bundled skill guidance
- bundled distiller/runtime prompts and helpers

It does **not** own:
- the future global memory-retrieval routing law
- the full retrieval ladder
- semantic, continuity, relational, or forensic routing policy
- reconciliation logic
- host memory consolidation policy

## Why it exists

Agents sometimes assert specifics they cannot properly support, especially after cold starts, compaction, or when a recent correction has not propagated into durable memory yet.

This plugin enforces a narrow rule:
if a claim is specific and cannot be adequately anchored, the agent should not assert it as fact.
It should retrieve, ask, or stay general.

It also adds a missing reflex:
explicit user corrections should not depend entirely on the model remembering, unprompted, to record them.

## Core functions

This package now frames three narrow truth-control functions:
1. **Pre-answer truth gate**: check whether a specific claim is anchored strongly enough to be stated
2. **Correction capture support**: detect correction-shaped turns, nudge the current turn, and allow immediate correction-register writeback
3. **Distiller bridge**: stage runtime corrections into consolidator-visible daily memory surfaces for later host absorption

`recover` remains part of the package, but it is a helper surface inside truth-control, not the headline identity.

## Two trigger paths

### 1. Recall-risk path
Used when the user asks something recall-sensitive.

Flow:
- host retrieval routing runs first
- truth-control gates specificity
- `recover` helps only when local anchors are still missing

### 2. Correction-capture path
Used when the inbound user turn itself looks like a correction.

Flow:
- inbound correction detector marks the turn
- `before_prompt_build` injects a short truth-control nudge
- structured explicit corrections may be written immediately to the runtime correction register
- later distiller flow stages them for host consolidation

## Architecture boundary

Memory stack split:
- **future memory-retrieval plugin**: retrieval routing law, lightest-correct-layer reminder, full ladder ownership
- **this plugin**: local truth-risk reflex, answer-entitlement discipline, correction precedence, correction-trigger support, and final factual-claim gate behavior

Retrieval routing is still upstream of this plugin.
truth-control is the final factual-claim gate, not the global retrieval router.

## Hook behavior

This plugin uses a split hook design:
- inbound turn detection
- prompt-time nudge
- centralized truth-control logic

### Inbound correction trigger
The public internal hook docs describe this role as `message:preprocessed`.
On the current installed SDK/runtime, this package implements the same role on `before_dispatch` as the practical prepared-turn interception point, because it exposes the prepared body plus `sessionKey` needed for transient handoff.
This is an SDK/version-specific compatibility choice and should be revalidated when OpenClaw is upgraded.

That detector is implemented in the plugin runtime, not as a separate Python script in this version.

Its job is intentionally narrow:
- classify the prepared inbound turn as `none`, `possible_correction`, or `explicit_correction`
- keep the detector conservative
- only auto-record when the correction is explicit **and** structured enough to extract a safe replacement pair
- pass a short-lived session-scoped signal to the matching agent turn

It does **not**:
- write to durable memory
- act as a retriever/router
- consolidate corrections
- replace writeback logic

### Prompt-time nudge
This plugin registers a narrow `before_prompt_build` hook.

It injects short guidance only when one of these is true:
- the latest user turn appears recall-sensitive
- the current turn was tagged as correction-shaped by the inbound detector

The guidance remains intentionally short.
It does not inject the full retrieval ladder or a giant rulebook.

## Correction precedence and lifecycle

Recent explicit user corrections outrank stale memory, repeated ambient associations, and durable memory that has not been updated yet.

Operationally:
- inbound trigger detects correction-shaped turns
- structured explicit corrections may be written to the runtime correction register immediately
- `check` consults recent corrections before permitting a specific factual claim
- `distill` stages corrections into daily memory surfaces
- later host consolidators decide durable absorption and reconciliation

Important state distinction:
- **recorded** means present in the runtime correction register
- **staged** means exported into a consolidator-visible memory surface
- **consolidated** means a host process confirmed durable absorption

truth-control does not perform final consolidation or reconciliation itself.

## Native tool

Compatibility tool id remains `truth_recovery` in this phase.

Actions:
- `check`
- `recover`
- `writeback`
- `list-corrections`
- `prune-corrections`
- `mark-consolidated`

### Distill action decision

`distill` is **not** exposed as a native tool action in this version.

`distill` remains runtime-only and cron/manual driven so the plugin does not become a broad always-available write path for memory staging.

## Bundled skill

The plugin ships a bundled skill at:
- `skills/truth-recovery/SKILL.md`

Bundle path is kept for compatibility in this phase, even though the skill now teaches the truth-control framing.

Bundled skill loading is declared via `"skills": ["skills"]` in `openclaw.plugin.json`.

## Runtime dependencies and surfaces

Telemetry root resolution for scripts/docs in this package:
- explicit `--telemetry-dir` / explicit output path wins
- then `TRUTH_CONTROL_TELEMETRY_ROOT`
- then `TRUTH_RECOVERY_TELEMETRY_ROOT`
- then `~/.openclaw/telemetry` as fallback example/default on a typical local install


This plugin depends on:
- **Python 3** on the Gateway host
- bundled worker scripts under `scripts/`
- workspace runtime files under `<workspace>/runtime/...`
- workspace memory files under `<workspace>/memory/...`
- telemetry under `<telemetry-root>/...` for the distiller/reporting side

Operator-level surface split:
- **workspace runtime** under `<workspace>/runtime/...` holds live correction state and related local runtime files
- **workspace memory** under `<workspace>/memory/...` holds daily staging targets for later host consolidation
- **telemetry root** under `<telemetry-root>/...` holds distiller logs and report artifacts

## Config

Manifest is the canonical config schema source:
- `openclaw.plugin.json`

Config path remains:
- `plugins.entries.truth-recovery.config`

Supported fields:
- `paths.workspaceRoot`
- `paths.correctionsFile`
- `paths.pendingFile`
- `paths.memoryFile`
- `paths.dailyLogDir`
- `pythonBinary`
- `enablePromptGuidance`
- `enableCorrectionCapture`
- `enableExplicitCorrectionAutoWriteback`
- `correctionSignalTtlMs`
- `defaultCheckPending`

## Install story

This package can be loaded locally in two ways:
- preferred managed install via `openclaw plugins install /absolute/path/to/truth-recovery-plugin`
- manual local loading by placing the package under `~/.openclaw/extensions/`

Installing this single plugin package gives you:
- plugin runtime
- bundled skill
- bundled scripts
- bundled references
- bundled runtime prompts

Operational setup still uses:
- `INSTALL.md`
- `runtime/create-cron-prompt.md`
- `runtime/correction-distiller-prompt.md`
- `runtime/sync-cron-delivery-prompt.md`
- `scripts/init_harness_config.py`

## Quick verification

After install and gateway restart, verify:
- plugin loads successfully
- bundled skill is visible
- native `truth_recovery` tool is available
- runtime prompts exist under `runtime/`
- Python scripts are present under `scripts/`
- explicit structured correction turns create a transient turn signal
- benign non-corrections do not trigger writeback reflex too often

## Status

This package is staged for upstream review first.
Compatibility ids are intentionally preserved in this phase.
