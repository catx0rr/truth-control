# Truth Control Plugin — Installation Guide

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

Install one plugin package and get the full truth-control package surface:
- native plugin runtime
- bundled skill
- bundled scripts
- bundled references
- bundled runtime prompts

This guide covers plugin installation plus the runtime surfaces needed by the correction register and distiller side.

---

## 1. Install the plugin package

Because this package is not part of the official OpenClaw plugin list, there are two supported local install paths.

### Option A, preferred: managed local install

```bash
openclaw plugins install /absolute/path/to/truth-control-claw
openclaw gateway restart
```

Use this when you want OpenClaw to manage the install in the normal plugin flow.

### Option B: manual local loading from extensions

Copy or place the plugin directory under:

```text
~/.openclaw/extensions/
```

Example shape:

```text
~/.openclaw/extensions/truth-control-claw/
```

Then restart the gateway:

```bash
openclaw gateway restart
```

Use this when you want the plugin loaded locally from the standard extensions discovery path instead of installing it through `openclaw plugins install`.

After installation or manual placement, OpenClaw should load:
- the native plugin runtime from `index.js`
- the bundled skill root under `skills/`
- bundled companion assets under `scripts/`, `references/`, and `runtime/`

Naming note:
- operators install the package as `truth-control-claw`
- compatibility runtime ids remain `truth-recovery` and `truth_recovery` in this phase
- the bundled skill directory remains `skills/truth-recovery/` in this phase

---

## 2. Runtime dependencies

Required on the Gateway host:
- Python 3
- plugin files intact under the installed plugin root

Operational surfaces used after install:
- `<workspace>/runtime/truth-recovery/recent-corrections.jsonl`
- optional `<workspace>/runtime/pending-actions/pending-actions.jsonl`
- optional `<workspace>/runtime/harness-state/harness-state.json`
- `<workspace>/memory/`
- `<telemetry-root>/truth-recovery/`

The plugin runtime itself does not create every operational surface automatically. Use the setup steps below.

---

## 3. Create runtime and telemetry directories

### Workspace runtime

```bash
mkdir -p <workspace>/runtime/truth-recovery
mkdir -p <workspace>/memory
```

Optional shared runtime surfaces:

```bash
mkdir -p <workspace>/runtime/pending-actions
mkdir -p <workspace>/runtime/harness-state
mkdir -p <workspace>/memory/corrections
```

### Telemetry

Choose a telemetry root explicitly when packaging for reuse.
Resolution order used by the helper scripts in this package:
- explicit `--telemetry-dir`
- `TRUTH_CONTROL_TELEMETRY_ROOT`
- `TRUTH_RECOVERY_TELEMETRY_ROOT`
- `~/.openclaw/telemetry` as a common local-host fallback example, not a required package path

Example:

```bash
mkdir -p <telemetry-root>/truth-recovery/distiller
mkdir -p <telemetry-root>/truth-recovery/latest-report
```

---

## 4. Create required files

Required correction register:

```bash
touch <workspace>/runtime/truth-recovery/recent-corrections.jsonl
```

Optional shared files:

```bash
touch <workspace>/runtime/pending-actions/pending-actions.jsonl
```

Optional harness-state init:

```bash
python3 <installed-plugin-root>/scripts/init_harness_config.py \
  --file <workspace>/runtime/harness-state/harness-state.json
```

Enable nightly and hourly report toggles only if wanted.

---

## 5. Verify the standalone package surfaces

Confirm the installed plugin root contains:

```text
package.json
openclaw.plugin.json
index.js
README.md
INSTALL.md
scripts/
references/
runtime/
skills/truth-recovery/SKILL.md
```

---

## 6. Verify the native tool and trigger split

After install and restart, verify the plugin is listed and enabled, then test the native tool with a simple check action through the agent.

Expected native tool actions:
- `check`
- `recover`
- `writeback`
- `list-corrections`
- `prune-corrections`
- `mark-consolidated`

Strengthening-pass result notes:
- `check` now returns `next_action` to make the host control signal more concrete
- `recover` now returns deterministic `score`, `score_breakdown`, `score_strength`, optional `strength_cap_reason`, `next_action`, and optional `host_routing_hint` alongside portable `suggested_surface_types`
- `writeback` may persist `capture_confidence` and `capture_reason` for structured corrections
- the transient correction signal helps shape the next turn, but the hot correction register remains the authoritative recent-correction surface

`distill` remains runtime-prompt / cron-driven in this package. It is not exposed as a native tool action.

Also verify the control-plane split:
- recall-sensitive turns receive the short truth-control gate nudge
- correction-shaped turns create a **transient, session-scoped** signal for the matching turn
- high-confidence structured corrections may auto-record immediately
- medium-confidence structured corrections only auto-record when extra guard conditions are present
- low-confidence bare forms stay candidate-only by default
- durable staging still happens later through distiller flow

Note:
- the inbound correction detector is currently implemented in plugin runtime code, not as a separate `detect_correction.py` script
- on the currently tested SDK/runtime, `before_dispatch` is used as the practical prepared-turn interception point for inbound correction detection; revalidate this on OpenClaw upgrades
- the detector is conservative by design
- structured correction capture is confidence-tiered, so wider phrasing coverage does not automatically mean wider auto-write behavior

---

## 7. Distiller setup flow

For the distiller side, use the bundled runtime prompts:
- `runtime/create-cron-prompt.md`
- `runtime/correction-distiller-prompt.md`
- `runtime/sync-cron-delivery-prompt.md`

This keeps the plugin standalone while preserving the narrow boundary:
- native plugin runtime handles trigger + nudge + tool
- bundled runtime prompts handle cron/manual distiller procedure

---

## 8. Notes

- This plugin is not the global retrieval router.
- This plugin should not inject the full retrieval ladder.
- This package now presents as truth-control. Compatibility ids remain truth-recovery for now.
- If Python 3 is missing, native tool calls and explicit correction auto-writeback will fail.
- If the plugin files are incomplete, bundled skill and distiller support will be incomplete too.
- If you inspect the correction register after structured capture, entries may now include `capture_confidence` and `capture_reason` for observability.
