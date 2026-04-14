# Release Notes

## 1.2.0

Final scoring calibration and routing alignment.

What changed:
- `recover.py` surface trust values now match the intended spec more closely: `pending_actions=0.90`, `scoped_daily_memory=0.70`, `durable_memory=0.60`, `procedural_memory=0.50`
- `next_action` now follows the final resolved strength outcome instead of re-imposing a separate `score >= 0.70` gate after a result is already classified as strong and anchored
- strong usable correction anchors in the 0.66–0.69 range no longer fall through to `ask_or_escalate` just because they sit below the old direct-answer cliff
- bare hour forms like `5pm` are now recognized as time signals in recover scoring instead of being treated weaker than `5:00pm`
- sentence-initial capital stopwords like `The` are no longer misread as named subjects in full-sentence claims, which removes a false `subject_alignment_failed` path on ordinary correction sentences
- release keeps the existing hard safety caps, host escalation hints, and diagnostic-noise demotion intact

Design boundary preserved:
- this is still deterministic ranking, not semantic retrieval
- the recall gap remains a separate retrieval-layer problem, not something hidden by score inflation
- correction precedence still remains above score

## 1.1.0

Deterministic recover scoring layer.

What changed:
- `recover.py` now computes a transparent weighted composite score for already-retrieved candidates instead of relying only on coarse heuristic ordering
- six deterministic score signals added: `subject_alignment`, `surface`, `specificity`, `temporal`, `context_focus`, and `claim_type_match`
- score bands added: `strong`, `medium`, `weak`, `none`
- hard safety gates still cap results downward when strict binding, subject alignment, ambient collision, unusable-anchor, or meta-noise checks fail
- result entries now include `score`, `score_breakdown`, `score_strength`, and optional `strength_cap_reason`
- top-level recover output now includes `best_score` and a host-facing `next_action`
- ranking now prefers usable anchors, final strength, and composite score before fallback tie-breakers
- `host_routing_hint` now fires for weak results and borderline medium results, not only for fully empty recovery
- diagnostic and validation residue is down-ranked more aggressively to reduce subject-bleed false positives

Design boundary preserved:
- deterministic only, no embeddings, NER model, or LLM rescoring
- correction precedence remains above score
- retrieval ladder ownership still stays outside this plugin

## 1.0.0

First standalone plugin package release.

What changed:
- standalone plugin packaging
- bundled skill support
- bundled runtime prompts
- bundled Python scripts
- narrow `before_prompt_build` truth-risk hook
- native `truth_recovery` tool
- manifest kept as the canonical config schema source
- `distill` kept runtime-only

Strengthening pass on the staged `to_publish` copy:
- widened structured correction capture beyond `not X, but Y` to also cover `it's X, not Y`, `should be X not Y`, `I mean X not Y`, interruption forms like `wait, X not Y`, and guarded bare `X not Y`
- added confidence-tiered correction capture handling so wider phrasing support does not imply wider auto-write behavior
- structured writeback entries can now persist `capture_confidence` and `capture_reason`
- `check` now emits `next_action` for stronger host-side control flow
- `recover` now emits optional `host_routing_hint` alongside portable surface suggestions
- subject-focused direct factual lines can promote local recovery results to strong anchors without widening into fuzzy retrieval
- README and INSTALL were updated to document the new capture fields, confidence tiers, authoritative correction-surface rule, and the package-vs-compatibility naming story before upstream handoff
- install-path examples now use the operator-facing package name `truth-control-claw` instead of the stale legacy folder naming

Design boundary preserved:
- owns local truth-risk nudge
- owns native factual-claim gate tool
- owns correction precedence support
- does not own the future global retrieval router
- does not inject the full retrieval ladder
