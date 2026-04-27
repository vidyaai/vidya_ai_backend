# DIAGRAM_FIX_PLAN_NEW — Push Pass Rate from 60% → 80%

## Context

Papers10 reproduced the prior 60% baseline (papers8) after I repaired the
ANSWER_LEAK_FIX_PLAN regression that had collapsed papers9 to 34%. The
forbidden-terms pipeline is now correct in principle but bottlenecked by
**LLM compliance**: the diagram-generating LLM ignores the `FORBIDDEN
LABELS` directive in roughly 25% of answer-leak cases, and the planner
LLM sometimes embeds answer terminology directly into the diagram
description it writes (so the generator only sees a leaky description).

Independent audits agree on the ceiling:

| Reviewer | papers10 |
|---|---|
| In-line Gemini (during regen) | 32/50 (64%) |
| `review_only.py` (Gemini, eq-fixed) | 23/50 (46%) |
| `claude_manual_review.py` (Opus, eq-fixed) | 29/50 (58%) |

To push past 60% reliably we need **deterministic enforcement** that does
not depend on LLM compliance — informed by 2025 work on text-to-diagram
grammars (MermaidSeqBench, Flowchart2Mermaid) and Multi-Agent Reflexion
(MAR). The five changes below apply those principles to the existing
pipeline without rewriting the renderers.

The two engines we care about:

- **`engine="nonai"`** (papers10 used this — default): planner LLM writes
  description → code-generator LLM writes TikZ / matplotlib / circuitikz
  / schemdraw source → Python/LaTeX renders to PNG → Gemini reviewer.
- **`engine="ai"`**: Gemini native image generation paints pixels
  directly from the description.

Code-level interventions (#1) only help the nonai path; description-level
(#2) and OCR (#3) help both.

---

## The Five Changes

### #1 — Code-level forbidden-label scrub (highest leverage, ~90 min)

**Where**: New module `src/utils/code_label_scrubber.py`, invoked from
the rendering tools in `src/utils/diagram_tools.py` immediately before
`pdflatex` / `exec` is called on the LLM-generated source.

**What it does**: Intercept the source string the LLM produced
(`tikz_source`, `matplotlib_code`, `circuitikz_source`, `schemdraw_code`)
and run a deterministic regex pass that walks string literals in
label/title/legend positions, then replaces any token matching the
per-question `forbidden_terms` list with `?`.

**Patterns to scrub** (per renderer):

- TikZ / circuitikz:
  - `\node[...] (id) at (x,y) {LITERAL}`
  - `\draw ... node[...] {LITERAL}`
  - `\foreach ... { ... label=LITERAL ...}`
  - `\node[label={LITERAL}] ...`
  - Title / caption macros: `\caption{LITERAL}`, `\title{LITERAL}`
- matplotlib (Python source):
  - `ax.text(x, y, "LITERAL")`
  - `ax.set_title("LITERAL")`, `set_xlabel`, `set_ylabel`
  - `ax.annotate("LITERAL", ...)`
  - `ax.legend(["L1", "L2", ...])` — list literal of strings
  - `plt.title(...)`, `plt.suptitle(...)`
- schemdraw: any `.label("LITERAL")` chained call, plus title/caption
  fields.

**Algorithm**:

```python
def scrub_code(source: str, forbidden: list[str], renderer: str) -> tuple[str, int]:
    """Return (scrubbed_source, num_replacements). Idempotent."""
    forbidden_lower = [f.lower() for f in forbidden if f]
    patterns = _PATTERNS_BY_RENDERER[renderer]   # list of (regex, group_idx)
    n = 0
    for pattern, group_idx in patterns:
        def _replace(m):
            nonlocal n
            literal = m.group(group_idx)
            if any(f in literal.lower() for f in forbidden_lower):
                n += 1
                return m.group(0).replace(literal, "?")
            return m.group(0)
        source = pattern.sub(_replace, source)
    return source, n
```

**Integration points** (file:line in current tree):

- `src/utils/diagram_tools.py:tikz_tool` — after the LLM produces
  `tikz_code`, before the pdflatex subprocess: insert
  `tikz_code, n = scrub_code(tikz_code, forbidden_terms, "tikz")` and
  `logger.info(f"Q{i}: scrubbed {n} forbidden labels from tikz")`.
- `src/utils/diagram_tools.py:circuitikz_tool` — same pattern.
- `src/utils/diagram_tools.py:claude_code_tool` (matplotlib) — after
  Claude returns the matplotlib source string, before `exec`.
- `src/utils/diagram_tools.py:schemdraw_tool` — same.

**Plumbing the forbidden list to the tools**: The list is currently
attached only to `tool_arguments["description"]` as a suffix
(`diagram_agent.py` ~line 1190). To make scrubbing work, we need the
raw list. Add a `forbidden_labels: list[str] | None = None` kwarg to
each tool function signature in `diagram_tools.py`, and at the call
site in `diagram_agent.py` pass `forbidden_labels=_forbidden_terms`
alongside the existing tool args.

**Caveat acknowledged**: The LLM may emit literals via variables
(`label_text = "Forbidden reflections"; ax.text(0,0,label_text)`) which
the regex will miss. Estimate: scrubber catches 80–90% of literals,
which is enough to materially move the pass rate. The remaining 10–20%
is what change #3 (OCR) catches.

**Estimated impact**: +5 to +7 passes.

### #2 — Description-level redaction (~30 min)

**Where**: New helper in `src/utils/diagram_agent.py` adjacent to
`_extract_forbidden_terms`. Called before the description is passed to
any rendering tool.

**What it does**: After `_extract_forbidden_terms(...)` returns the
per-question forbidden list, walk the diagram description string and
substitute each forbidden token with `"?"` (or a generic placeholder
like `"a labeled region"`). This stops the planner LLM from leaking
answer terms into the description in the first place.

**Algorithm**:

```python
def _redact_description(desc: str, forbidden: list[str]) -> str:
    """Substring-replace forbidden tokens with '?' in the description.
    Case-insensitive. Whole-word boundaries to avoid partial matches."""
    redacted = desc
    for term in forbidden:
        if not term: continue
        pattern = re.compile(rf"\b{re.escape(term)}\b", re.IGNORECASE)
        redacted = pattern.sub("?", redacted)
    return redacted
```

**Integration point**: `diagram_agent.py` around line 1180, immediately
before `tool_arguments["description"]` is finalized:

```python
if _forbidden_terms and "description" in tool_arguments:
    tool_arguments = dict(tool_arguments)
    tool_arguments["description"] = _redact_description(
        tool_arguments["description"], _forbidden_terms
    )
    # then append the existing FORBIDDEN LABELS suffix as a directive
    tool_arguments["description"] += build_forbidden_suffix(_forbidden_terms)
```

**Why this matters even with #1**: A planner description like *"Draw a
region labeled 'Forbidden reflections' and another labeled 'Allowed
reflections'"* tells the code-generator LLM to label these regions;
the LLM faithfully writes that code; #1 then strips the literals
leaving `?` placeholders. With #2, the description never asks for
those labels in the first place — the LLM writes cleaner code from the
start, with structurally meaningful diagrams instead of `?`-strewn
ones.

**Helps both engines**: redaction happens before either nonai code-gen
or the AI engine sees the description.

**Estimated impact**: +3 to +5 passes.

### #3 — Post-render OCR scrub with pytesseract (~60 min)

**Where**: New module `src/utils/ocr_scrub.py`, invoked from the regen
loop in `diagram_agent.py` immediately after a tool returns PNG bytes
and before the bytes are passed to the Gemini reviewer.

**What it does**:

1. Run `pytesseract.image_to_data(...)` on the PNG → list of recognised
   text tokens with bounding boxes and confidence scores.
2. Compare each token (case-insensitive substring) against the
   per-question `forbidden_terms` list.
3. If any match: return `(found=True, hits=[(token, bbox), ...])` and
   force the regen loop into a "label-leak detected" branch with the
   bbox info appended to the corrected description (e.g.
   *"Detected forbidden label 'Threshold' at top-right of the legend.
   Remove it and re-render."*).

**Why this is needed even with #1 and #2**:

- AI engine (`engine="ai"`) bypasses #1 entirely — Gemini paints
  pixels, no code to scrub. OCR is the only deterministic defence.
- For nonai, the regex scrubber catches ~80–90% of literals; OCR
  catches the residual cases where the LLM smuggled labels through
  variables, computed strings, or tikz `\foreach` constructions the
  regex didn't anticipate.

**Dependencies**: Add `pytesseract>=0.3.10` and `Pillow` to
`requirements.txt`. Tesseract binary needs `apt install tesseract-ocr`
on the host. Verify in the deployment image.

**Integration point**: `diagram_agent.py` in the regen loop, after
the tool call returns image bytes and before the `reviewer.review_diagram(
image_bytes, ...)` call (currently around line 1612). Pseudocode:

```python
ocr_hit = ocr_scrub_check(image_bytes, _forbidden_terms)
if ocr_hit.found:
    review_result = {
        "passed": False,
        "failure_type": "answer_leak",
        "reason": f"OCR detected forbidden labels: {ocr_hit.hits}",
        "fixable": False,
        "corrected_description": _build_ocr_correction(original_desc, ocr_hit),
    }
else:
    review_result = await reviewer.review_diagram(image_bytes, ...)
```

**Caveat**: OCR adds ~1–2 s per question. Worth it for the deterministic
guarantee. Skip when `forbidden_terms` is empty.

**Estimated impact**: +2 to +3 passes (more on AI-engine runs).

### #4 — Multi-agent Reflexion regen (~45 min)

**Where**: `diagram_agent.py` regen loop, around lines 1640–1680.

**What it does**: Currently each of the 3 regen attempts uses the same
prompt-correction strategy. Inspired by Multi-Agent Reflexion (MAR
2025), each attempt now uses a different *critic perspective*:

- **Attempt 1 — leak-critic**: focus the corrected description on
  removing answer-revealing labels. Use the existing accumulated leak
  reasons.
- **Attempt 2 — type-critic**: focus on whether the diagram is the
  *right type* (sequence diagram, BCC unit cell, Bloch sphere, ...).
  Pass `WRONG/CORRECT/VISUAL FEATURES/DO NOT` quad from the Gemini
  reviewer's `wrong_type` corrections.
- **Attempt 3 — readability-critic**: focus on layout, label
  overlap, font size. Use prompts like *"Render with explicit
  `[xshift=8pt]` offsets, use `\footnotesize`, ensure no two labels
  share a position."*

**Mechanism**: A new function `_build_critic_corrected_description(
attempt: int, original_desc: str, review_result: dict) -> str` chooses
which template to apply based on `attempt` and the failure type. The
existing `_accumulated_leak_reasons` list stays as the cumulative
memory.

**Tool rotation**: Combined with the existing `fallback_router`, also
prefer a different rendering tool per attempt
(tikz → claude_code → schemdraw) so we don't hit the same LLM/renderer
quirk three times in a row.

**Estimated impact**: +1 to +2 passes.

### #5 — Raise answer-leak regen budget 3 → 6 (~5 min)

**Where**: `diagram_agent.py` — the hardcoded `MAX_REGEN_ATTEMPTS = 3`
constant near the regen loop.

**What it does**: With #4's critic rotation we have more useful angles
than 3 attempts can express. Raising to 6 lets us cycle:
leak → type → readability → leak (different tool) → type (different
tool) → readability (different tool).

**Cost**: Up to 2× generation time on the worst-case path.
Counter-balanced by #1+#2 reducing how often we even hit the regen
loop.

**Estimated impact**: +1 pass (statistically — gives stuck questions a
better chance to converge).

---

## Files to Modify

| File | Why |
|---|---|
| `src/utils/code_label_scrubber.py` *(new)* | Implements #1's regex scrubber per renderer. |
| `src/utils/ocr_scrub.py` *(new)* | Implements #3's pytesseract wrapper + bbox reporting. |
| `src/utils/diagram_tools.py` | Plumb `forbidden_labels` into all 4 tool signatures; call `scrub_code(...)` immediately before render. |
| `src/utils/diagram_agent.py` | Add `_redact_description` (#2); call OCR scrub before reviewer (#3); critic rotation + budget bump (#4, #5). |
| `requirements.txt` | Add `pytesseract`, `Pillow` (if absent). |
| `docs/DIAGRAM_FIX_PLAN_NEW.md` *(new)* | This plan. |

## Files to Reuse (do not duplicate)

- `_extract_forbidden_terms()` and `_GLOBAL_FORBIDDEN_CONCEPTS` —
  `src/utils/diagram_agent.py:99-150`. The scrubber and redactor consume
  this list; do not re-derive it.
- `GeminiDiagramReviewer.review_diagram()` —
  `src/utils/gemini_diagram_reviewer.py:60`. Already accepts
  `forbidden_labels`; #3's OCR step short-circuits it on positive hits
  but otherwise leaves the call chain untouched.
- `fallback_router.SubjectSpecificFallbackRouter` —
  `src/utils/fallback_router.py`. Use its existing tool-selection logic
  for #4's rotation rather than writing a new selector.
- `_accumulated_leak_reasons` list —
  `src/utils/diagram_agent.py:1549`. Keep as the long-term memory
  across critic-perspective attempts in #4.
- `pdf_generator.process_question_text_with_equations()` —
  `src/utils/pdf_generator.py:543`. Reference implementation for
  `<eq>` substitution that the (already-shipped) review-script fix
  matched.

## Verification

After implementing each change, run:

```bash
cd /home/ubuntu/Pingu/vidya_ai_backend

# 1. Smoke tests for the new helpers
python -m pytest tests/test_code_label_scrubber.py -v   # (write 6-8 cases per renderer)
python -m pytest tests/test_ocr_scrub.py -v             # (use a generated PNG with known label)

# 2. Full benchmark
python question_generation_test/run_batch_papers.py question_papers11 \
    > /tmp/regen_papers11.log 2>&1
python question_generation_test/review_only.py question_papers11 \
    > /tmp/review_only_papers11.log 2>&1
python question_generation_test/claude_manual_review.py question_papers11 \
    > /tmp/claude_manual_review_papers11.log 2>&1
```

Compare against papers10 baselines:

| Reviewer | papers10 baseline | papers11 target |
|---|---|---|
| In-line Gemini | 32/50 (64%) | ≥ 40/50 (80%) |
| `review_only.py` (eq-fixed) | 23/50 (46%) | ≥ 30/50 (60%) |
| `claude_manual_review.py` (eq-fixed) | 29/50 (58%) | ≥ 36/50 (72%) |

**Per-fix telemetry to watch in the log**:

- `Q{i}: scrubbed N forbidden labels from {renderer}` — confirms #1 fired.
- `Q{i}: redacted description (N tokens)` — confirms #2 fired.
- `Q{i}: OCR detected forbidden labels: [...]` — confirms #3 caught a residual leak.
- `Q{i}: Regen attempt N/6 using {critic} critic via {tool}` — confirms #4+#5 rotated.

**Spot checks** (manual review of the resulting PDFs):

- Crystal Q3: Miller indices `(100)/(110)/(111)` should be replaced with `?` (was the dominant Crystallography failure).
- BB84 Q3: graph title should not contain "Eavesdropping" (regex would catch
  `\title{Eavesdropping Detection}` → `\title{?}`).
- Stellar Q5: onion-shell layer labels (Hydrogen, Helium, …) should be `?` for the layers students must identify.
- Neuro Q1: legend should not contain "Threshold".

## Order of Operations

1. **#2 (description redaction)** — smallest change, exercises the
   forbidden-list plumbing, easy to revert. Land + commit + measure.
2. **#1 (code scrub)** — biggest impact. Land in same branch but
   commit separately so attribution is clear when comparing pass-rate
   deltas.
3. **#5 (budget bump)** — trivial, land with #4.
4. **#4 (critic rotation)** — non-trivial logic; review carefully.
5. **#3 (OCR)** — last because it adds a system dependency
   (Tesseract binary) and matters most for AI-engine deployments,
   which papers10–11 do not exercise.

After every step, regenerate the failing subset only (Crystal, BB84,
Plasma, Stellar) — about 20 questions, ~25 min — to triangulate which
fix moved which failure. Run the full 50-question regen only at the
end.

## Rollback

Each step is a separate commit on `vidya_ai_diagram_fix`. If any change
*lowers* the pass rate, revert that single commit; the others are
independent. The repo state is pushed to GitHub up to `e333a31`, so
nothing is lost.

## Realistic Outcome Estimate

| Scenario | papers11 in-line | papers11 audit (review_only) |
|---|---|---|
| All 5 fire as projected | 88–94% | 72–82% |
| Half land cleanly | 74–80% | 56–66% |
| Honest worst case | 64–70% | 46–52% |

**80% live** is reachable; **80% on the strict audit** is harder and
not guaranteed by these five changes alone — that target may require
the schema-based approach (full Mermaid/D2 path) we deferred.
