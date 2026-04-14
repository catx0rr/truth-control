import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";
import { fileURLToPath } from "node:url";
import path from "node:path";
import os from "node:os";
import { spawn } from "node:child_process";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SCRIPTS_DIR = path.join(__dirname, "scripts");
const DEFAULT_TIMEOUT_MS = 30_000;
const DEFAULT_CORRECTION_SIGNAL_TTL_MS = 5 * 60_000;
const TOOL_NAME = "truth_recovery";
const correctionSignals = new Map();

const TRUTH_CONTROL_GATE_GUIDANCE = [
  "Truth-control hint:",
  "",
  "This turn may require anchored recall before making a specific factual claim.",
  "Do not state weakly anchored past details as fact.",
  "Recent explicit corrections may outrank stale memory.",
  "Use the truth_recovery tool to check whether a recent correction or local anchor changes the answer.",
  "If the specific cannot be anchored, ask, retrieve, or stay general."
].join("\n");

const EXPLICIT_CORRECTION_GUIDANCE = [
  "Truth-control correction hint:",
  "",
  "This turn appears to contain an explicit user correction.",
  "Treat the correction as higher priority than stale memory.",
  "If the correction changes a factual answer, use the corrected value.",
  "If needed, use truth_recovery to inspect anchors or recent corrections before answering.",
  "Do not ignore explicit corrections."
].join("\n");

const POSSIBLE_CORRECTION_GUIDANCE = [
  "Truth-control correction hint:",
  "",
  "This turn may contain a user correction or clarification.",
  "Verify before carrying forward earlier specifics.",
  "If the user is correcting a prior factual detail, prefer the corrected value over stale memory.",
  "Use truth_recovery if you need to inspect anchors or recent corrections before answering."
].join("\n");

function asString(value) {
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

function asBoolean(value, fallback = false) {
  return typeof value === "boolean" ? value : fallback;
}

function asInteger(value, fallback) {
  return Number.isInteger(value) ? value : fallback;
}

function resolveMaybeAbsolute(baseDir, value, warnings, label) {
  const raw = asString(value);
  if (!raw) return undefined;
  if (path.isAbsolute(raw)) return raw;
  warnings.push(`${label} was relative, resolved against ${baseDir}`);
  return path.resolve(baseDir, raw);
}

function resolveWorkspaceRoot(pluginConfig) {
  const configured = asString(pluginConfig?.paths?.workspaceRoot);
  const envWorkspace = asString(process.env.OPENCLAW_WORKSPACE);
  return path.resolve(configured || envWorkspace || path.join(os.homedir(), ".openclaw", "workspace"));
}

function resolveExecutionConfig(params, pluginConfig) {
  const warnings = [];
  const workspaceRoot = resolveWorkspaceRoot(pluginConfig);

  const correctionsFile =
    resolveMaybeAbsolute(
      workspaceRoot,
      asString(params.correctionsFile) || asString(pluginConfig?.paths?.correctionsFile),
      warnings,
      "correctionsFile"
    ) || path.join(workspaceRoot, "runtime", "truth-recovery", "recent-corrections.jsonl");

  const pendingFile =
    resolveMaybeAbsolute(
      workspaceRoot,
      asString(params.pendingFile) || asString(pluginConfig?.paths?.pendingFile),
      warnings,
      "pendingFile"
    ) || path.join(workspaceRoot, "runtime", "pending-actions", "pending-actions.jsonl");

  const memoryFile =
    resolveMaybeAbsolute(
      workspaceRoot,
      asString(params.memoryFile) || asString(pluginConfig?.paths?.memoryFile),
      warnings,
      "memoryFile"
    ) || path.join(workspaceRoot, "MEMORY.md");

  const dailyLogDir =
    resolveMaybeAbsolute(
      workspaceRoot,
      asString(params.dailyLogDir) || asString(pluginConfig?.paths?.dailyLogDir),
      warnings,
      "dailyLogDir"
    ) || path.join(workspaceRoot, "memory");

  return {
    workspaceRoot,
    correctionsFile,
    pendingFile,
    memoryFile,
    dailyLogDir,
    pythonBinary: asString(pluginConfig?.pythonBinary) || "python3",
    defaultCheckPending: asBoolean(pluginConfig?.defaultCheckPending, true),
    correctionSignalTtlMs: asInteger(pluginConfig?.correctionSignalTtlMs, DEFAULT_CORRECTION_SIGNAL_TTL_MS),
    enableExplicitCorrectionAutoWriteback: asBoolean(pluginConfig?.enableExplicitCorrectionAutoWriteback, true),
    warnings
  };
}

function runPython(pythonBinary, args, timeoutMs = DEFAULT_TIMEOUT_MS) {
  return new Promise((resolve, reject) => {
    const child = spawn(pythonBinary, args, { cwd: SCRIPTS_DIR, env: process.env });
    let stdout = "";
    let stderr = "";
    let settled = false;
    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      child.kill("SIGTERM");
      reject(new Error(`Script timed out after ${timeoutMs}ms`));
    }, timeoutMs);

    child.stdout.on("data", (chunk) => {
      stdout += chunk.toString();
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk.toString();
    });
    child.on("error", (error) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      reject(error);
    });
    child.on("close", (code) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      let parsed;
      try {
        parsed = stdout.trim() ? JSON.parse(stdout) : undefined;
      } catch {
        parsed = undefined;
      }
      if (code !== 0 && parsed === undefined) {
        reject(new Error((stderr || stdout || `Script exited with code ${code}`).trim()));
        return;
      }
      resolve({ code, stdout, stderr, parsed });
    });
  });
}

function flattenText(value, depth = 0) {
  if (depth > 5 || value == null) return "";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) {
    return value.map((item) => flattenText(item, depth + 1)).filter(Boolean).join(" ");
  }
  if (typeof value === "object") {
    const preferred = ["text", "content", "message", "body", "input", "prompt", "arguments"];
    const parts = [];
    for (const key of preferred) {
      if (key in value) {
        const text = flattenText(value[key], depth + 1);
        if (text) parts.push(text);
      }
    }
    if (parts.length) return parts.join(" ");
    return Object.values(value)
      .map((item) => flattenText(item, depth + 1))
      .filter(Boolean)
      .join(" ");
  }
  return "";
}

function getLatestUserText(event) {
  const messages = Array.isArray(event?.messages) ? event.messages : [];
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    const message = messages[i];
    if (message?.role === "user") {
      return flattenText(message.content ?? message);
    }
  }
  return "";
}

function isTruthRiskTurn(text) {
  const normalized = asString(text)?.toLowerCase();
  if (!normalized) return false;
  const patterns = [
    /\bremember\b/,
    /\brecall\b/,
    /\bearlier\b/,
    /\bbefore\b/,
    /\byesterday\b/,
    /\blast (?:time|night|week|weekend|month)\b/,
    /\bwhat did (?:i|we|you)\b/,
    /\bwho said\b/,
    /\bwhen did\b/,
    /\bwhat happened\b/,
    /\bhow did (?:it|that) go\b/,
    /\bdid (?:it|that) work\b/,
    /\bwe decided\b/,
    /\byou said\b/,
    /\byou told me\b/,
    /\bexact\b/,
    /\bversion\b/,
    /\bstatus\b/
  ];
  return patterns.some((pattern) => pattern.test(normalized));
}

function sanitizeInboundBody(text) {
  const normalized = asString(text);
  if (!normalized) return "";
  return normalized
    .replace(/^\[message_id:[^\]]+\]\s*/i, "")
    .replace(/\[Thread history\][\s\S]*?\[\/Thread history\]\s*/gi, "")
    .replace(/\s+/g, " ")
    .trim();
}

function cleanCorrectionValue(value) {
  const cleaned = asString(value)
    ?.replace(/^["'“”‘’]+|["'“”‘’]+$/g, "")
    .replace(/[.?!]+$/g, "")
    .trim();
  if (!cleaned) return undefined;
  if (cleaned.length < 2 || cleaned.length > 120) return undefined;
  return cleaned;
}

function inferCorrectionScope(text, oldValue, correctedValue) {
  const combined = [text, oldValue, correctedValue].filter(Boolean).join(" ").toLowerCase();
  if (/\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\b/.test(combined)) return "time";
  if (/\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|yesterday|today|tomorrow|weekend)\b/.test(combined)) {
    return "date";
  }
  if (/\bversion\b/.test(combined)) return "version";
  if (/\bstatus\b/.test(combined)) return "status";
  if (/\b(?:client|customer|person|owner|wife|daughter|sister|brother|cat)\b/.test(combined)) return "person";
  if (/\b(?:in|at|from|to|near)\b/.test(combined)) return "location";
  return "detail";
}

function countWords(value) {
  const normalized = asString(value);
  if (!normalized) return 0;
  return normalized.split(/\s+/).filter(Boolean).length;
}

function startsWithCorrectionMarker(text) {
  const normalized = asString(text);
  if (!normalized) return false;
  return /^(?:wait|no|actually|correction|i mean|i meant|should be|it(?:'s| is)|not)\b/i.test(normalized);
}

function looksSpeculativeOrRhetorical(text) {
  const normalized = asString(text);
  if (!normalized) return false;
  return /\?|\b(?:maybe|probably|i think|i guess|perhaps|or maybe|or just|kind of|sort of)\b/i.test(normalized);
}

function hasReplyContext(event, ctx) {
  return Boolean(
    event?.replyTo ||
      event?.replyToMessageId ||
      event?.quotedMessageId ||
      event?.quotedMessage ||
      ctx?.replyToMessageId ||
      ctx?.quotedMessageId
  );
}

function isShortUnambiguousCorrection(oldValue, correctedValue) {
  const oldWords = countWords(oldValue);
  const correctedWords = countWords(correctedValue);
  return oldWords > 0 && correctedWords > 0 && oldWords <= 6 && correctedWords <= 8;
}

function buildStructuredCorrection({ body, oldValue, correctedValue, patternLabel, captureConfidence }) {
  if (!oldValue || !correctedValue) return undefined;
  if (oldValue.toLowerCase() === correctedValue.toLowerCase()) return undefined;
  return {
    correctionSignal: "explicit_correction",
    reason: "structured_replacement",
    oldValue,
    correctedValue,
    scope: inferCorrectionScope(body, oldValue, correctedValue),
    bodyForAgent: body,
    autoWriteCandidate: captureConfidence === "high",
    capture_confidence: captureConfidence,
    capture_reason: `matched pattern: ${patternLabel}`
  };
}

function shouldAutoWriteStructuredCorrection(detection, event, ctx) {
  if (!detection?.oldValue || !detection?.correctedValue) {
    return { autoWriteCandidate: false, autoWriteGuards: ["no_structured_pair"] };
  }

  if (looksSpeculativeOrRhetorical(detection.bodyForAgent)) {
    return { autoWriteCandidate: false, autoWriteGuards: ["speculative_or_rhetorical"] };
  }

  const autoWriteGuards = [];
  if (hasReplyContext(event, ctx)) autoWriteGuards.push("reply_context");
  if (startsWithCorrectionMarker(detection.bodyForAgent)) autoWriteGuards.push("starts_with_correction_marker");
  if (detection.scope && detection.scope !== "detail") autoWriteGuards.push("clear_scope");
  if (isShortUnambiguousCorrection(detection.oldValue, detection.correctedValue)) {
    autoWriteGuards.push("short_unambiguous_pair");
  }

  if (detection.capture_confidence === "high") {
    return { autoWriteCandidate: true, autoWriteGuards };
  }

  if (detection.capture_confidence === "medium") {
    return {
      autoWriteCandidate: autoWriteGuards.length >= 2,
      autoWriteGuards: autoWriteGuards.length ? autoWriteGuards : ["insufficient_additional_guards"]
    };
  }

  return {
    autoWriteCandidate:
      autoWriteGuards.length >= 3 &&
      (autoWriteGuards.includes("clear_scope") || autoWriteGuards.includes("reply_context")),
    autoWriteGuards: autoWriteGuards.length ? autoWriteGuards : ["insufficient_additional_guards"]
  };
}

function classifyCorrectionIntent(text) {
  const body = sanitizeInboundBody(text);
  if (!body) {
    return { correctionSignal: "none", reason: "empty" };
  }

  const lower = body.toLowerCase();
  const benignPatterns = [
    /^\s*(?:no|nope|nah)\s*(?:thanks|thank you)?[.!?]*\s*$/i,
    /^\s*(?:no\s+problem|no\s+worries|not\s+yet|not\s+now|not\s+really|not\s+sure)\s*[.!?]*\s*$/i,
    /^\s*(?:all good|that'?s fine|its fine|it'?s fine)\s*[.!?]*\s*$/i
  ];
  if (benignPatterns.some((pattern) => pattern.test(body))) {
    return { correctionSignal: "none", reason: "benign_negative" };
  }

  const structuredPatterns = [
    {
      pattern: /^(?:no\s*,\s*)?not\s+(.{1,80}?)\s*(?:-|–|—|,?\s+but)\s+(.{1,120}?)\s*$/i,
      patternLabel: "not X, but Y",
      captureConfidence: "high",
      extract: (match) => ({ oldValue: match[1], correctedValue: match[2] })
    },
    {
      pattern: /^(?:it(?:'s|\s+is))\s+(.{1,120}?)\s*,?\s*not\s+(.{1,80}?)\s*$/i,
      patternLabel: "it's X, not Y",
      captureConfidence: "high",
      extract: (match) => ({ oldValue: match[2], correctedValue: match[1] })
    },
    {
      pattern: /^should\s+be\s+(.{1,120}?)\s*,?\s*not\s+(.{1,80}?)\s*$/i,
      patternLabel: "should be X, not Y",
      captureConfidence: "high",
      extract: (match) => ({ oldValue: match[2], correctedValue: match[1] })
    },
    {
      pattern: /^i\s+mea(?:n|nt)\s+(.{1,120}?)\s*,?\s*not\s+(.{1,80}?)\s*$/i,
      patternLabel: "I mean X, not Y",
      captureConfidence: "high",
      extract: (match) => ({ oldValue: match[2], correctedValue: match[1] })
    },
    {
      pattern: /^(?:wait|no|actually)\s*,\s*(.{1,120}?)\s*,?\s*not\s+(.{1,80}?)\s*$/i,
      patternLabel: "interruption correction X, not Y",
      captureConfidence: "medium",
      extract: (match) => ({ oldValue: match[2], correctedValue: match[1] })
    },
    {
      pattern: /^(.{1,120}?)\s+not\s+(.{1,80}?)\s*$/i,
      patternLabel: "bare X not Y",
      captureConfidence: "low",
      extract: (match) => ({ oldValue: match[2], correctedValue: match[1] })
    }
  ];

  for (const structuredPattern of structuredPatterns) {
    const match = body.match(structuredPattern.pattern);
    if (!match) continue;
    const extracted = structuredPattern.extract(match);
    const oldValue = cleanCorrectionValue(extracted.oldValue);
    const correctedValue = cleanCorrectionValue(extracted.correctedValue);
    const structured = buildStructuredCorrection({
      body,
      oldValue,
      correctedValue,
      patternLabel: structuredPattern.patternLabel,
      captureConfidence: structuredPattern.captureConfidence
    });
    if (structured) {
      return structured;
    }
  }

  const explicitPatterns = [
    /^\s*actually\b/i,
    /^\s*i meant\b/i,
    /^\s*you forgot\b/i,
    /^\s*(?:that'?s|that is)\s+incorrect\b/i,
    /^\s*(?:you'?re|you are)\s+wrong\b/i,
    /^\s*no\s*,/i
  ];
  if (explicitPatterns.some((pattern) => pattern.test(body))) {
    return {
      correctionSignal: "explicit_correction",
      reason: "explicit_correction_phrase",
      bodyForAgent: body,
      autoWriteCandidate: false
    };
  }

  const possiblePatterns = [/\bwrong\b/i, /\bnot that\b/i, /\bcorrection\b/i, /\bupdated\b/i, /\bchanged\b/i];
  if (possiblePatterns.some((pattern) => pattern.test(lower))) {
    return {
      correctionSignal: "possible_correction",
      reason: "possible_correction_phrase",
      bodyForAgent: body,
      autoWriteCandidate: false
    };
  }

  return { correctionSignal: "none", reason: "no_signal", bodyForAgent: body };
}

function cleanupCorrectionSignals(ttlMs = DEFAULT_CORRECTION_SIGNAL_TTL_MS) {
  const now = Date.now();
  for (const [key, entry] of correctionSignals.entries()) {
    if (!entry?.seenAt || now - entry.seenAt > ttlMs) {
      correctionSignals.delete(key);
    }
  }
}

function setCorrectionSignal(sessionKey, signal, ttlMs) {
  if (!sessionKey || !signal) return;
  cleanupCorrectionSignals(ttlMs);
  correctionSignals.set(sessionKey, { ...signal, seenAt: Date.now() });
}

function consumeCorrectionSignal(sessionKey, ttlMs) {
  if (!sessionKey) return undefined;
  cleanupCorrectionSignals(ttlMs);
  const signal = correctionSignals.get(sessionKey);
  if (!signal) return undefined;
  correctionSignals.delete(sessionKey);
  return signal;
}

function summarizePayload(action, payload) {
  if (action === "check") {
    return `Check complete, mode=${payload.recommended_mode ?? "unknown"}, specific=${payload.is_specific === true}.`;
  }
  if (action === "recover") {
    return `Recovery complete, anchors=${payload.anchors_found ?? 0}, best_strength=${payload.best_strength ?? "none"}.`;
  }
  if (action === "writeback") {
    return "Correction recorded to recent corrections register.";
  }
  if (action === "list-corrections") {
    return `Listed ${payload.count ?? 0} correction(s).`;
  }
  if (action === "prune-corrections") {
    return `Prune complete, removed=${payload.removed ?? 0}, kept=${payload.kept ?? 0}.`;
  }
  if (action === "mark-consolidated") {
    return `Mark consolidated complete, found=${payload.found === true}.`;
  }
  return `Action ${action} complete.`;
}

function shapeResult(action, payload, resolved) {
  const envelope = {
    action,
    summary: summarizePayload(action, payload),
    resolved: {
      workspaceRoot: resolved.workspaceRoot,
      correctionsFile: resolved.correctionsFile,
      pendingFile: resolved.pendingFile,
      memoryFile: resolved.memoryFile,
      dailyLogDir: resolved.dailyLogDir,
      warnings: resolved.warnings
    },
    result: payload
  };

  return {
    content: [{ type: "text", text: JSON.stringify(envelope, null, 2) }],
    details: envelope
  };
}

function buildArgs(action, params, resolved) {
  const args = [];

  if (action === "check") {
    args.push(path.join(SCRIPTS_DIR, "check.py"));
    args.push("--claim", asString(params.claim));
    args.push("--corrections-file", resolved.correctionsFile);
    args.push("--max-age-days", String(asInteger(params.maxAgeDays, 30)));
    if (asString(params.specificity)) args.push("--specificity", asString(params.specificity));
    if (asString(params.claimType)) args.push("--claim-type", asString(params.claimType));
    return args;
  }

  if (action === "recover") {
    args.push(path.join(SCRIPTS_DIR, "recover.py"));
    args.push("--query", asString(params.query));
    args.push("--corrections-file", resolved.correctionsFile);
    args.push("--pending-file", resolved.pendingFile);
    args.push("--memory-file", resolved.memoryFile);
    args.push("--log-dir", resolved.dailyLogDir);
    args.push("--days", String(asInteger(params.days, 7)));
    if (typeof params.checkPending === "boolean" ? params.checkPending : resolved.defaultCheckPending) {
      args.push("--check-pending");
    }
    return args;
  }

  if (action === "writeback") {
    args.push(path.join(SCRIPTS_DIR, "writeback.py"));
    args.push("--old", asString(params.old));
    args.push("--corrected", asString(params.corrected));
    args.push("--scope", asString(params.scope));
    args.push("--file", resolved.correctionsFile);
    if (asString(params.source)) args.push("--source", asString(params.source));
    if (asString(params.context)) args.push("--context", asString(params.context));
    if (asString(params.captureConfidence)) args.push("--capture-confidence", asString(params.captureConfidence));
    if (asString(params.captureReason)) args.push("--capture-reason", asString(params.captureReason));
    return args;
  }

  if (action === "list-corrections") {
    args.push(path.join(SCRIPTS_DIR, "writeback.py"));
    args.push("--list", "--file", resolved.correctionsFile, "--max-age-days", String(asInteger(params.maxAgeDays, 30)));
    return args;
  }

  if (action === "prune-corrections") {
    args.push(path.join(SCRIPTS_DIR, "writeback.py"));
    args.push("--prune", "--file", resolved.correctionsFile, "--max-age-days", String(asInteger(params.maxAgeDays, 30)));
    return args;
  }

  if (action === "mark-consolidated") {
    args.push(path.join(SCRIPTS_DIR, "writeback.py"));
    args.push("--mark-consolidated", asString(params.old), "--file", resolved.correctionsFile);
    return args;
  }

  throw new Error(`Unsupported action: ${action}`);
}

async function maybeAutoRecordExplicitCorrection(detection, pluginConfig, logger) {
  if (!detection?.autoWriteCandidate || !detection.oldValue || !detection.correctedValue) {
    return { autoRecorded: false, reason: "no_structured_candidate" };
  }

  const resolved = resolveExecutionConfig({}, pluginConfig ?? {});
  if (!resolved.enableExplicitCorrectionAutoWriteback) {
    return { autoRecorded: false, reason: "auto_writeback_disabled" };
  }

  const params = {
    old: detection.oldValue,
    corrected: detection.correctedValue,
    scope: detection.scope || "detail",
    source: "truth_control_hook",
    context: detection.bodyForAgent?.slice(0, 240),
    captureConfidence: detection.capture_confidence,
    captureReason: detection.capture_reason
  };

  try {
    const args = buildArgs("writeback", params, resolved);
    const run = await runPython(resolved.pythonBinary, args, DEFAULT_TIMEOUT_MS);
    return {
      autoRecorded: run.code === 0,
      payload: run.parsed,
      stderr: run.stderr?.trim() || undefined
    };
  } catch (error) {
    logger?.warn?.(`truth-control: explicit correction auto-writeback failed (${String(error)})`);
    return { autoRecorded: false, error: String(error) };
  }
}

function buildTruthControlGuidance({ truthRisk, correctionSignal }) {
  const sections = [];
  if (correctionSignal?.correctionSignal === "explicit_correction") {
    sections.push(EXPLICIT_CORRECTION_GUIDANCE);
  } else if (correctionSignal?.correctionSignal === "possible_correction") {
    sections.push(POSSIBLE_CORRECTION_GUIDANCE);
  }
  if (truthRisk) {
    sections.push(TRUTH_CONTROL_GATE_GUIDANCE);
  }
  return sections.join("\n\n");
}

export default definePluginEntry({
  id: "truth-recovery",
  name: "Truth Control",
  description:
    "Truth-control plugin with compatibility ids preserved for local truth gating, correction-trigger support, and correction precedence.",
  register(api) {
    api.on("before_dispatch", async (event, ctx) => {
      if (!asBoolean(api.pluginConfig?.enableCorrectionCapture, true)) {
        return;
      }
      const sessionKey = asString(event.sessionKey) || asString(ctx.sessionKey);
      const body = sanitizeInboundBody(asString(event.body) || asString(event.content) || "");
      if (!sessionKey || !body) {
        return;
      }

      const resolved = resolveExecutionConfig({}, api.pluginConfig ?? {});
      const detection = classifyCorrectionIntent(body);
      if (detection.correctionSignal === "none") {
        return;
      }

      const autoWriteDecision =
        detection.reason === "structured_replacement"
          ? shouldAutoWriteStructuredCorrection(detection, event, ctx)
          : { autoWriteCandidate: false, autoWriteGuards: ["non_structured_explicit_signal"] };

      const finalDetection = {
        ...detection,
        autoWriteCandidate: autoWriteDecision.autoWriteCandidate,
        autoWriteGuards: autoWriteDecision.autoWriteGuards
      };

      const autoWriteback =
        finalDetection.correctionSignal === "explicit_correction"
          ? await maybeAutoRecordExplicitCorrection(finalDetection, api.pluginConfig ?? {}, api.logger)
          : { autoRecorded: false, reason: "non_explicit_or_non_structured" };

      setCorrectionSignal(
        sessionKey,
        {
          ...finalDetection,
          autoWriteback,
          senderId: asString(event.senderId),
          messageTimestamp: event.timestamp
        },
        resolved.correctionSignalTtlMs
      );
    });

    api.on("before_prompt_build", async (event, ctx) => {
      if (!asBoolean(api.pluginConfig?.enablePromptGuidance, true)) {
        return;
      }
      const latestUserText = getLatestUserText(event);
      const truthRisk = isTruthRiskTurn(latestUserText);
      const ttlMs = asInteger(api.pluginConfig?.correctionSignalTtlMs, DEFAULT_CORRECTION_SIGNAL_TTL_MS);
      const correctionSignal = consumeCorrectionSignal(asString(ctx.sessionKey), ttlMs);
      const guidance = buildTruthControlGuidance({ truthRisk, correctionSignal });
      if (!guidance) {
        return;
      }
      return { prependContext: guidance };
    });

    api.registerTool({
      name: TOOL_NAME,
      description:
        "Truth-control compatibility tool for specific factual claims. Supports check, recover, writeback, correction listing, pruning, and consolidation marking.",
      parameters: {
        type: "object",
        additionalProperties: false,
        properties: {
          action: {
            type: "string",
            enum: ["check", "recover", "writeback", "list-corrections", "prune-corrections", "mark-consolidated"]
          },
          claim: { type: "string" },
          query: { type: "string" },
          old: { type: "string" },
          corrected: { type: "string" },
          scope: { type: "string" },
          source: { type: "string" },
          context: { type: "string" },
          captureConfidence: { type: "string", enum: ["high", "medium", "low"] },
          captureReason: { type: "string" },
          specificity: { type: "string", enum: ["auto", "specific", "general"] },
          claimType: { type: "string" },
          checkPending: { type: "boolean" },
          maxAgeDays: { type: "integer", minimum: 1 },
          days: { type: "integer", minimum: 1 },
          timeoutMs: { type: "integer", minimum: 1 },
          correctionsFile: { type: "string" },
          pendingFile: { type: "string" },
          memoryFile: { type: "string" },
          dailyLogDir: { type: "string" }
        },
        required: ["action"]
      },
      async execute(_toolCallId, params) {
        const action = asString(params.action);
        if (!action) throw new Error("action is required");
        if (action === "check" && !asString(params.claim)) {
          throw new Error("claim is required for action=check");
        }
        if (action === "recover" && !asString(params.query)) {
          throw new Error("query is required for action=recover");
        }
        if (action === "writeback") {
          if (!asString(params.old)) throw new Error("old is required for action=writeback");
          if (!asString(params.corrected)) throw new Error("corrected is required for action=writeback");
          if (!asString(params.scope)) throw new Error("scope is required for action=writeback");
        }
        if (action === "mark-consolidated" && !asString(params.old)) {
          throw new Error("old is required for action=mark-consolidated");
        }

        const resolved = resolveExecutionConfig(params, api.pluginConfig ?? {});
        const args = buildArgs(action, params, resolved);
        const run = await runPython(resolved.pythonBinary, args, asInteger(params.timeoutMs, DEFAULT_TIMEOUT_MS));
        const payload = {
          ...(run.parsed ?? {}),
          exit_code: run.code,
          stderr: run.stderr?.trim() || undefined
        };
        return shapeResult(action, payload, resolved);
      }
    });
  }
});
