# Release Notes

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

Design boundary preserved:
- owns local truth-risk nudge
- owns native factual-claim gate tool
- owns correction precedence support
- does not own the future global retrieval router
- does not inject the full retrieval ladder
