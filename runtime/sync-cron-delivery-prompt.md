# Truth-Recovery — Sync Cron Delivery

Run this prompt after changing `truthRecovery.reporting.nightlyChatReport` or `truthRecovery.reporting.sendHourlyChatReport` in the harness state config. It re-syncs the cron jobs' delivery mode to match the current toggles.

This file lives inside `runtime/`. Resolve the absolute path of the parent of `runtime/` and use it as `SKILL_ROOT`.

---

## Rules

- Do not guess the cron edit syntax — use the exact commands shown below.
- Do not modify cron schedules, payloads, or timezones — only delivery mode.
- If a toggle is `true` but no valid delivery route can be resolved, keep the job internal and warn clearly.
- Prefer `openclaw cron list --json` for machine-readable inspection when available.

---

## Step 1: Resolve Paths

1. Resolve the absolute path of the parent of `runtime/` as `SKILL_ROOT`
2. Use the current working directory as `WORKSPACE_ROOT`

---

## Step 2: Read Reporting Config

Read `WORKSPACE_ROOT/runtime/harness-state/harness-state.json` if it exists.

Extract from the `truthRecovery` namespace:
- `truthRecovery.reporting.nightlyChatReport` (default: `false` if missing)
- `truthRecovery.reporting.sendHourlyChatReport` (default: `false` if missing)
- `truthRecovery.reporting.delivery.to` (default: `null` if missing)
- `truthRecovery.reporting.delivery.channel` (default: `"last"` if missing)

If the file does not exist, or `truthRecovery` / `truthRecovery.reporting` is missing, use the defaults. Do not error.

---

## Step 3: Inspect Existing Cron Jobs

List current truth-recovery cron jobs. Prefer machine-readable output:

```bash
openclaw cron list --json
```

If `--json` is not supported, fall back to:

```bash
openclaw cron list
```

Find:
- `truth-recovery-distiller-hourly`
- `truth-recovery-distiller-nightly`

If either job does not exist, report it as missing and skip it. Do not create jobs here — use `runtime/create-cron-prompt.md` for that.

---

## Step 4: Resolve Delivery Route

Before switching any job to announce delivery, resolve the announce route in this strict order:

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
- Do NOT switch the job to announce
- Keep or set the job to `--no-deliver`
- Warn clearly: "Chat delivery is enabled in config but no valid announce route could be resolved. Job remains internal-only. Set `truthRecovery.reporting.delivery.to` to an explicit target to enable chat delivery."

**Do not silently configure announce with an unverifiable route.** Internal-only is safer than broken announce.

---

## Step 5: Sync Hourly Job

### If `sendHourlyChatReport == false`:

```bash
openclaw cron edit "truth-recovery-distiller-hourly" --no-deliver
```

### If `sendHourlyChatReport == true` AND valid route exists:

```bash
openclaw cron edit "truth-recovery-distiller-hourly" --announce
```

If `truthRecovery.reporting.delivery.to` is set, include the explicit target in the edit command per the installed CLI's announce-target syntax.

### If `sendHourlyChatReport == true` BUT no valid route:

Keep `--no-deliver`. Warn the operator.

---

## Step 6: Sync Nightly Job

### If `nightlyChatReport == false`:

```bash
openclaw cron edit "truth-recovery-distiller-nightly" --no-deliver
```

### If `nightlyChatReport == true` AND valid route exists:

```bash
openclaw cron edit "truth-recovery-distiller-nightly" --announce
```

If `truthRecovery.reporting.delivery.to` is set, include the explicit target.

### If `nightlyChatReport == true` BUT no valid route:

Keep `--no-deliver`. Warn the operator.

---

## Step 7: Verify After Edit

After editing any job, verify the resulting job definitions:

```bash
openclaw cron list --json
```

Check that each job's delivery mode and route match the intended configuration. Do not rely on edit command success alone — inspect the actual job definitions.

---

## Step 8: Report

Compose a short confirmation:

- Current config values (both toggles + delivery settings)
- Route resolution result (explicit target / last-route reuse confirmed / no valid route)
- Hourly job: delivery mode before → after (or "missing" / "unchanged" / "warning: no route")
- Nightly job: delivery mode before → after (or "missing" / "unchanged" / "warning: no route")
- Verification result from Step 7

---

## Important

- This prompt only changes delivery mode. It does not change schedules, payloads, or timezones.
- JSONL telemetry and nightly report file generation remain always-on regardless of delivery mode.
- Delivery mode is a cron-job-level property. Prompt-level toggles alone cannot control whether the cron runner delivers to chat.
- Enabling a reporting toggle does not by itself guarantee delivery. A valid announce route must also be resolvable.
- If route resolution is weak: warn, stay internal, keep telemetry logging — do not pretend chat delivery is working.
