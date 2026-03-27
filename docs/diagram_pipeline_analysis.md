# Gemini Diagram Review Pipeline - Complete Analysis

## PART 1: IMPORTS & INSTANTIATION

**Import Location**: [diagram_agent.py](src/utils/diagram_agent.py#L99)
- Line 99: `from utils.gemini_diagram_reviewer import GeminiDiagramReviewer`

**Instantiation**: [diagram_agent.py](src/utils/diagram_agent.py#L101)
- Line 101: `self.reviewer = GeminiDiagramReviewer()` (in `__init__` method, ~lines 90-115)
- Context: Uses Gemini 2.5 Pro as unified reviewer for ai/nonai/fallback flows

---

## PART 2: REVIEW_DIAGRAM METHOD SIGNATURE

**Class**: `GeminiDiagramReviewer` in [gemini_diagram_reviewer.py](src/utils/gemini_diagram_reviewer.py)

**Method**: `async def review_diagram()` at line ~65

**Parameters**:
```python
review_result = await self.reviewer.review_diagram(
    image_bytes=image_bytes_for_review,          # PNG bytes (from _image_bytes or S3 download)
    question_text=clean_question_for_review,      # Question (with <eq> placeholders stripped)
    diagram_description=description_for_review,   # Tool description used to generate
    user_prompt_context=getattr(self, "_generation_prompt", ""),  # Original assignment context
    domain=q_domain,                              # e.g., "electrical", "general"
    diagram_type=q_diagram_type,                  # e.g., "circuit_schematic", "diagram"
)
```

**Return Dict**:
```python
{
    "passed": bool,                           # True if diagram acceptable
    "reason": str,                            # Explanation of verdict
    "corrected_description": str | None,      # Better description if failed
    "issues": list[str],                      # Specific problems found
    "fixable": bool                           # Text/label errors (vs structural)
}
```

---

## PART 3: IMAGE BYTES EXTRACTION PATTERN

**Location 1 - Imagen Retry Loop** (lines 647-671 in `_analyze_single_question`):
```python
# Line 647: Extract from tool response
_attempt_bytes = diagram_data.get("_image_bytes")

# Lines 663-670: Primary source (from tool) or fallback (S3 download)
image_bytes_for_review = _attempt_bytes
if image_bytes_for_review is None:
    # Fallback: download from S3 presigned URL
    try:
        import requests as _req
        resp = _req.get(diagram_data["s3_url"], timeout=15)
        if resp.status_code == 200:
            image_bytes_for_review = resp.content
    except Exception as dl_err:
        logger.warning(f"Could not download Gemini diagram for review: {dl_err}")
```

**Location 2 - Non-AI Review** (lines 1138-1153 in `_analyze_single_question`):
```python
# Line 1138: Extract from tool response
image_bytes_for_review = diagram_data.pop("_image_bytes", None)

# Lines 1143-1152: Same fallback pattern (S3 download)
if image_bytes_for_review is None:
    try:
        import requests as _req
        resp = _req.get(diagram_data["s3_url"], timeout=15)
        if resp.status_code == 200:
            image_bytes_for_review = resp.content
    except Exception as dl_err:
        logger.warning(f"Could not download diagram for review: {dl_err}")
```

**Pattern**: Always use `_image_bytes` first (fast, in-memory), fall back to S3 download if missing.

---

## PART 4: GEMINI REVIEW IN _ANALYZE_SINGLE_QUESTION

### 4A: IMAGEN RETRY LOOP (engine=ai or engine=both)
**Location**: Lines 568-790

**Retry Configuration**:
- Line 568: `max_imagen_attempts = 3`
- Line 569: `imagen_accepted = False`
- Line 570: `last_image_bytes = None` (tracks bytes for fix-vs-regen decision)
- Line 572: `dimension_failures = 0` (tracks dimension/label-related failures)

**Step 1: Generate Image** (lines 608-640)
```python
if attempt == 1 or last_image_bytes is None:
    # First attempt or no fixable image -- GENERATE FROM SCRATCH
    diagram_data = await self.diagram_tools.execute_tool_call(
        tool_name="imagen_tool",
        tool_arguments={"description": current_description, "subject": self.subject},
        assignment_id=assignment_id,
        question_idx=question_idx,
        question_text=equation_resolved_question_text,
    )
else:
    # FIXABLE IMAGE EXISTS -- SEND BACK FOR CORRECTION
    logger.info(f"Fixing existing diagram (attempt {attempt}) -- issues: {last_review_issues[:120]}")
    diagram_data = await self.diagram_tools.imagen_fix_tool(
        image_bytes=last_image_bytes,
        issues=last_review_result.get("issues", []),
        reason=last_review_result.get("reason", ""),
        original_description=current_description,
        assignment_id=assignment_id,
        question_idx=question_idx,
        question_text=equation_resolved_question_text,
    )
```

**Step 2: Dimension Failure Detection on 3rd Attempt** (lines 589-606)
```python
# On 3rd attempt, if 2+ dimension/label failures, switch to SYMBOLIC VARIABLE NAMES
if attempt == max_imagen_attempts and dimension_failures >= 2:
    current_description += (
        "\n\nIMPORTANT - USE SYMBOLIC LABELS INSTEAD OF NUMERIC DIMENSIONS:\n"
        "Do NOT write specific numeric dimension values on the diagram.\n"
        "Instead, use symbolic variable names for ALL dimensions, e.g.:\n"
        "  - W_chip or W_silicon (for chip width)\n"
        "  - L_chip or L_silicon (for chip length)\n"
        "  - t_chip or t_silicon (for chip thickness)\n"
        # ... more guidance ...
    )
```

**Step 3: Review the Generated Image** (lines 676-760)
```python
if image_bytes_for_review:
    # Line 682: Use CURRENT description (may be corrected), not original
    description_for_review = current_description

    # Line 685-689: Strip <eq> placeholders to prevent false label-mismatch failures
    clean_question_for_review = re.sub(r"<eq\s+\S+>", "", equation_resolved_question_text).strip()

    # LINE 686-693: GEMINI REVIEW CALL
    review_result = await self.reviewer.review_diagram(
        image_bytes=image_bytes_for_review,
        question_text=clean_question_for_review,
        diagram_description=description_for_review,
        user_prompt_context=getattr(self, "_generation_prompt", ""),
        domain=q_domain,
        diagram_type=q_diagram_type,
    )
```

**Step 4: PASS vs FAIL logic** (lines 695-777)

**On PASS** (lines 695-707):
```python
if review_result["passed"]:
    logger.info(f"Gemini diagram PASSED review on attempt {attempt} for Q{question_idx}: {review_result['reason'][:100]}")

    # For engine=both, keep AI bytes for stitching later
    if self.engine == "both":
        _ai_image_bytes_for_stitch = image_bytes_for_review

    # Remove _image_bytes before attaching to question (transient key)
    diagram_data.pop("_image_bytes", None)
    imagen_accepted = True
    break  # EXIT RETRY LOOP
```

**On FAIL** (lines 709-760):
```python
else:
    is_fixable = review_result.get("fixable", False)
    last_review_issues = ", ".join(review_result.get("issues", []))
    last_review_result = review_result

    # DIMENSION/LABEL FAILURE DETECTION (lines 717-738)
    _reason_lower = review_result.get("reason", "").lower()
    _issues_lower = last_review_issues.lower()
    _dim_keywords = ["dimension", "label", "unit", "thickness", "width",
                     "conflicting", "duplicate", "wrong axis", "mm", "cm"]
    if any(kw in _reason_lower or kw in _issues_lower for kw in _dim_keywords):
        dimension_failures += 1
        logger.info(f"Dimension-related failure #{dimension_failures} for Q{question_idx}")

    logger.warning(f"Gemini diagram FAILED review on attempt {attempt}/{max_imagen_attempts} "
                   f"for Q{question_idx} (fixable={is_fixable}): {review_result['reason'][:120]}")

    # FIXABLE VS STRUCTURAL DECISION (lines 740-766)
    if is_fixable:
        # ✓ Structure is good, just TEXT/LABEL/UNIT issues
        # Keep the image bytes so next iteration uses IMAGEN_FIX_TOOL
        last_image_bytes = image_bytes_for_review
        logger.info(f"Diagram is fixable -- will send back for text correction on next attempt")
    else:
        # ✗ Structural issue -- need FULL REGENERATION
        last_image_bytes = None  # Reset so next attempt regenerates from scratch
        corrected = review_result.get("corrected_description")
        if corrected:
            imagen_description = corrected  # Update description for next iteration
            logger.info(f"Structural issue -- regenerating from scratch with corrected description: {corrected[:120]}...")
        diagram_data = None  # Reset so we retry
```

**Step 5: Exit retry loop on max attempts** (lines 780-795)
```python
if not imagen_accepted:
    logger.warning(f"Gemini image gen failed all {max_imagen_attempts} attempts for Q{question_idx}, "
                   f"falling back to nonai flow (claude_code_tool/schemdraw/matplotlib)")
    diagram_data = None  # Force nonai fallback
```

---

### 4B: STANDARD REVIEW (engine=nonai or nonai fallback)
**Location**: Lines 1133-1221

**Skip duplicate review** (lines 1133-1137):
```python
if effective_engine in ("ai", "both") and imagen_accepted:
    logger.info(f"Skipping duplicate review for Q{question_idx} — already reviewed in Imagen retry loop")
else:
    # Perform review below
```

**Review call** (lines 1162-1171):
```python
review_result = await self.reviewer.review_diagram(
    image_bytes=image_bytes_for_review,
    question_text=clean_question_for_review,
    diagram_description=description_for_review,
    user_prompt_context=getattr(self, "_generation_prompt", ""),
    domain=q_domain,
    diagram_type=q_diagram_type,
)
```

**On FAIL with corrected_description** (lines 1173-1211):
```python
if not review_result["passed"]:
    logger.warning(f"Diagram review FAILED for Q{question_idx}: {review_result['reason']}  "
                   f"Issues: {review_result['issues']}")

    corrected_desc = review_result.get("corrected_description")
    if corrected_desc:
        logger.info(f"Regenerating Q{question_idx} with corrected description: {corrected_desc[:120]}...")

        # PRESERVE ORIGINAL TOOL (important for matplotlib diagrams with LaTeX)
        if tool_name == "claude_code_tool":
            regen_tool = "claude_code_tool"
            regen_args = dict(tool_arguments)
            regen_args["description"] = (
                corrected_desc + " Do NOT include any computed answer values, "
                "specific numeric results, or parameters that reveal the solution."
            )
        else:
            regen_tool = "circuitikz_tool"
            regen_args = {"description": corrected_desc}

        logger.info(f"Regenerating Q{question_idx} using {regen_tool} (original tool preserved)")

        regen_data = await self.diagram_tools.execute_tool_call(
            tool_name=regen_tool,
            tool_arguments=regen_args,
            assignment_id=assignment_id,
            question_idx=question_idx,
            question_text=equation_resolved_question_text,
        )

        if regen_data:
            regen_data.pop("_image_bytes", None)  # Pop transient key
            diagram_data = regen_data
            logger.info(f"Regenerated diagram accepted for Q{question_idx}")
        else:
            logger.warning(f"Regeneration failed for Q{question_idx}; keeping original diagram")
else:
    logger.info(f"Diagram review PASSED for Q{question_idx}: {review_result['reason']}")
```

---

## PART 5: CORRECTANSWERDIAGRAM - NO REVIEW CURRENTLY

**Location**: [diagram_agent.py](src/utils/diagram_agent.py#L1542)

**Current Implementation** (lines 1542-1662):
- Decides if correctAnswerDiagram needed via `_ai_decide_correct_answer_diagram_needed()`
- Selects tool (circuitikz vs claude_code_tool) based on domain/diagram_type
- Executes tool directly: `await self.diagram_tools.execute_tool_call()`
- **Attaches directly to question WITHOUT review** (lines 1647-1653)
- **NO gemini review step present**

**Current Code** (lines 1642-1659):
```python
answer_diagram_data = await self.diagram_tools.execute_tool_call(
    tool_name=answer_tool_name,
    tool_arguments=answer_tool_args,
    assignment_id=assignment_id,
    question_idx=f"{question_idx}_answer",
    question_text=f"ANSWER KEY: {question_text}",
)

if answer_diagram_data and answer_diagram_data.get("s3_url"):
    answer_diagram_data.pop("_image_bytes", None)
    question["correctAnswerDiagram"] = {
        "s3_url": answer_diagram_data.get("s3_url"),
        "s3_key": answer_diagram_data.get("s3_key"),
        "file_id": answer_diagram_data.get("file_id"),
        "filename": answer_diagram_data.get("filename"),
    }
    logger.info(f"Q{question_idx}: correctAnswerDiagram generated successfully")
else:
    logger.warning(f"Q{question_idx}: correctAnswerDiagram generation failed, continuing without it")
```

---

## SUMMARY FOR CORRECTANSWERDIAGRAM ENHANCEMENT

To add Gemini review to correctAnswerDiagram:
1. **Extract image bytes** after tool execution (same pattern as lines 663-670)
2. **Call reviewer** with same parameters as lines 686-693
3. **Handle PASS**: Attach to question (lines 1650-1657)
4. **Handle FAIL**:
   - If `fixable=true`: Use imagen_fix_tool or just log warning
   - If `fixable=false`: Regenerate with corrected_description (same pattern as lines 1180-1211)
