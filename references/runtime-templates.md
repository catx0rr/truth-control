# Runtime File Templates

Templates for initializing truth-control runtime and telemetry surfaces.

**Path model:** Live operational state lives under `<workspace>/runtime/`. Observability and telemetry lives under a chosen `<telemetry-root>/`.

Telemetry root resolution used by the helper scripts in this package:
1. explicit `--telemetry-dir`
2. `TRUTH_CONTROL_TELEMETRY_ROOT`
3. `TRUTH_RECOVERY_TELEMETRY_ROOT`
4. `~/.openclaw/telemetry` as a common local-host fallback example, not a required package path

---

## Workspace Runtime — Live Operational State

### runtime/truth-recovery/recent-corrections.jsonl

Append-only JSONL file. One correction per line. Hot correction register owned by truth-recovery.

#### Entry schema

```json
{
  "old": "incorrect value",
  "corrected": "correct value",
  "scope": "location",
  "source": "user_correction",
  "timestamp": "2026-04-05T16:30:00+08:00",
  "timestamp_utc": "2026-04-05T08:30:00Z",
  "timezone": "Asia/Manila",
  "context": "Optional context for the correction",
  "consolidated": false,
  "consolidated_at": null,
  "consolidated_at_utc": null,
  "staged": false,
  "staged_at": null,
  "staged_at_utc": null
}
```

#### Field reference

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `old` | string | yes | The old/incorrect value |
| `corrected` | string | yes | The corrected value from the user |
| `scope` | string | yes | Category: `location`, `time`, `date`, `person`, `event`, `decision`, `quantity`, `preference`, `other` |
| `source` | string | yes | Always `"user_correction"` for user-initiated corrections |
| `timestamp` | string | yes | Local timezone-aware ISO 8601 with explicit offset |
| `timestamp_utc` | string | yes | UTC ISO 8601 with Z suffix — same moment as `timestamp` |
| `timezone` | string | yes | IANA timezone name (e.g., `Asia/Manila`) or offset label (e.g., `UTC+08:00`) |
| `context` | string | no | Optional context for the correction |
| `consolidated` | boolean | no | Set to `true` when the host's consolidator picks up this correction |
| `consolidated_at` | string | no | Local-aware ISO timestamp of when the consolidator processed it |
| `consolidated_at_utc` | string | no | UTC companion for consolidated_at |
| `staged` | boolean | no | Set to `true` when the distiller bridge stages this correction into daily memory |
| `staged_at` | string | no | Local-aware ISO timestamp of when staging occurred |
| `staged_at_utc` | string | no | UTC companion for staged_at |

#### Lifecycle

1. Created by `writeback.py` when user corrects the agent
2. Read by `check.py` on every pre-output gate check
3. Read by `recover.py` as Priority 2 in the local recovery surfaces
4. Staged by `distill.py` → distilled note appended to `memory/YYYY-MM-DD.md` → entry marked `staged: true`
5. Marked `consolidated: true` by the host's consolidator after it updates durable memory
6. Pruned by `writeback.py --prune` after 30 days if consolidated

**Important:** `staged` and `consolidated` are distinct states. Staging makes corrections visible to consolidators. Consolidation is the host's responsibility. The distiller never sets `consolidated: true`.

#### Initialize

```bash
mkdir -p <workspace>/runtime/truth-recovery
touch <workspace>/runtime/truth-recovery/recent-corrections.jsonl
```

---

### runtime/pending-actions/pending-actions.jsonl

Shared workspace runtime surface. Tracks actions the agent has initiated that have pending outcomes. Not truth-recovery-specific — other packages may also read or write this.

#### Entry schema

```json
{
  "id": "pa_001",
  "action": "Deploy configuration for the journal site",
  "status": "in_progress",
  "initiated": "2026-04-05T18:00:00+08:00",
  "expected_completion": "2026-04-05T18:15:00+08:00",
  "context": "Server deployment",
  "outcome": null,
  "outcome_source": null,
  "outcome_timestamp": null
}
```

#### Field reference

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | yes | Unique ID: `pa_NNN` |
| `action` | string | yes | What was initiated |
| `status` | string | yes | `pending`, `in_progress`, `completed`, `failed`, `unknown` |
| `initiated` | string | yes | ISO timestamp of when action started |
| `expected_completion` | string | no | When the action is expected to finish |
| `context` | string | no | Additional context |
| `outcome` | string | no | Result of the action (filled after completion) |
| `outcome_source` | string | no | How the outcome was verified: `tool_output`, `user_report`, `log_check`, `inferred` |
| `outcome_timestamp` | string | no | When the outcome was recorded |

#### Status transitions

```
pending → in_progress → completed
                      → failed
                      → unknown (if no outcome after expected_completion)
```

#### Initialize

```bash
mkdir -p <workspace>/runtime/pending-actions
touch <workspace>/runtime/pending-actions/pending-actions.jsonl
```

---

### runtime/harness-state/harness-state.json

Global shared runtime state file for custom memory / harness packages. Each package stores its config under its own namespace. Not required by current core scripts — reserved for host-level state tracking.

#### Schema

`harness-state.json` is a shared root. Each package stores all of its state under its own namespace. truth-recovery uses `truthRecovery`. Other packages (e.g., auto-dream, mempalace) would use their own namespaces alongside it.

```json
{
  "truthRecovery": {
    "version": "1.0",
    "session_context_level": "normal",
    "last_correction_check": null,
    "corrections_active": 0,
    "pending_actions_active": 0,
    "reporting": {
      "nightlyChatReport": false,
      "sendHourlyChatReport": false,
      "delivery": {
        "channel": "last",
        "to": null
      }
    },
    "stats": {
      "checks_total": 0,
      "checks_specific": 0,
      "checks_gated": 0,
      "corrections_recorded": 0,
      "recoveries_run": 0,
      "anchored_outputs": 0,
      "tentative_outputs": 0,
      "unanchored_outputs": 0
    }
  }
}
```

#### Reporting config (under `truthRecovery`)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `truthRecovery.reporting.nightlyChatReport` | boolean | `false` | Nightly cron should deliver report to chat |
| `truthRecovery.reporting.sendHourlyChatReport` | boolean | `false` | Hourly cron should deliver report to chat |
| `truthRecovery.reporting.delivery.channel` | string | `"last"` | Delivery channel strategy — `"last"` attempts host last-route reuse, not a guaranteed universal delivery path |
| `truthRecovery.reporting.delivery.to` | string | `null` | Explicit announce target — highest confidence route, overrides channel strategy |

**Reporting law:** JSONL telemetry logs are always written regardless of these settings. Markdown latest report is always generated for nightly runs. These toggles control cron delivery mode only.

**Delivery resolution law:** When a toggle is `true`, the announce route is resolved strictly: (1) explicit `delivery.to` wins, (2) `delivery.channel == "last"` is attempted only if the host runtime confirms support, (3) otherwise keep internal-only and warn. The package must never configure a broken announce cron silently.

**Delivery law:** Toggles decide whether report content is *eligible* for chat delivery. The cron job's delivery configuration decides whether the runner can *actually send* it. When toggles change, the cron jobs must be re-synced via `runtime/sync-cron-delivery-prompt.md`.

#### Context level detection

| Level | Condition |
|-------|-----------|
| `thin` | Session just started, cold boot, restart, reconnect, <3 exchanges |
| `normal` | Active session with moderate history |
| `rich` | Long session with deep context available |

#### Initialize

Use the safe init script to merge the `truthRecovery` namespace without destroying other packages:

```bash
mkdir -p <workspace>/runtime/harness-state
python3 <skill-root>/scripts/init_harness_config.py \
  --file <workspace>/runtime/harness-state/harness-state.json
```

**Do not use `cat >` to overwrite this file** — it is shared across packages. The init script safely merges the `truthRecovery` namespace, preserving any other namespaces already present. If `truthRecovery` already exists, it skips by default (use `--force` to overwrite).

---

## Global Telemetry — Observability / Reporting

Telemetry lives under `<telemetry-root>/`, separate from workspace runtime.

### truth-recovery/distiller/distiller-runs-YYYY-MM-DD.jsonl

Daily-sharded append-only JSONL file. One run record per distiller execution.

#### Entry schema

```json
{
  "timestamp": "2026-04-12T10:00:00+08:00",
  "timestamp_utc": "2026-04-12T02:00:00Z",
  "timezone": "Asia/Manila",
  "mode": "nightly-preconsolidation",
  "success": true,
  "corrections_loaded": 4,
  "corrections_unstaged": 2,
  "corrections_staged": 2,
  "would_stage": 2,
  "error": null
}
```

#### Field reference

| Field | Type | Description |
|-------|------|-------------|
| `timestamp` | string | Local timezone-aware ISO 8601 with explicit offset |
| `timestamp_utc` | string | UTC ISO 8601 with Z suffix |
| `timezone` | string | IANA timezone name or offset label |
| `mode` | string | `hourly` or `nightly-preconsolidation` |
| `success` | boolean | Whether the distiller run succeeded |
| `corrections_loaded` | number | Total corrections in the file |
| `corrections_unstaged` | number | Unstaged corrections found |
| `corrections_staged` | number | Corrections actually staged this run |
| `would_stage` | number | Corrections that would have been staged |
| `error` | string | Error message if `success` is false, else null |

#### Backward compatibility

Parsers must tolerate older entries that may lack `timestamp_utc` or `timezone`. New entries must always include the full triple.

#### Initialize

```bash
mkdir -p <telemetry-root>/truth-recovery/distiller
```

---

### truth-recovery/latest-report/nightly-distill-report.md

Overwritten each nightly run. Human-readable convenience surface, not canonical telemetry.

#### Initialize

```bash
mkdir -p <telemetry-root>/truth-recovery/latest-report
```

---

## Timestamp Contract

All timestamps across the truth-recovery package follow this rule:

- **`timestamp`** — local timezone-aware ISO 8601 with explicit offset (primary)
- **`timestamp_utc`** — UTC ISO 8601 with Z suffix (companion for machine correlation)
- **`timezone`** — IANA timezone name if known, offset label as fallback

Local-aware first. UTC companion for correlation. Never naive.

---

## Directory Structure

### Workspace runtime (live operational state)

```
<workspace>/runtime/
├── truth-recovery/
│   └── recent-corrections.jsonl
├── pending-actions/
│   └── pending-actions.jsonl
└── harness-state/
    └── harness-state.json
```

### Global telemetry (observability)

```
<telemetry-root>/
└── truth-recovery/
    ├── distiller/
    │   └── distiller-runs-YYYY-MM-DD.jsonl
    └── latest-report/
        └── nightly-distill-report.md
```

### Staging target (workspace memory)

```
<workspace>/memory/
├── YYYY-MM-DD.md                  # Primary staging target
└── corrections/
    └── YYYY-MM.md                 # Optional audit mirror
```
