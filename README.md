# Truth Control Claw

## Compatibility identity

This package is in a transitional naming phase.

Operator-facing package name:
- package name: `truth-control-claw`

Runtime compatibility ids still preserved in this phase:
- plugin id: `truth-recovery`
- native tool: `truth_recovery`
- bundled skill path: `skills/truth-recovery/`
- skill frontmatter name: `truth-control`

Why they differ right now:
- operators install and refer to the package as **truth-control-claw**
- runtime ids stay on the old compatibility surface so existing plugin wiring, tool calls, and bundle loading do not break during the transition
- the package identity has moved first, while the runtime surface is intentionally lagging behind for compatibility

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

## Control-plane process flow

```text
Recall-risk path
----------------
User asks recall-sensitive question
        |
        v
Host retrieval routing runs first
(lightest correct layer first)
        |
        v
before_prompt_build
inject short truth-control nudge
only when recall risk is present
        |
        v
Agent turn / host may call truth_recovery.check
        |
        +--> correction conflict found
        |        |
        |        v
        |   use corrected value / override stale recall
        |
        +--> still weakly anchored
        |        |
        |        v
        |   truth_recovery.recover
        |        |
        |        +--> anchor found -> answer with anchor
        |        |
        |        `--> no anchor -> ask, retrieve more, or stay general
        |
        `--> already anchored -> answer directly


Correction-capture path
-----------------------
Inbound user turn
        |
        v
before_dispatch
classify: none / possible_correction / explicit_correction
        |
        +--> explicit + structured + safe enough
        |        |
        |        v
        |   writeback to hot correction register
        |   (authoritative recent-correction surface)
        |
        `--> set transient session signal
                 |
                 v
          before_prompt_build
          inject correction-aware nudge
                 |
                 v
          agent answers using corrected value first
                 |
                 v
          later distiller stages corrections to daily memory
                 |
                 v
          host consolidation / reconciliation happens later

Authority rule
--------------
Transient session signal -> shapes the matching turn only
Hot correction register  -> source of truth for recent corrections
Daily memory / durable memory -> later staged and consolidated layers
```

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
On the currently tested SDK/runtime, this package uses `before_dispatch` as the practical prepared-turn interception point because it exposes the prepared body plus `sessionKey` needed for transient handoff.
This is an SDK/version-specific compatibility choice and should be revalidated on OpenClaw upgrades.

That detector is implemented in the plugin runtime, not as a separate Python script in this version.

Its job is intentionally narrow:
- classify the prepared inbound turn as `none`, `possible_correction`, or `explicit_correction`
- keep the detector conservative
- support a small structured correction family, including forms like `not X, but Y`, `it's X, not Y`, `should be X not Y`, `I mean X not Y`, and guarded interruption forms
- attach machine-readable `capture_confidence` and `capture_reason` to structured correction candidates
- only auto-record when the correction is explicit **and** structured enough to extract a safe replacement pair
- use confidence-tiered auto-write behavior: `high` may auto-write directly, `medium` needs extra guard signals, `low` stays candidate-only by default
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
- recorded correction entries may include `capture_confidence` and `capture_reason` for later debugging and tuning
- the transient correction signal helps shape the matching turn, but the hot correction register is the authoritative recent-correction surface
- `check` consults recent corrections before permitting a specific factual claim
- `check` now emits a host-facing `next_action` control signal such as `answer_direct`, `call_recover`, `use_correction_override`, or `ask_or_stay_general`
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

Key action outputs in this strengthening pass:
- `check` still returns the recommendation mode, but now also returns `next_action` so the host can react more deterministically
- `recover` now returns a deterministic composite `score`, `score_breakdown`, `score_strength`, optional `strength_cap_reason`, a host-facing `next_action`, and an optional `host_routing_hint` string for host-neutral operator guidance
- `writeback` can persist `capture_confidence` and `capture_reason` when a structured correction was captured by the plugin runtime

## Deterministic scoring model (v1.1)

`recover.py` now adds a deterministic numeric scoring layer on top of the existing honesty and eligibility gates.

Important boundary:
- scoring ranks already-retrieved candidates
- scoring does **not** replace retrieval
- scoring does **not** override correction precedence
- scoring does **not** bypass hard safety gates such as failed subject alignment, ambient collision risk, unusable anchors, or strict-binding failure

Composite score:

```text
score =
  (subject_alignment * 0.30) +
  (surface * 0.20) +
  (specificity * 0.15) +
  (temporal * 0.15) +
  (context_focus * 0.10) +
  (claim_type_match * 0.10)
```

Signals:
- `subject_alignment` 0.30, is the candidate actually about the named subject
- `surface` 0.20, how trustworthy the source surface is
- `specificity` 0.15, how concrete the detail is
- `temporal` 0.15, whether the timing is plausible enough
- `context_focus` 0.10, whether the line looks like real content instead of meta or diagnostic noise
- `claim_type_match` 0.10, quantized match between candidate content and claim type

Surface trust values:
- `recent_corrections` = 1.0
- `pending_actions` = 0.90
- `scoped_daily_memory` = 0.70
- `durable_memory` = 0.60
- `procedural_memory` = 0.50

Score bands:
- `strong` = `>= 0.70`
- `medium` = `0.45–0.69`
- `weak` = `0.15–0.44`
- `none` = `< 0.15`

Hard-cap examples:
- strict subject binding failure can cap the result to `none`
- ambient collision without real subject focus can cap the result to `weak`
- unusable anchors do not get rescued by score alone
- meta or diagnostic lines do not get promoted just because they share tokens

Result fields added by `recover` in v1.1:
- `score`
- `score_breakdown`
- `score_strength`
- `strength_cap_reason` when a hard safety cap applied
- `best_score` on the top-level recover result
- `next_action` on the top-level recover result

Recovery routing effect in v1.2:
- `answer_direct` now follows the final strong anchored outcome more directly, instead of re-imposing a separate score cliff after strength resolution
- `tentative_answer` when there is a usable medium-strength anchor
- `ask_or_escalate` when the best result is weak, unanchored, or still too borderline
- `host_routing_hint` now fires not only for `none`, but also for weak results and borderline medium results that still need stronger host retrieval before being stated as fact

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
- then `~/.openclaw/telemetry` as a common local-host fallback example, not a required package path


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
- preferred managed install via `openclaw plugins install /absolute/path/to/truth-control-claw`
- manual local loading by placing the package under `~/.openclaw/extensions/`

Example manual local folder shape:
- `~/.openclaw/extensions/truth-control-claw/`

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
- recorded structured corrections include `capture_confidence` / `capture_reason` when applicable
- high-confidence structured corrections may auto-write immediately
- bare low-confidence forms do not create noisy automatic writes by default
- benign non-corrections do not trigger writeback reflex too often

## General regression scenarios

When validating this package, use generalized fixture-style checks instead of personal or environment-specific examples.

Recommended baseline scenarios:
- ambient false positive, a vague preference-style query with no real anchor should stay unanchored
- attribute fact, a concrete subject-plus-attribute line should anchor cleanly
- birthday fact, a concrete subject-plus-date fact should anchor cleanly
- correction conflict, a claim using an old corrected value should route to correction override behavior
- meta or test noise line, diagnostic or validation residue should not outrank a real factual line just because tokens overlap
- date-specific event query, a partially related line should stay tentative and emit host escalation guidance when the temporal slice is still under-anchored

For repeatable validation, the next quality step is:
- a tiny `test-fixtures/` folder
- a repeatable `check` / `recover` regression script
- fixture coverage for the six baseline scenarios above

## License

Licensed under the MIT License.
