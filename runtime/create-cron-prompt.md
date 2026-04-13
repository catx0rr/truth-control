# Truth-Recovery — One-Time Cron Creation

This prompt is executed **once** to create two recurring distiller crons.
After execution, this file is not used again — the crons run `runtime/correction-distiller-prompt.md` directly.

---

## Rules

- Run this prompt exactly once per installation.
- Do not embed distiller logic here.
- Do not leave `SKILL_ROOT` or any placeholder literal in the created cron payloads.
- Replace all path references with resolved absolute paths before creating the crons.
- Do not improvise. Follow every step in order.
- Do not guess the cron creation syntax — use the exact commands shown below.

---

## Step 1: Resolve SKILL_ROOT

This file lives inside `runtime/`. The skill root is the parent directory.

```
SKILL_ROOT = <absolute path of the parent directory of runtime/>
```

Verify it:

```bash
ls "$SKILL_ROOT/SKILL.md"
```

If the file does not exist, stop. The skill is not installed correctly.

---

## Step 2: Verify correction-distiller-prompt.md Exists

```bash
ls "$SKILL_ROOT/runtime/correction-distiller-prompt.md"
```

If the file does not exist, stop. The skill installation is incomplete.

---

## Step 3: Resolve Absolute Paths and Timezone

Resolve four values before creating crons:

```
PROMPT_PATH    = <resolved absolute path to $SKILL_ROOT/runtime/correction-distiller-prompt.md>
WORKSPACE_PATH = <resolved absolute path to the active workspace root>
TELEMETRY_PATH = <resolved absolute path to the chosen telemetry root>
TIMEZONE       = <IANA timezone of the host/operator, e.g. Asia/Manila>
```

Telemetry root resolution guidance:
- explicit operator choice is best
- otherwise use `TRUTH_CONTROL_TELEMETRY_ROOT`
- otherwise use `TRUTH_RECOVERY_TELEMETRY_ROOT`
- otherwise `~/.openclaw/telemetry` is the local-install fallback example

All four must be fully resolved — no `~`, no `$SKILL_ROOT`, no `$HOME`, no placeholders.

**Timezone rule:** If the operator's timezone is known, use it. If not, determine the system timezone. Cron schedules fire at wall-clock time in the specified timezone. Without `--tz`, OpenClaw uses the gateway host timezone.

---

## Step 4: Read Reporting Config

Read `WORKSPACE_PATH/runtime/harness-state/harness-state.json` if it exists.

Extract:
- `truthRecovery.reporting.sendHourlyChatReport` (default: `false` if missing)
- `truthRecovery.reporting.nightlyChatReport` (default: `false` if missing)
- `truthRecovery.reporting.delivery.to` (default: `null` if missing)
- `truthRecovery.reporting.delivery.channel` (default: `"last"` if missing)

If the file does not exist, or `truthRecovery` / `truthRecovery.reporting` is missing, use the defaults. Do not error.

If the file does not exist or any key is missing, use the defaults. Do not error.

### Resolve delivery route

If either toggle is `true`, resolve the announce route in this strict order:

**A. Explicit target (highest confidence)**

If `truthRecovery.reporting.delivery.to` is non-null and non-empty → use it as the explicit announce target. This is unambiguous.

**B. Last-route reuse (conditional)**

Else if `truthRecovery.reporting.delivery.channel == "last"` → attempt last-route reuse. But first verify it is actually available:

```bash
openclaw cron --help
```

Check whether the installed CLI supports last-route reuse for announce delivery in cron jobs. If the output does not confirm this capability, treat it as **unavailable** and fall through to C.

**C. No valid route (fallback)**

If no explicit target exists AND last-route reuse cannot be confirmed:
- Use `--no-deliver`
- Warn clearly: "Chat delivery is enabled in config but no valid announce route could be resolved. Job will run internal-only. Set `truthRecovery.reporting.delivery.to` to an explicit target to enable chat delivery."

**Do not silently configure announce with an unverifiable route.** Internal-only is safer than broken announce.

### Verify after creation

After creating each cron job, verify the resulting job definition:

```bash
openclaw cron list --json
```

Check that the job's delivery mode and route match the intended configuration. Do not rely on command success alone — inspect the actual job definition.

---

## Step 5: Check for Existing Jobs

Before creating, check if the jobs already exist:

```bash
openclaw cron list --json
```

If `--json` is not supported, fall back to `openclaw cron list`.

- If `truth-recovery-distiller-hourly` **already exists** → skip creation, report existing job. Direct operator to `runtime/sync-cron-delivery-prompt.md` if delivery mode needs updating.
- If `truth-recovery-distiller-nightly` **already exists** → same.

**Do not create duplicate jobs.**

---

## Step 6: Create Cron 1 — Hourly Sweep

**Only if the hourly job does not already exist.**

### If `sendHourlyChatReport == false` (or no valid route):

```bash
openclaw cron add \
  --name "truth-recovery-distiller-hourly" \
  --cron "0 * * * *" \
  --tz "<TIMEZONE>" \
  --session isolated \
  --no-deliver \
  --message "Run truth-recovery distiller.
Mode: hourly.
Read <PROMPT_PATH> and follow every step strictly.
Working directory: <WORKSPACE_PATH>"
```

### If `sendHourlyChatReport == true` AND valid route exists:

```bash
openclaw cron add \
  --name "truth-recovery-distiller-hourly" \
  --cron "0 * * * *" \
  --tz "<TIMEZONE>" \
  --session isolated \
  --announce \
  --message "Run truth-recovery distiller.
Mode: hourly.
Read <PROMPT_PATH> and follow every step strictly.
Working directory: <WORKSPACE_PATH>"
```

If `truthRecovery.reporting.delivery.to` is set, include the explicit target per the installed CLI's announce-target syntax.

---

## Step 7: Create Cron 2 — Nightly Pre-Consolidation

**Only if the nightly job does not already exist.**

### If `nightlyChatReport == false` (or no valid route):

```bash
openclaw cron add \
  --name "truth-recovery-distiller-nightly" \
  --cron "50 2 * * *" \
  --tz "<TIMEZONE>" \
  --session isolated \
  --no-deliver \
  --message "Run truth-recovery distiller.
Mode: nightly-preconsolidation.
Read <PROMPT_PATH> and follow every step strictly.
Working directory: <WORKSPACE_PATH>"
```

### If `nightlyChatReport == true` AND valid route exists:

```bash
openclaw cron add \
  --name "truth-recovery-distiller-nightly" \
  --cron "50 2 * * *" \
  --tz "<TIMEZONE>" \
  --session isolated \
  --announce \
  --message "Run truth-recovery distiller.
Mode: nightly-preconsolidation.
Read <PROMPT_PATH> and follow every step strictly.
Working directory: <WORKSPACE_PATH>"
```

---

## Step 8: Verify Crons Were Created

```bash
openclaw cron list
```

Check that:
- Created jobs exist with correct schedule and `--tz`
- Delivery mode matches the toggle/route resolution from Step 4
- Both payloads reference the absolute path to `runtime/correction-distiller-prompt.md`
- No placeholder literals appear in the payloads

---

## Step 9: Report

Compose a short confirmation:
- Resolved SKILL_ROOT, PROMPT_PATH, WORKSPACE_PATH, TELEMETRY_PATH, TIMEZONE
- Reporting config values read
- Delivery route resolution result
- For each job: created / skipped (already exists), delivery mode chosen
- Any warnings (toggle true but no route, job already existed)

---

## Anti-Patterns

Do NOT:
- Embed the full distiller procedure in the cron payload
- Leave variable names or placeholders in the cron payload
- Guess the cron creation syntax — use the exact `openclaw cron add` forms above
- Omit `--tz` — always specify the timezone explicitly
- Create duplicate jobs — check for existing jobs first
- Silently configure announce with no valid delivery route
- Use this file as the recurring runtime prompt — that is `runtime/correction-distiller-prompt.md`
- Hardcode any skill path assumption — resolve from this file's location

---

## Context

This cron pair runs **before** the host's consolidation cycle:

| System | Schedule | Purpose |
|--------|----------|---------|
| **truth-recovery hourly** | `0 * * * *` | Light distiller sweep |
| **truth-recovery nightly** | `50 2 * * *` | Pre-consolidation sweep + report |

truth-recovery's distiller is a **staging bridge**, not a consolidator.

### Reporting contract

Run records are written to the chosen telemetry root:
- Run logs: `TELEMETRY_PATH/truth-recovery/distiller/distiller-runs-YYYY-MM-DD.jsonl` (daily-sharded)
- Nightly report: `TELEMETRY_PATH/truth-recovery/latest-report/nightly-distill-report.md`

Telemetry is always written regardless of delivery mode. Delivery mode only controls whether cron output reaches chat.

### Later delivery changes

To change delivery mode after creation, run:
`SKILL_ROOT/runtime/sync-cron-delivery-prompt.md`
