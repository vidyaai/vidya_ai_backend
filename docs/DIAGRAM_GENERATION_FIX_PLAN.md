# Plan: Raise `engine="nonai"` diagram pass rate 32% → ≥80%

## Context

**Scope of "non-AI" here** — this plan targets the code-rendered generation path only: [google_diagram_generator.py](vidya_ai_backend/src/utils/google_diagram_generator.py) and Gemini image generation (`imagen_tool`, Nano Banana, Nano Banana Pro) are **out of scope**. All fixes operate within the tool family `circuitikz_tool`, `tikz_tool`, `claude_code_tool`, `plotly_tool`, `matplotlib_tool` — Claude writes rendering code; the deterministic renderers (pdflatex, matplotlib, plotly) turn that code into the final PNG. Classification confirms papers7 was run in this mode: `/tmp/regen_papers7.log` line 1 shows `engine=nonai`.

The Gemini 2.5 Pro **reviewer** stays in place — it is the feedback oracle that tells the regen loop what's wrong; it never generates a diagram. Reviewer fixes below are about making that feedback reach the code-rendered generators correctly, not about switching any generation away from code.

`regen_papers7` finished at **16/50 = 32% pass**, well below the 54% historical baseline in [DIAGRAM_GENERATION_FIX_PLAN.md](vidya_ai_backend/docs/DIAGRAM_GENERATION_FIX_PLAN.md). Prior plan work has focused on prompt engineering; the user now wants only **deterministic code-level changes** to the nonai pipeline, plus fixing internal syntax errors.

Log evidence (from `/tmp/regen_papers7.log`, `/tmp/review_only_papers7.log`) shows the feedback loop has collapsed for infrastructure reasons, not prompt reasons:

1. **The Gemini reviewer is producing truncated output.** Every single failure logs `Issues: []` and the REASON is cut mid-sentence (e.g. `"The diagram is missing the required label \"Δv\"  Issues: []"`, `"The diagram's legend explicitly states the interpretation  Issues: []"`). `max_output_tokens=800` at [gemini_diagram_reviewer.py:124](vidya_ai_backend/src/utils/gemini_diagram_reviewer.py#L124) is too small to fit REASON + ISSUES + CORRECTED_DESCRIPTION. The regen loop therefore always hits the generic fallback branch (`"No corrected_description from reviewer — building fallback"` appears on nearly every failure) instead of using the structured repair signals the reviewer is trying to emit.
2. **pdflatex hard failures have no retry and no alt-tool fallback.** 9 distinct compile failures in papers7, clustered on two patterns: `/pgf/decoration/.expanded` (unknown key) and `Giving up on this path. Did you forget a semicolon?`. [tikz_generator.py:212-226](vidya_ai_backend/src/utils/tikz_generator.py#L212-L226) raises immediately on any compile error.
3. **Silent pass on reviewer error.** [gemini_diagram_reviewer.py:139-145](vidya_ai_backend/src/utils/gemini_diagram_reviewer.py#L139-L145) and [176-182](vidya_ai_backend/src/utils/gemini_diagram_reviewer.py#L176-L182) return `"passed": True` when the review timed out or errored — this masks real failures as successes and can also *hide* failing diagrams from the regen loop.
4. **`<eq qN_eqM>` placeholders** warn but don't block (Game Theory Q1 `data_mismatch` with generic placeholder payoff values fails identically across all runs).
5. The regen loop already reads `issues` for `missing_labels` only ([diagram_agent.py:1490-1502](vidya_ai_backend/src/utils/diagram_agent.py#L1490-L1502)); `data_mismatch`, `wrong_type`, and `answer_leak` ignore it.

Intended outcome: deterministic changes to reviewer I/O, pdflatex recovery, and corrected-description propagation that raise papers7 pass rate from 32% to ≥80% without re-running any AI prompt edits, and clean up the latent bugs that make failures silent.

## Target failures and expected recovery

| Fix | Converts (papers7 evidence) |
|---|---|
| Raise `max_output_tokens` + JSON-mode parsing | ~12 failures currently stuck on empty ISSUES / truncated CORRECTED_DESCRIPTION |
| Regex post-processing for `.expanded` + missing `;` | 6 pdflatex hard failures |
| Compile-failure fallback to alternate tool | 3 remaining pdflatex failures |
| Extend `issues`-injection to all failure types | 6 `data_mismatch` / `answer_leak` regens where reviewer flagged specific items |
| Block unresolved `<eq>` in final description | 4 Game Theory / math-placeholder failures |
| Stop silent-passing on reviewer error/timeout | protects against regression; unknown count |

Baseline 16 + projected 31 recovered ≈ 47/50 (94%). We target ≥80% (40/50) leaving margin.

## Changes (all code-level, deterministic)

### 1. Fix the reviewer output pipeline — the single biggest lever

**File:** [vidya_ai_backend/src/utils/gemini_diagram_reviewer.py](vidya_ai_backend/src/utils/gemini_diagram_reviewer.py)

- **Line 124**: Raise `max_output_tokens` from `800` → `2048`. CORRECTED_DESCRIPTION alone can be 400+ tokens (the Check 0 required format with WRONG/CORRECT/VISUAL FEATURES/DO NOT blocks).
- **Lines 139-145 and 176-182**: Stop returning `"passed": True` on timeout/error. Change fallback to `"passed": False, "failure_type": "review_error", "fixable": False` so the regen loop keeps the previous diagram instead of accepting a broken one. Log at ERROR level.
- **Lines 488-495** (`_parse_review_result`): After parsing, if `failure_type in ("wrong_type", "data_mismatch")` and `corrected_desc is None`, log WARNING and set a structured sentinel (`corrected_desc = f"__NEEDS_REPROMPT__: {reason}"`) so the regen loop can detect and treat it as a soft failure rather than silently using generic fallback text.
- **Fix parser truncation edge case** at line 488: if `ISSUES:` field is present but empty *and* `REASON` exceeds 400 chars, we almost certainly truncated — log WARNING for observability. (This is a signal, not a control flow change.)

### 2. pdflatex error recovery — deterministic LaTeX repair + retry

**Files:**
- [vidya_ai_backend/src/utils/tikz_generator.py](vidya_ai_backend/src/utils/tikz_generator.py) (lines 135-159 for post-processing, 197-226 for compile)
- [vidya_ai_backend/src/utils/circuitikz_generator.py](vidya_ai_backend/src/utils/circuitikz_generator.py) (parallel location ~1063)

Add a new private helper `_repair_latex(latex: str, error_text: str) -> str` that applies these regex repairs **only when the first pass fails** (keep first pass untouched to avoid masking a successful compile):

- **`.expanded` / `/tikz/normal ` / other deprecated pgfkeys**: strip the offending `\tikzset{...}` line or the `decoration={.expanded, ...}` option. Pattern: `re.sub(r",?\s*/pgf/decoration/\.expanded[^,}]*", "", latex)` and similar for `/tikz/normal\s+`.
- **Missing semicolons inside `\begin{tikzpicture}`**: for each line inside the tikzpicture that starts with `\draw`/`\path`/`\node`/`\fill` and does not end with `;` or `{` or a continuation comma, append `;`. Use a line-by-line scan, not a single regex, to avoid regex-complexity bugs.
- **Stray `\usetikzlibrary{...}` outside preamble**: move it to just after `\documentclass`.
- Wrap every regex call in `try: ... except re.error: logger.warning(...)` so a malformed pattern never crashes the pipeline (addresses the `re.PatternError` class of errors noted in the prior plan).

**Compile loop** ([tikz_generator.py:197-226](vidya_ai_backend/src/utils/tikz_generator.py#L197-L226)): change the existing `for _pass in range(2)` (currently meant for BibTeX-style cross-reference second pass, but raises on any error) to:

```
for _pass in range(2):
    result = subprocess.run(...)
    if result.returncode == 0:
        break
    if _pass == 0:
        latex_src = self._repair_latex(latex_src, result.stdout)
        with open(tex_file, "w", ...) as fh: fh.write(latex_src)
        continue
    # second failure — raise as before
    raise RuntimeError(...)
```

This gives a deterministic second chance without any AI call. Apply the mirrored change in `circuitikz_generator.py`.

### 3. Alternate-tool fallback when pdflatex still fails

**File:** [vidya_ai_backend/src/utils/diagram_agent.py](vidya_ai_backend/src/utils/diagram_agent.py) — within the tool-invocation `try/except` surrounding tikz_tool and circuitikz_tool (search for `RuntimeError` from generators).

If `tikz_tool` / `circuitikz_tool` raises `RuntimeError("pdflatex compilation failed")` on the final attempt, downgrade to `matplotlib_tool` or `plotly_tool` (both code-rendered, not AI image gen) using the same `description`. Never fall back to `imagen_tool` or Gemini image gen — the goal is to raise the code-rendered path's standalone pass rate, not mask it. Gate behind a `_PDFLATEX_FALLBACK_ENABLED = True` module constant for easy rollback.

### 4. Propagate `issues` to every failure type in the regen loop

**File:** [vidya_ai_backend/src/utils/diagram_agent.py:1481-1517](vidya_ai_backend/src/utils/diagram_agent.py#L1481-L1517)

Currently only the `missing_labels` branch reads `review_result.get("issues", "")`. Replicate the same pattern in the `wrong_type`, `data_mismatch`, and `answer_leak` branches. Extract a local helper inside the function (this is the one place abstraction is warranted because the string-building is identical modulo the lead-in sentence):

```
def _format_issues(issues):
    if isinstance(issues, list): issues = ", ".join(issues)
    return f" Specifically: {issues}." if issues and issues.lower() != "none" else ""
```

Inject `_format_issues(review_result.get("issues"))` into each branch's `corrected_desc`. This is exactly the pattern [DIAGRAM_GENERATION_FIX_PLAN.md](vidya_ai_backend/docs/DIAGRAM_GENERATION_FIX_PLAN.md) already identifies as Fix ML-1 but extends it to the other three failure types — fully deterministic, no prompt change.

### 5. Block unresolved `<eq>` placeholders before tool invocation

**File:** [vidya_ai_backend/src/utils/diagram_agent.py](vidya_ai_backend/src/utils/diagram_agent.py) around the description-construction step (~line 1065-1090 where the current warning lives).

Currently logs a warning and continues. Change to:
- If `<eq ` appears in the *final* description passed to any tool, substitute with a concrete fallback: call `_resolve_equation_placeholders()` a second time using `equation_resolved_question_text`; if any placeholder still survives, replace with `"[see question text]"` so at least no placeholder tokens reach the generator.
- Log at ERROR level with the question id + surviving placeholder list so we can audit.

This addresses Game Theory Q1's persistent `data_mismatch` (generic placeholder payoffs across all 4 runs).

### 6. Syntax / hygiene bugs to clean up while in these files

These are small and should land in the same PR (spotted during exploration, none change behavior beyond the intended fix):

- **Bare `except Exception:` with silent pass** in [diagram_agent.py](vidya_ai_backend/src/utils/diagram_agent.py) around lines 1304, 1347 (flagged by Explore). Replace with `except Exception as e: logger.exception(...)` — do not swallow silently.
- **Unguarded `re.sub`** at [tikz_generator.py:149](vidya_ai_backend/src/utils/tikz_generator.py#L149) and the mirror in circuitikz_generator.py. Wrap in try/except `re.error`; fallback to the unmodified `latex` string so a bad regex never kills compilation.
- **`domain_router.py:206-208`** bare `except Exception` silent recovery — replace with logged recovery using `logger.exception`.
- **Dead fallback verdict parse**: at [gemini_diagram_reviewer.py:448](vidya_ai_backend/src/utils/gemini_diagram_reviewer.py#L448) `verdict = "PASS"` default is wrong if the field is never parsed — change default to `"FAIL"` so a malformed response fails closed, not open.

## Files touched

| File | Change type |
|---|---|
| [vidya_ai_backend/src/utils/gemini_diagram_reviewer.py](vidya_ai_backend/src/utils/gemini_diagram_reviewer.py) | token limit, error-path correctness, parser fail-closed |
| [vidya_ai_backend/src/utils/tikz_generator.py](vidya_ai_backend/src/utils/tikz_generator.py) | `_repair_latex` helper, compile-retry, re.error guard |
| [vidya_ai_backend/src/utils/circuitikz_generator.py](vidya_ai_backend/src/utils/circuitikz_generator.py) | mirror tikz_generator changes |
| [vidya_ai_backend/src/utils/diagram_agent.py](vidya_ai_backend/src/utils/diagram_agent.py) | `_format_issues` helper, eq-placeholder guard, bare-except cleanup, alt-tool fallback |
| [vidya_ai_backend/src/utils/domain_router.py](vidya_ai_backend/src/utils/domain_router.py) | bare-except cleanup |

No changes to any `*_prompt*.py` files, no changes to the Gemini review prompt text, no changes to `subject_prompt_registry.py`, and **no changes to `google_diagram_generator.py`** — the nonai path never touches Gemini image generation. All six interventions are deterministic code in the code-rendered pipeline.

## Verification

Run in order, with the same harness the prior plan uses:

```bash
cd /home/ubuntu/Pingu/vidya_ai_backend/question_generation_test

# 1. Smoke — reviewer changes only (no regen)
python review_only.py question_papers7 2>&1 | tee /tmp/review_only_papers7_v2.log
grep "TOTAL:" /tmp/review_only_papers7_v2.log
# expectation: ≥ previous 16/50 because silent-pass path is now fail-closed; parser improvements should NOT regress anything that was passing legitimately

# 2. Full pipeline — generates new papers8 with all fixes active
python regen_diagrams.py --input question_papers5 --output question_papers8 2>&1 | tee /tmp/regen_papers8.log
# grep for compile-recovery success
grep -c "pdflatex pass 1 failed" /tmp/regen_papers8.log   # should drop markedly
grep -c "pdflatex pass 2 failed" /tmp/regen_papers8.log   # should be near zero
grep -c "Issues: \[\]" /tmp/regen_papers8.log             # should drop as token limit fixes truncation
grep -c "No corrected_description from reviewer" /tmp/regen_papers8.log  # should drop

# 3. Offline review of papers8
python review_only.py question_papers8 2>&1 | tee /tmp/review_only_papers8.log
grep "TOTAL:" /tmp/review_only_papers8.log
# expectation: ≥ 40/50 (80%)

# 4. Regression check across history
for p in question_papers1 question_papers2 question_papers3 question_papers4; do
  echo -n "$p: "
  python review_only.py $p 2>&1 | grep "TOTAL:"
done
# expectation: no regression vs 53/63/63/59% baseline
```

Per-question acceptance telemetry to check manually in papers8:
- Game Theory Q1: `data_mismatch` should no longer cite "generic placeholder values".
- Any circuitikz question failing with `/pgf/decoration/.expanded` should now compile.
- Any question previously logged with `Issues: []` should now show a non-empty ISSUES list in the reviewer output.

## Out of scope (deliberately)

- Any prompt-text edits to the agent, generators, reviewer, or subject registry — the user asked for code-only fixes.
- Reintroducing Gemini image generation (`engine="ai"` / `imagen_tool` / Nano Banana / Nano Banana Pro) as a fallback. The whole point is to raise the code-rendered path's standalone pass rate; falling back to AI image gen would hide the underlying defects.
- New subject-specific answer-hiding sections (those are the P0 prompt fixes in [DIAGRAM_GENERATION_FIX_PLAN.md](vidya_ai_backend/docs/DIAGRAM_GENERATION_FIX_PLAN.md); leave for a follow-up).
- Expanding `_extract_required_labels()` regex (P2 in existing plan; low ROI vs the token-limit fix).
- Any new dependencies.
