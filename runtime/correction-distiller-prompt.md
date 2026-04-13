# Truth-Recovery — Correction Distiller Runtime Prompt

Working directory: the workspace root.
This file lives inside `runtime/`. Resolve the absolute path of the parent of `runtime/` and use it as `SKILL_ROOT`.

**Hybrid rule:** Scripts handle all staging, deduplication, and reporting. LLM orchestrates the steps and interprets results.

**This prompt stages runtime corrections into consolidator-visible memory surfaces.**
**It does NOT consolidate, promote, or write to durable memory files.**

---

## Step 0: Resolve Paths and Config

1. Resolve the absolute path of the parent of `runtime/` as `SKILL_ROOT`
2. Use the current working directory as `WORKSPACE_ROOT`
3. Resolve `TELEMETRY_ROOT` = the chosen telemetry root
4. Telemetry root resolution order: explicit operator choice, then `TRUTH_CONTROL_TELEMETRY_ROOT`, then `TRUTH_RECOVERY_TELEMETRY_ROOT`, then `~/.openclaw/telemetry` as a local-install fallback example
5. Do not assume a hardcoded skill path
6. Do not assume a hardcoded workspace path

Determine the run mode from the cron message:
- `Mode: hourly` → hourly sweep
- `Mode: nightly-preconsolidation` → nightly sweep with report

### Read reporting config

Read `WORKSPACE_ROOT/runtime/harness-state/harness-state.json` if it exists.

Extract from the `truthRecovery` namespace:
- `truthRecovery.reporting.nightlyChatReport` (default: `false` if missing)
- `truthRecovery.reporting.sendHourlyChatReport` (default: `false` if missing)

If the file does not exist, or `truthRecovery` / `truthRecovery.reporting` is missing, default both to `false`. Do not error.

**Reporting law:**
- JSONL telemetry is **always written** regardless of these flags
- Nightly markdown report file is **always generated** regardless of these flags
- These flags indicate whether report content is **eligible** for chat delivery

**Delivery ownership:** This prompt does not own cron delivery mode. Whether report content actually reaches chat depends on the cron job's delivery configuration (`--announce` vs `--no-deliver`), not on prompt-level toggles alone. To change delivery behavior, run `SKILL_ROOT/runtime/sync-cron-delivery-prompt.md`.

---

## Step 1: Run the Distiller [SCRIPT]

```bash
python3 SKILL_ROOT/scripts/distill.py \
  --corrections-file WORKSPACE_ROOT/runtime/truth-recovery/recent-corrections.jsonl \
  --memory-dir WORKSPACE_ROOT/memory
```

Read the JSON output. Record:
- `corrections_loaded`
- `corrections_unstaged`
- `corrections_staged`
- `would_stage`
- `dry_run` (should be `false`)

If the command fails, record the error and continue to Step 2.

---

## Step 2: Append Run Record [SCRIPT]

Use `append_run.py` to write a structured run record to the telemetry root. Do **not** use raw `echo` — the script handles JSON escaping, timestamp triple generation, daily sharding, and consistent schema.

**If Step 1 succeeded:**

```bash
python3 SKILL_ROOT/scripts/append_run.py \
  --telemetry-dir TELEMETRY_ROOT \
  --mode <hourly or nightly-preconsolidation> \
  --success \
  --corrections-loaded <N> \
  --corrections-unstaged <N> \
  --corrections-staged <N> \
  --would-stage <N>
```

Fill `<N>` values from the distill.py JSON output in Step 1.

**If Step 1 failed:**

```bash
python3 SKILL_ROOT/scripts/append_run.py \
  --telemetry-dir TELEMETRY_ROOT \
  --mode <hourly or nightly-preconsolidation> \
  --error "<error message>"
```

The script writes to a daily-sharded file at:
`TELEMETRY_ROOT/truth-recovery/distiller/distiller-runs-YYYY-MM-DD.jsonl`

`TELEMETRY_ROOT` must be resolved first. Do not assume a single hardcoded host path.

---

## Step 3: Reporting [SCRIPT + CONFIG]

### Hourly mode

**Always:** Steps 1 and 2 above (distill + JSONL log).

**If `sendHourlyChatReport == true`:**

Generate the short hourly report:

```bash
python3 SKILL_ROOT/scripts/report_runs.py \
  --telemetry-dir TELEMETRY_ROOT \
  --mode hourly \
  --dry-run
```

The script emits the exact hourly report body. Send that exact text to chat with no added bullets, summary, explanation, or rewritten phrasing.

**If `sendHourlyChatReport == false`:**

No chat output. The JSONL log is sufficient.

### Nightly mode

**Always:** Steps 1 and 2 above (distill + JSONL log).

**Always generate the nightly markdown report file:**

```bash
python3 SKILL_ROOT/scripts/report_runs.py \
  --telemetry-dir TELEMETRY_ROOT \
  --mode nightly
```

This writes to: `TELEMETRY_ROOT/truth-recovery/latest-report/nightly-distill-report.md`

**If `nightlyChatReport == true`:**

Read the generated report file and send its exact contents to chat with no added bullets, summary, explanation, or rewritten phrasing.

**If `nightlyChatReport == false`:**

Keep the report file only. No chat output.

### Exact report templates

`report_runs.py` owns the wording. Do not improvise alternate phrasing.

Hourly template:

```text
⏳ Truth-Recovery Distiller — Hourly Consolidation

Hourly run: <SUCCESS or FAILED>
Local Time: <local timezone-aware ISO 8601 with offset>
UTC Time: <UTC ISO 8601 with Z>
Timezone: <IANA timezone if known, else local offset label>
```

Nightly template:

```text
⌛ Truth-Recovery Distiller — Nightly Pre-Consolidation

Nightly run: <SUCCESS or FAILED>
Local Time: <local timezone-aware ISO 8601 with offset>
UTC Time: <UTC ISO 8601 with Z>
Timezone: <IANA timezone if known, else local offset label>

Hourly sweeps since last nightly run:
- Fired: <count>
- Success: <count>
- Failed: <count>

Nightly staging result:
- Corrections loaded: <count>
- Unstaged before run: <count or unknown>
- Staged tonight: <count>

Status:
- <short status line 1>
- <optional short status line 2>
```

Nightly success with nothing staged:

```text
⌛ Truth-Recovery Distiller — Nightly Pre-Consolidation

Nightly run: SUCCESS
Local Time: <local timezone-aware ISO 8601 with offset>
UTC Time: <UTC ISO 8601 with Z>
Timezone: <IANA timezone if known, else local offset label>

Hourly sweeps since last nightly run:
- Fired: <count>
- Success: <count>
- Failed: <count>

Nightly staging result:
- Corrections loaded: 0
- Unstaged before run: 0
- Staged tonight: 0

Status:
- Distiller bridge ran before consolidation
- Nothing needed staging
```

Nightly failed:

```text
⌛ Truth-Recovery Distiller — Nightly Pre-Consolidation

Nightly run: FAILED
Local Time: <local timezone-aware ISO 8601 with offset>
UTC Time: <UTC ISO 8601 with Z>
Timezone: <IANA timezone if known, else local offset label>

Hourly sweeps since last nightly run:
- Fired: <count>
- Success: <count>
- Failed: <count>

Nightly staging result:
- Corrections loaded: 0
- Unstaged before run: unknown
- Staged tonight: 0

Status:
- Nightly distiller failed before consolidation
- Last error: <error text>
```

---

## Mode Behavior Summary

| Mode | Distill | JSONL log | Markdown report | Chat eligible |
|------|---------|-----------|-----------------|---------------|
| `hourly` | Always | Always | No | Only if `sendHourlyChatReport == true` |
| `nightly-preconsolidation` | Always | Always | Always | Only if `nightlyChatReport == true` |

**Note:** "Chat eligible" means the prompt generates report content. Actual chat delivery depends on the cron job's delivery mode.

---

## Path Summary

| Surface | Path | Type |
|---------|------|------|
| Hot correction register | `WORKSPACE_ROOT/runtime/truth-recovery/recent-corrections.jsonl` | Live state |
| Harness state (config) | `WORKSPACE_ROOT/runtime/harness-state/harness-state.json` | Live state |
| Daily memory staging | `WORKSPACE_ROOT/memory/YYYY-MM-DD.md` | Staging target |
| Distiller run logs | `TELEMETRY_ROOT/truth-recovery/distiller/distiller-runs-YYYY-MM-DD.jsonl` | Telemetry |
| Nightly report | `TELEMETRY_ROOT/truth-recovery/latest-report/nightly-distill-report.md` | Telemetry |

---

## Safety Rules

1. This prompt does NOT write to durable memory files — that is the host consolidator's job
2. This prompt does NOT set `consolidated: true` — only host-confirmed durable absorption does that
3. This prompt only stages corrections and logs the result
4. If the distiller reports 0 unstaged corrections, that is a normal healthy state — do not treat it as an error
5. Do not read or stage `runtime/pending-actions/pending-actions.jsonl` unless explicitly requested
6. Telemetry goes to `TELEMETRY_ROOT`, not to the workspace runtime directory
7. Reporting toggles control chat content eligibility — actual delivery depends on cron job configuration
8. To change cron delivery mode, run `SKILL_ROOT/runtime/sync-cron-delivery-prompt.md`
