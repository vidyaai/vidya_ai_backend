# Plan: Raise Paper Pass Rate from 60% → 80% by Closing Answer Leaks

## Context

Papers7 and Papers8 (50 questions each, 10 topics × 5 Qs) are generated and auto-reviewed by a Gemini reviewer, then spot-checked by a Claude "manual" reviewer. Answer leaks — diagrams that reveal the very thing the student is asked to identify/compute — are the single dominant failure class after data/label issues.

Measured state (from the logs):

| Run | Total FAIL | answer_leak FAIL | Gemini pass | Claude manual pass |
|---|---|---|---|---|
| papers7 | 34/50 | 9 | 16/50 (32%) | 33/50 (66%) |
| papers8 | 20/50 | 7 | 30/50 (60%) | 32/50 (64%) |

Claude Opus manual review is stricter on leaks than Gemini — it catches leaks Gemini's exception list allows (e.g., "Threshold" line in QEC Q5, spin-momentum locking arrows in Topo Q3, neuromorphic threshold potential Q1, base-editing window CRISPR Q5, labeled shells in Stellar Q5). So the *real* user-facing leak rate is higher than Gemini's 7–9 flags suggest; the 60→80 gap is leak-dominated.

### Papers8 failure breakdown (Claude manual review — 18 failures)

| Question | Failure | Category | Estimated fixable? |
|---|---|---|---|
| QEC Q4 | "Fidelity" label reveals answer | answer_leak (text) | Yes — forbidden list |
| QEC Q5 | "Threshold" label reveals answer | answer_leak (text) | Yes — forbidden list |
| Orbital Q1 | Equal areas visually shown | answer_leak (visual) | Needs template override |
| Topo Q3 | Spin-momentum locking arrows | answer_leak (text) | Yes — forbidden list |
| Topo Q4 | TRIM/band-inversion labels | answer_leak (text) | Yes — forbidden list |
| Neuro Q1 | Threshold potential labeled | answer_leak (text) | Yes — forbidden list |
| Neuro Q4 | Both spike patterns labeled | answer_leak (text) | Yes — forbidden list |
| Crystal Q3 | "(100)" label cut off | readability | Yes — regen quality fix (E) |
| Crystal Q4 | Large dots show absences | answer_leak (visual) | Needs template override |
| Game Q1 | Missing Player 2 labels | missing_labels | Yes — regen quality fix (E) |
| CRISPR Q1 | Too simplistic diagram | quality | Yes — regen quality fix (E) |
| CRISPR Q5 | Base editing window labeled | answer_leak (text) | Yes — forbidden list |
| Plasma Q3 | Drift direction shown | answer_leak (text) | Yes — forbidden list |
| BB84 Q1 | Only 2 of 4 states shown | data_mismatch | Yes — regen quality fix (E) |
| BB84 Q2 | Eavesdropping label | answer_leak (text) | Yes — forbidden list |
| BB84 Q4 | Note-box spoiler | answer_leak (text) | Yes — forbidden list |
| Stellar Q1 | All products labeled | answer_leak (text) | Yes — forbidden list |
| Stellar Q5 | All shells labeled | answer_leak (text) | Yes — forbidden list |

**Summary**: 14 answer leaks (12 text-label, 2 visual-only) + 4 non-leak failures.

### Concrete leak patterns observed
1. **Conclusion-as-legend**: "Pareto Frontier", "Systematic Absences", "Eavesdropping Detection" — the answer is the legend entry. (Game Theory Q5, Crystallography Q4, BB84 Q2/Q4)
2. **Threshold/region labels**: "Threshold line", "Band Inversion Path", "Feasible Region". (QEC Q5, Topo Q4)
3. **Fully-labeled products/structures** when Q is "identify the structures": RuvC/HNH/Bridge Helix for CRISPR Q1; labeled C→Ne→Si→Fe in Stellar Q1; labeled shells in Stellar Q5.
4. **Visual-only leaks** (no text, still tells the answer): equal sectors visually identical in Kepler Q1 (both papers); large dots showing allowed diffraction peaks in Crystallography Q4.
5. **Note-box spoilers**: "Note: creates entanglement, not a clone" in BB84 Q4.

### Where the leaks come from in code
- [diagram_agent.py:24-69](vidya_ai_backend/src/utils/diagram_agent.py#L24-L69) `_extract_required_labels` filters only answer terms found after the verbs `find|calculate|determine|…`. It misses *conceptual* answers ("Pareto Frontier", "band inversion") and visual-only leaks.
- [diagram_agent.py:576-598](vidya_ai_backend/src/utils/diagram_agent.py#L576-L598) `_analyze_single_question` receives the full `question` dict which contains `correctAnswer`, but this value is **never used** during student-diagram generation — only later at [line 1690](vidya_ai_backend/src/utils/diagram_agent.py#L1690) for answer rephrasing and [line 1994](vidya_ai_backend/src/utils/diagram_agent.py#L1994) for answer-key diagram generation.
- [diagram_agent.py:1137](vidya_ai_backend/src/utils/diagram_agent.py#L1137) the student-diagram description is built from question text only; `correct_answer` is never consulted, so the generator has no authoritative list of strings/concepts to avoid.
- [gemini_diagram_reviewer.py:274-289](vidya_ai_backend/src/utils/gemini_diagram_reviewer.py#L274-L289) the exception list is *global* and over-permissive (e.g., "Valence Band" is allowed even when the question asks to identify the valence band). The Gemini override at [lines 546-571](vidya_ai_backend/src/utils/gemini_diagram_reviewer.py#L546-L571) further downgrades `answer_leak` to PASS on keyword match ("standard formula", "well-known", etc.), which explains why Claude manual review flags extra leaks Gemini missed.
- Regen loop at [diagram_agent.py:1450-1573](vidya_ai_backend/src/utils/diagram_agent.py#L1450-L1573) is solid (cumulative leak memory, reference-image passback), but only triggers *after* a leak happens and caps at 5 attempts. Many leaks survive because the first generation didn't know what to avoid and the reviewer exception list greenlights the regen.
- Subject-level "ANSWER HIDING" rules exist in [subject_prompt_registry.py](vidya_ai_backend/src/utils/subject_prompt_registry.py) per subject, but not per-topic, so conceptual answer terms ("Pareto Frontier") aren't forbidden by name.

---

## Strategy

Four coordinated changes:
- **(A)** Stop text-label leaks at generation — answer-aware forbidden list (fixes ~10 of 14 leaks)
- **(B)** Tighten reviewer — per-question forbidden list + narrower leniency override (prevents false PASSes)
- **(C)** Fix visual-only leaks — topic-specific diagram template rules (fixes 2 visual leaks)
- **(D)** Fix non-leak failures — targeted regen quality improvements (fixes 4 remaining)

### A. Answer-aware forbidden-terms list at generation time

**Critical prerequisite**: Thread `correct_answer` into the diagram generation path.
- In `_analyze_single_question` ([diagram_agent.py:576](vidya_ai_backend/src/utils/diagram_agent.py#L576)), extract `correct_answer = question.get("correctAnswer", "")` early (alongside `question_text` at line 597).
- Pass `correct_answer` to the new `_extract_forbidden_terms` function.
- For MCQ questions, also extract the correct option text (not just the index "A"/"B") so the forbidden list contains the actual answer content.

**New function** `_extract_forbidden_terms(question_text, correct_answer, domain) -> list[str]` in [diagram_agent.py](vidya_ai_backend/src/utils/diagram_agent.py) next to `_extract_required_labels` (around line 70).
- Extract noun phrases and named concepts from `correct_answer` using regex (`r"[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*"` for proper nouns, `r"[A-Z]{2,}"` for acronyms).
- Also extract terms the question asks to find/identify/calculate (reuse the verb-target extraction logic from `_extract_required_labels` lines 40-45, but KEEP the matched terms instead of filtering them out).
- Merge with a curated domain-specific never-label set: `pareto frontier`, `nash equilibrium`, `systematic absences`, `band inversion`, `threshold`, `feasible region`, `stable/unstable`, `eavesdropping`, `logical operator`, `spin-momentum locking`, `equal areas`, `base editing window`, `RuvC`, `HNH`, shell element names (`C,O,Ne,Si,Fe`).
- Return deduplicated list, max 20 terms.

**Wire-through** — inject forbidden list at three points:
1. **Description builder** ([diagram_agent.py:1137](vidya_ai_backend/src/utils/diagram_agent.py#L1137)): Append `"\n\nFORBIDDEN LABELS (do not render as text, legend entries, annotations, or note boxes): {', '.join(forbidden_terms)}"` to the description string before passing to any tool.
2. **TikZ generator** ([tikz_generator.py:94-100](vidya_ai_backend/src/utils/tikz_generator.py#L94-L100)): Add a `forbidden_labels: list[str] = []` parameter to the generation function. If non-empty, append a `FORBIDDEN LABEL LIST` section to the system prompt.
3. **Google Diagram generator** ([google_diagram_generator.py:261-265](vidya_ai_backend/src/utils/google_diagram_generator.py#L261-L265)): Same approach — add parameter and append to prompt.
4. **Regen loop** ([diagram_agent.py:1539-1547](vidya_ai_backend/src/utils/diagram_agent.py#L1539-L1547)): Seed `_accumulated_leak_reasons` with the forbidden-terms list at initialization (before the loop starts at line 1458), so even the first regen attempt knows what answer terms to avoid.

### B. Reviewer: per-question forbidden list, tighter leniency

In [gemini_diagram_reviewer.py](vidya_ai_backend/src/utils/gemini_diagram_reviewer.py):

1. **Add `forbidden_labels` parameter** to `review_diagram()` ([line 60](vidya_ai_backend/src/utils/gemini_diagram_reviewer.py#L60)):
   ```python
   async def review_diagram(self, image_bytes, question_text, diagram_description,
                             user_prompt_context="", domain="", diagram_type="",
                             forbidden_labels: list[str] | None = None) -> Dict[str, Any]:
   ```

2. **Inject into the review prompt** ([lines 267-319](vidya_ai_backend/src/utils/gemini_diagram_reviewer.py#L267-L319)): After the ANSWER LEAK CHECK section, add:
   ```
   QUESTION-SPECIFIC FORBIDDEN LABELS (auto-derived from the correct answer):
   {forbidden_labels}
   If ANY of these terms appear as text labels, legend entries, annotations, or note boxes
   in the diagram, this is an AUTOMATIC FAIL (answer_leak) regardless of the exception list above.
   ```

3. **Narrow the leniency override** ([lines 546-571](vidya_ai_backend/src/utils/gemini_diagram_reviewer.py#L546-L571)): Add a guard so the `_lenient_leak_keywords` check does NOT fire when the reviewer's reason mentions any term from `forbidden_labels`. This prevents the override from re-passing leaks the forbidden list explicitly targets.

4. **Wire through from diagram_agent.py**: Update the call at [line 1462](vidya_ai_backend/src/utils/diagram_agent.py#L1462) to pass `forbidden_labels=forbidden_terms`.

### C. Visual-leak rules (fixes Orbital Q1, Crystal Q4)

These two leaks cannot be fixed by text filtering alone — the visual rendering itself reveals the answer.

1. **Kepler equal-areas** (Orbital Q1 — both papers): Add a rule in [subject_prompt_registry.py](vidya_ai_backend/src/utils/subject_prompt_registry.py) physics section:
   > "If the question asks to prove or demonstrate Kepler's second law (equal areas in equal times), draw the elliptical orbit with TWO sectors clearly marked but shade only ONE sector. Label the other sector with '?' or 'Area = ?'. The student must demonstrate they are equal — do NOT draw them visually identical or label both areas."

   Also add this as a FAIL rule in the reviewer prompt ([gemini_diagram_reviewer.py:291-313](vidya_ai_backend/src/utils/gemini_diagram_reviewer.py#L291-L313)):
   > "If the question asks to prove equal areas: both sectors shown with equal shading/size = answer_leak."

2. **Crystallography systematic absences** (Crystal Q4): Add a rule in chemistry section of [subject_prompt_registry.py](vidya_ai_backend/src/utils/subject_prompt_registry.py):
   > "If the question asks to identify systematic absences or forbidden reflections, render ALL candidate reflection positions as same-size, same-style dots with (hkl) coordinate labels. Do NOT use dot size, color, or presence/absence to distinguish allowed from forbidden — the student must determine this."

   Add corresponding reviewer rule:
   > "If the question asks to identify systematic absences: dots that differ in size/color/visibility to show allowed vs forbidden = answer_leak."

3. **Stages/shells/products identification** (Stellar Q1, Q5): Add a rule in physics section:
   > "If the question asks to identify products, stages, or shell compositions in nucleosynthesis: draw the structural layout (layers, arrows, reaction paths) but replace at least the KEY product labels with '?' placeholders. The student must fill in what is produced at each stage."

### D. Non-leak failure fixes (fixes Crystal Q3, Game Q1, CRISPR Q1, BB84 Q1)

These 4 failures are quality/data issues, not answer leaks. Address them by improving the regen loop's handling of specific failure types:

1. **Label readability / truncation** (Crystal Q3 — "(100)" cut off): In [diagram_agent.py](vidya_ai_backend/src/utils/diagram_agent.py) regen fallback for `missing_labels` ([line 1527-1532](vidya_ai_backend/src/utils/diagram_agent.py#L1527-L1532)), add an explicit instruction:
   > "Ensure ALL labels are fully visible and not clipped by diagram boundaries. Use smaller font or reposition labels that are near edges."

2. **Missing structural labels** (Game Q1 — Player 2 actions missing): Already handled by `missing_labels` regen path. The issue is likely that the first generation prompt doesn't list required labels explicitly enough. Fix: in `_extract_required_labels` ([diagram_agent.py:24-69](vidya_ai_backend/src/utils/diagram_agent.py#L24-L69)), add pattern matching for game-theory action labels (`r"(?:actions?|strategies?)\s*(?:are|:)\s*([A-Z][a-z]+(?:\s*(?:and|,)\s*[A-Z][a-z]+)*)"`) to extract them as required labels.

3. **Diagram too simplistic** (CRISPR Q1): In [subject_prompt_registry.py](vidya_ai_backend/src/utils/subject_prompt_registry.py) biochemistry section, add guidance:
   > "For questions about molecular structures of CRISPR-Cas9 (identifying domains, structural features), generate a DETAILED schematic showing at minimum: the Cas9 protein outline, guide RNA, target DNA strand, PAM site, and placeholder labels for key domains the student must identify. Do NOT generate a simple arrow-and-box diagram."

4. **Incomplete diagram content** (BB84 Q1 — only 2 of 4 states): In [subject_prompt_registry.py](vidya_ai_backend/src/utils/subject_prompt_registry.py) cs/quantum section, add:
   > "For BB84 protocol Bloch sphere diagrams, ALWAYS show all four BB84 states: |0⟩, |1⟩, |+⟩, |−⟩ with clear labels. A Bloch sphere with fewer than 4 labeled states is incomplete for BB84."

---

## Files to modify

| File | Changes | Lines affected |
|---|---|---|
| [diagram_agent.py](vidya_ai_backend/src/utils/diagram_agent.py) | New `_extract_forbidden_terms` (~30 lines); extract `correct_answer` at line 597; wire forbidden list into description, tool args, reviewer call, and regen seed | ~70, ~597, ~1137, ~1462, ~1458, ~1527 |
| [gemini_diagram_reviewer.py](vidya_ai_backend/src/utils/gemini_diagram_reviewer.py) | Add `forbidden_labels` param; inject into prompt; guard leniency override; add 3 visual-leak rules | ~60, ~267-319, ~546-571 |
| [tikz_generator.py](vidya_ai_backend/src/utils/tikz_generator.py) | Add `forbidden_labels` param to generation function; append to system prompt | ~94-100 |
| [google_diagram_generator.py](vidya_ai_backend/src/utils/google_diagram_generator.py) | Same as tikz_generator | ~261-265 |
| [subject_prompt_registry.py](vidya_ai_backend/src/utils/subject_prompt_registry.py) | Add visual-leak rules (physics, chemistry); CRISPR detail guidance (biochem); BB84 completeness (cs) | physics section, chemistry section, biochem section, cs section |

**Reuse** (no duplication):
- `_extract_required_labels` ([diagram_agent.py:24](vidya_ai_backend/src/utils/diagram_agent.py#L24)) — reuse its verb-target extraction logic inside `_extract_forbidden_terms` (call internally, keep the matched terms instead of filtering them).
- Existing `_accumulated_leak_reasons` loop at [diagram_agent.py:1514](vidya_ai_backend/src/utils/diagram_agent.py#L1514) — seed the first element from the forbidden list so even attempt 1 has "known answer terms" in its correction block.
- Existing `corrected_description` regen pipeline stays unchanged.

---

## Expected impact

| Change | Fixes | Count |
|---|---|---|
| A. Forbidden-terms list at generation | QEC Q4/Q5, Topo Q3/Q4, Neuro Q1/Q4, CRISPR Q5, Plasma Q3, BB84 Q2/Q4, Stellar Q1/Q5 | ~12 text-label leaks |
| B. Tighter reviewer | Prevents false-PASS on leaks that survive A | +0 new fixes, prevents regressions |
| C. Visual-leak rules | Orbital Q1, Crystal Q4 | 2 visual leaks |
| D. Non-leak quality fixes | Crystal Q3, Game Q1, CRISPR Q1, BB84 Q1 | 4 non-leak failures |
| **Total fixable** | | **18/18** |
| **Risk of over-filtering** (forbidden list catches legitimate structural labels) | | **-1 to -3 regressions** |

**Projected outcome**: 32 current passes + 15 net fixes (18 fixed - 3 regressions) = **47/50 (94%)** best case, **42/50 (84%)** conservative case. Either exceeds 80% target.

**Key risk**: Over-filtering. If the forbidden list bans a term that's also a legitimate structural label (e.g., "RuvC" is an answer for CRISPR Q1 but a needed structural label for CRISPR Q2), it could cause new `missing_labels` failures. Mitigation: the forbidden list is per-question (derived from each question's own `correctAnswer`), not global. A term forbidden for Q1 won't be forbidden for Q2.

---

## Verification

Run before/after on the same 10-topic × 5-Q fixture:

1. **Review-only pass** (fast, ~3 min): `python vidya_ai_backend/question_generation_test/review_only_papers.py --paper 9` (fresh paper number) — expect Gemini `FAIL (answer_leak)` count to drop from 7–9 to ≤2.
2. **Full regen pass** (~75 min): `python vidya_ai_backend/question_generation_test/regen_papers.py --paper 9` — inspect batch_results.json pass rate.
3. **Claude Opus manual review**: re-run the manual_review script on paper 9; target ≥40/50 (80%).
4. **Targeted spot checks**: confirm these specific prior failures are fixed by opening the generated PDFs:
   - Game Theory Q5 (no "Pareto Frontier" legend)
   - Crystallography Q4 (same-size dots; no "Systematic Absences" text)
   - BB84 Q1 (all 4 states shown), Q2 (no eavesdropping label), Q4 (no note-box spoiler)
   - Stellar Q1/Q5 (product/shell names replaced with `?`)
   - Kepler Q1 (one sector shaded, other marked `?`)
   - CRISPR Q1 (detailed molecular schematic, not simplified)
   - Crystal Q3 ("(100)" label fully visible)
5. **Regression check**: confirm legitimate structural labels still render — QEC gate names (Hadamard/CNOT), orbital terms (perihelion), band-structure axes (E_F), Game Theory payoff values — by eyeballing those topics' PDFs.
6. **Over-filtering check**: grep the generation logs for "FORBIDDEN LABELS" and verify no question has >15 forbidden terms (sign of over-extraction). Spot-check 5 questions to confirm forbidden terms are genuinely answer-revealing.

Exit criteria: Claude manual review ≥80% on paper 9 with no topic below 3/5, and no regression in data_mismatch / missing_labels counts vs paper 8 baseline.
