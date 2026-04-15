# Diagram Generation Fix Plan

## 1. Pipeline Architecture

```
question_text
    │
    ▼
DomainRouter.classify()                              [domain_router.py:62-204]
    → domain, diagram_type, ai_suitable, subject_guidance
    │
    ▼
GPT-4o Agent  (_get_agent_prompt)                    [diagram_agent.py:155-348]
    → selects tool (circuitikz / tikz / claude_code / plotly / networkx)
    → builds description
    │
    ▼
_extract_required_labels(question_text)              [diagram_agent.py:24-69]
    → injects "REQUIRED LABELS: ..." prefix into description
    │
    ▼
Tool Execution (TikZ / CircuiTikZ / Claude Code / Plotly)
    → generates PNG image
    │
    ▼
GeminiDiagramReviewer.review_diagram()               [gemini_diagram_reviewer.py:60-491]
    → passed / failure_type / fixable / reason / issues / corrected_description
    │
    ├── PASS → accept image
    │
    └── FAIL → build corrected_desc → regen (up to 3 attempts)  [diagram_agent.py:1356-1544]
                 wrong_type     → "CRITICAL:" prefix + subject_guidance injection
                 missing_labels → "IMPORTANT:" prefix
                 data_mismatch  → "IMPORTANT:" prefix (reviewer corrected_description used first)
                 answer_leak    → "IMPORTANT:" prefix + reference_image_bytes + cumulative tracking
```

The Gemini reviewer applies 5 checks in order:
- **Check 0** — Diagram type correctness (`wrong_type`)
- **Check 1** — Answer leak detection (`answer_leak`)
- **Check 2** — Label presence (`missing_labels`)
- **Check 3** — Readability (`readability`)
- **Check 4** — Semantic data consistency (`data_mismatch`)

---

## 2. Multi-Dataset Evidence

### 2.1 Pass Rates (Offline Reviewer)

| Dataset | Questions | Passed | Rate |
|---------|-----------|--------|------|
| question_papers1 | 49 | 26 | 53% |
| question_papers2 | 49 | 31 | 63% |
| question_papers3 | 49 | 31 | 63% |
| question_papers4 | 49 | 29 | 59% |
| question_papers5_v2 | 48 | 17 | 35% |
| question_papers6 | 25 | 10 | 40% |
| **Grand Total** | **269** | **144** | **~54%** |

### 2.2 Inline Regen Effectiveness

| Run | 1st-attempt pass | 2nd-attempt pass | 3rd-attempt pass | Failed all 3 |
|-----|-----------------|-----------------|-----------------|--------------|
| regen_papers4 | 11/50 (22%) | 3 | 0 | 8 (16%) |
| regen_papers5 | 16/50 (32%) | 3 | 1 | 22 (44%) |
| regen_papers6_v1 | 8/25 (32%) | 2 | 1 | 10 (40%) |

Key finding: **40–44% of questions exhaust all 3 regen attempts** and fall back to question rephrasing. Regen rarely fixes `wrong_type` and `data_mismatch` — those fail persistently across all 3 attempts.

### 2.3 Failure Type Distribution (Grand Total: ~125 failures across ~269 questions)

| Failure Type | Count | % of Failures | Fixable by Regen? |
|---|---|---|---|
| `missing_labels` | 40 | 32% | Rarely (persists across attempts) |
| `answer_leak` | 34 | 27% | Rarely (cycles back to leak) |
| `data_mismatch` | 29 | 23% | Almost never |
| `wrong_type` | 18 | 14% | Never seen fixed in logs |
| `readability` | 4 | 3% | Usually (attempt 2 succeeds) |

### 2.4 Question-Position Failure Rates (papers1–4, 196 questions)

| Position | Pass Rate | Dominant Failure Type |
|---|---|---|
| Q2 | **82.5%** (best) | mixed |
| Q3 | ~70% | mixed |
| Q1 | 60% | data_mismatch |
| Q5 | 50% | wrong_type, data_mismatch |
| Q4 | **47.5%** (worst) | answer_leak |

### 2.5 Paper-Level Pass Rates (papers1–4 cross-log)

| Paper | P1 | P2 | P3 | P4 | Consistency |
|---|---|---|---|---|---|
| 04_Neuromorphic_Computing | 5/5 | 5/5 | 5/5 | 5/5 | **Perfect — most reliable** |
| 09_Quantum_Cryptography | 4/5 | 4/5 | 4/5 | 3/5 | Reliable |
| 08_Plasma_Physics | 3/5 | 5/5 | 3/5 | 4/5 | Variable Q1/Q4 |
| 01_Quantum_Error_Correction | 3/5 | 3/5 | 3/5 | 4/5 | Q3/Q5 persistent fails |
| 05_Crystallography | 3/5 | 3/5 | 3/5 | 3/5 | Q4/Q5 persistent fails |
| 02_Orbital_Mechanics | 2/5 | 4/5 | 4/5 | 3/5 | Variable |
| 10_Stellar_Nucleosynthesis | 2/5 | 2/5 | 2/5 | 4/5 | Mostly low; Q5 always fails |
| 03_Topological_Insulators | 2/5 | 2/5 | 3/5 | 2/5 | Q1/Q4/Q5 persistent fails |
| 07_CRISPR-Cas9 | 1/5 | 2/5 | 2/5 | 1/5 | **Consistently worst** |
| 06_Game_Theory | 1/4 | 1/4 | 2/4 | 0/4 | **Worst overall** |

---

## 3. Failure Type Analysis and Fix Strategies

---

### 3.1 `missing_labels` — 40 failures (32%)

#### What It Means
Required structural components named in the question or description do not appear as visible text labels in the diagram. The shape may be correct but key identifiers are absent.

#### Specific Persistent Examples (same question fails across all runs)

| Paper | Question | What's Missing | Logs Affected |
|---|---|---|---|
| QEC | Q3 | Logical qubit labels, ancilla qubit labels | P1–P4, P5_v2, P6 |
| QEC | Q5 | Region labels above/below threshold | P5_v2 |
| Neuromorphic | Q2–Q5 | STDP labels, synaptic weight labels, input/output labels, title | P5_v2 |
| Crystallography | Q5 | Lattice point labels, body-center atom label | P1–P4, P5_v2, P6 |
| Stellar Nucleosynthesis | Q3 | Key evolutionary region labels (main sequence, red giant, etc.) | P1–P4 |
| Plasma Physics | Q1, Q4 | Helical field lines label, safety factor q label | P3, P4 |
| Orbital Mechanics | Q3 | Velocity vectors, probe trajectory labels | P1, P3 |

#### Root Causes

**A. `_extract_required_labels()` has narrow coverage** — `diagram_agent.py:24-69`

Extracts: quoted terms, terms after "label/show/mark/indicate the", subscript math variables. Misses:
- Multi-word compound names not in quotes ("ancilla qubit", "lattice point", "body-center atom")
- Domain-standard labels implied by context rather than explicit wording
- Labels named only in the diagram description (not in the question text itself)

**B. REQUIRED LABELS injection uses weak imperative** — `diagram_agent.py:1028-1041`

```python
f"REQUIRED LABELS (must appear visibly in the diagram): {label_str}\n\n{description}"
```
For complex diagrams with many elements, Claude treats this as a suggestion and makes aesthetic trade-offs.

**C. Generator system prompts lack an explicit enumerate-every-named-component rule**

`tikz_generator.py:69-89` and the CircuiTikZ prompt say "include all labeled values" but not "every component named in the description MUST carry that exact name as a visible text label."

**D. Regen corrected_description is generic** — `diagram_agent.py:1440-1445`

```python
corrected_desc = (
    f"{original_desc} "
    f"IMPORTANT: The diagram is missing required labels. {reason}. "
    "Ensure ALL structural components mentioned in the description are clearly labeled."
)
```
Does not enumerate which specific labels are missing — Claude must infer from the generic `reason` text.

**E. Reviewer `issues` field (comma-separated specific missing labels) is not used in regen**

The reviewer returns `ISSUES: <comma-separated list>` but `diagram_agent.py:1440-1445` ignores it entirely.

#### Fix Strategies

**Fix ML-1 — Use reviewer `issues` field in regen description** *(P0 — High impact, Low effort)*
File: `diagram_agent.py:1440-1445`

```python
issues = review_result.get("issues", "")
issue_line = (
    f" Specifically these labels are missing: {issues}."
    if issues and issues.lower() != "none" else ""
)
corrected_desc = (
    f"{original_desc} "
    f"IMPORTANT: The diagram is missing required labels.{issue_line} {reason}. "
    "Add each missing label as visible text at the appropriate location in the diagram."
)
```

**Fix ML-2 — Strengthen REQUIRED LABELS injection to a hard constraint block** *(P0 — High impact, Low effort)*
File: `diagram_agent.py:1028-1041`

```python
# Current:
label_prefix = f"REQUIRED LABELS (must appear visibly in the diagram): {label_str}\n\n"

# Proposed:
label_prefix = (
    "MANDATORY LABELS — every item below MUST appear as visible text in the diagram:\n"
    + "\n".join(f"  • {lbl}" for lbl in required_labels)
    + "\nThe diagram will FAIL automated review if any of these are missing.\n\n"
)
```

**Fix ML-3 — Add "label every named component" rule to generator system prompts** *(P0 — High impact, Low effort)*
Files: `tikz_generator.py:69-89`, `circuitikz_generator.py` system prompt

Add as CRITICAL RULE:
```
LABEL EVERY NAMED COMPONENT: Every structural component named in the description
MUST have that exact name as a visible text label in the final diagram.
- "ancilla qubit" in description → label it "ancilla qubit"
- "lattice point" in description → label it "lattice point"
- "body-center atom" in description → label it "body-center atom"
Do not substitute with symbols, numbers, or abbreviations unless the
question itself uses that notation. Aesthetic trade-offs do NOT justify dropping labels.
```

**Fix ML-4 — Expand `_extract_required_labels()` to cover multi-word component names** *(P2 — Medium impact, Medium effort)*
File: `diagram_agent.py:24-69`

Add extraction of:
- "each [noun phrase]" and "all [noun phrase]" patterns
- 2–3 word noun phrases that appear in BOTH question text and description (intersection)
- Hyphenated compound terms (e.g., "spin-up edge state", "body-center atom")

---

### 3.2 `answer_leak` — 34 failures (27%)

#### What It Means
The diagram reveals the answer the student must find. This is the most severe failure — it defeats the exam question's purpose.

#### Specific Persistent Examples (same label leaks across all runs)

| Paper | Question | Leaking Label/Content | Logs Affected |
|---|---|---|---|
| Topological Insulators | Q4 | `"Z2 Topological Invariant"` explicitly labeled | **All 4 logs** (P1–P4) |
| Crystallography | Q4 | `"Systematic absences"` labeled in legend | **All 4 logs** (P1–P4) |
| CRISPR-Cas9 | Q1 | Key residue names and interaction labels | All 4 logs |
| CRISPR-Cas9 | Q4 | Color-coded lines showing which mismatch types lead to outcomes | All 4 logs |
| Game Theory | Q4 | Optimal payoff nodes highlighted / `"Pareto Frontier"` labeled | P1, P4 |
| Stellar Nucleosynthesis | Q5 | Each shell labeled with exact element product | P5_v2 |
| Plasma Physics | Q2 | Specific fusion reactions labeled in legend | P5_v2 |
| QEC | Q3 | `"Logical Qubit Encoding Path"` labeled | P2–P4 |
| Orbital Mechanics | Q1 | Mechanism answer shown directly | P1 |

#### Root Causes

**A. Technical term overlap: structural label = answer term**

In advanced STEM, component names are identical to the answer:
- "Z2 Topological Invariant" — is both a circuit label AND what students must identify
- "Systematic absences" — is both a plot legend entry AND the diffraction answer
- "Pareto Frontier" — is both a curve name AND the optimization answer
- Shell element labels (C, O, Ne, Mg, Si, Fe) in stellar nucleosynthesis — are answers to "what burns in each shell?"

**B. Agent system prompt anti-leak examples don't cover advanced physics/biology subjects**
File: `diagram_agent.py:249-292`

Anti-leak rules exist for timing diagrams, force diagrams, truth tables. No examples for quantum computing, topology, crystallography, game theory, or CRISPR.

**C. Domain router subject_guidance may misidentify what to omit**
File: `domain_router.py:90-107`

The router is prompted to end guidance with "Do NOT show: [2-3 answer-revealing elements]" but for novel advanced topics GPT-4 may not know what counts as an answer-leak.

**D. Gemini reviewer Check 1 IMPORTANT EXCEPTIONS list is too narrow**
File: `gemini_diagram_reviewer.py:269-277`

Exceptions only cover: "Data qubit, H, CNOT, X, Z, node names Vout/Vin". Doesn't cover advanced physics structural component names like "valence band", "conduction band", or crystallography axis labels.

**E. Regen cycles between answer_leak and missing_labels**

Logs show a common pattern: attempt 1 → answer_leak (too many labels), attempt 2 → missing_labels (removed too many labels), attempt 3 → answer_leak again. The model oscillates without converging.

#### Fix Strategies

**Fix AL-1 — Add advanced domain answer-hiding sections to subject_prompt_registry** *(P0 — High impact, Low effort)*
File: `subject_prompt_registry.py` — `_AGENT_SYSTEM_PROMPTS` dict

Add `⚠️ ANSWER HIDING` for each missing domain:

```
Quantum Computing / QEC:
  Do NOT label: error correction code type, syndrome measurement result,
  logical operation being performed, "Logical Qubit Encoding Path"

Condensed Matter / Topological Insulators:
  Do NOT label: topological phase name ("Topological Insulator", "Trivial Insulator"),
  Z2 invariant value, "Band Inversion", topological/trivial annotations on regions.
  DO label: energy axis (E), momentum axis (k), Fermi level (E_F), "Valence Band",
  "Conduction Band" — these identify axes, not answers.

Crystallography:
  Do NOT label: "Systematic absences", diffraction condition outcomes,
  structure factor calculation results, Bragg condition annotations.
  DO label: lattice points, unit cell boundaries, axis labels, Miller indices on planes.

Game Theory:
  Do NOT label: Nash equilibrium solutions, dominant strategies, Pareto frontier/front,
  "optimal" markers on nodes, best-response annotations.
  DO label: player names, strategy names, payoff values from question.

CRISPR-Cas9:
  Do NOT label: specific key residues (R1335, H840, etc.) if question asks to identify them,
  outcome labels on arrows if question asks what happens, mechanism conclusions.
  DO label: Cas9 protein, guide RNA (gRNA), PAM sequence, DNA target strand,
  cleavage site location.

Stellar Nucleosynthesis:
  Do NOT label: element products in each shell (C, O, Ne, etc.) if question asks to identify
  what burns where.
  DO label: shell boundaries, temperature/density arrows, stellar layers by number/position.
```

**Fix AL-2 — Expand Gemini reviewer Check 1 IMPORTANT EXCEPTIONS** *(P1 — Medium impact, Low effort)*
File: `gemini_diagram_reviewer.py:269-277`

Expand IMPORTANT EXCEPTIONS:
```
NOT answer leaks — these identify components, not conclusions:
- Quantum gates: H, CNOT, X, Z, T, S, Toffoli, ancilla qubit, data qubit, measurement gate
- Band structure axes: "Valence Band", "Conduction Band", "E" (energy axis), "k" (momentum),
  "E_F" (Fermi energy) — these label the axes/regions used to read the answer, not the answer
- Crystal component labels: "lattice point", "unit cell", "basis vector a/b/c"
- Orbital mechanics components: "perihelion", "aphelion", "semi-major axis a"
- Game theory structure: player node labels, branch labels showing strategies (not payoffs)

ANSWER LEAKS — these state the conclusion:
- "Z2 Topological Invariant = 1" or region labeled "Topological" / "Trivial"
- "Systematic absences" in a legend or annotation
- "Pareto Frontier", "Nash Equilibrium", "Dominant Strategy" labels
- Shell elements in stellar nucleosynthesis if question asks to identify them
- Syndrome table or "Logical Qubit Encoding Path" annotations
```

**Fix AL-3 — Inject answer-term blacklist into description** *(P2 — Medium impact, Medium effort)*
File: `diagram_agent.py` — after domain classification ~line 579

Add `_extract_answer_terms()` helper extracting terms following: "find", "calculate", "identify", "determine", "describe", "explain", "derive", "prove", "compute", "what is", "which [noun]":

```python
answer_terms = _extract_answer_terms(question_text)
if answer_terms:
    forbidden = ", ".join(f'"{t}"' for t in answer_terms[:5])
    description = (
        f"DO NOT LABEL OR ANNOTATE: {forbidden} — labeling these reveals the answer.\n\n"
        + description
    )
```

---

### 3.3 `data_mismatch` — 29 failures (23%)

#### What It Means
The diagram has the correct type and labeling but the specific data values, geometric orientations, sequences, or mathematical relationships are wrong.

#### Specific Persistent Examples

| Paper | Question | Mismatch | Logs Affected |
|---|---|---|---|
| Stellar Nucleosynthesis | Q1 | Shows neutrino (or gamma) emission at wrong nuclear step | P1–P4 |
| Stellar Nucleosynthesis | Q5 | Layered onion-shell structure wrong / layers in wrong order | P1–P3 |
| Game Theory | Q1 | Uses generic placeholder payoff values instead of question's specific numbers | **All 4 logs** |
| Game Theory | Q3 | Payoff value for (Low, High) outcome doesn't match question | **All 4 logs** |
| Crystallography | Q3 | Miller plane (100), (110), or (111) orientation incorrect | P1–P4, P5_v2, P6 |
| Plasma Physics | Q1 | Toroidal magnetic field direction shown incorrectly | P1, P3 |
| Quantum Cryptography | Q1 | Ket notation for diagonal basis states wrong | P3, P5_v2 |
| Orbital Mechanics | Q1/Q2 | Kepler time intervals labeled incorrectly; orbit arrows wrong direction | P1, P4, P6 |

#### Root Causes

**A. Complex geometric/numerical requirements not propagated into description**

The GPT-4o agent writes abstract descriptions and the generator fills in geometrically plausible but incorrect details. Neither agent nor generator knows domain-specific geometric rules.

**B. Game Theory special case: placeholder values**

Game Theory Q1 fails identically across ALL 4 logs with the same reason: "uses generic placeholder values". The question contains `<eq qN_eqM>` math placeholders that get passed as-is, and the generator substitutes meaningless values instead of the actual payoff numbers.

**C. Miller plane geometry is domain-specific knowledge**

The (hkl) intercept rule (x-intercept=1/h, y=1/k, z=1/l) is not in any current prompt. Generator draws planes that look plausible but are geometrically wrong.

**D. Reviewer `CORRECTED_DESCRIPTION` not always provided for data_mismatch**
File: `gemini_diagram_reviewer.py:313-361`

Unlike `wrong_type`, there's no MANDATORY instruction for data_mismatch, so `corrected_description` is sometimes absent and the fallback at `diagram_agent.py:1447-1451` is generic ("Regenerate using EXACTLY the values specified").

**E. Regen almost never fixes data_mismatch**

Logs show data_mismatch persists across all 3 regen attempts in the vast majority of cases.

#### Fix Strategies

**Fix DM-1 — Make `CORRECTED_DESCRIPTION` mandatory for data_mismatch in reviewer** *(P0 — High impact, Low effort)*
File: `gemini_diagram_reviewer.py:313-361`

Add (parallel to the wrong_type mandatory instruction):
```
When data_mismatch is detected:
  fixable=NO (diagram must be regenerated from scratch)
  CORRECTED_DESCRIPTION is MANDATORY. Use this format for each mismatch:
    "MISMATCH [n]: diagram shows [X] but question requires [Y].
     VISUAL FIX: [exact visual geometry needed, e.g. 'plane must be parallel to yz-axis',
     'near-perihelion sector must be ~3x smaller area than near-aphelion sector',
     'payoff values must be exactly: (Cooperate,Cooperate)=(3,3) (Defect,Defect)=(1,1)']"
  List every mismatch separately. Be quantitatively specific about geometry and values.
```

**Fix DM-2 — Add geometric precision rules to agent system prompt** *(P1 — Medium impact, Low effort)*
File: `diagram_agent.py:249-292` (`_get_agent_prompt()`)

Add "GEOMETRIC PRECISION" section:
```
GEOMETRIC PRECISION FOR COMMON DIAGRAM TYPES:
- Miller planes (hkl): intercepts x=1/h, y=1/k, z=1/l (index 0 = axis not intercepted = parallel to that axis).
  (100) = parallel to yz-plane. (110) = diagonal in xy-plane. (111) = equal intercepts on all three.
- Kepler's 2nd law: near-perihelion sector is narrow (small area), near-aphelion is wide (large area).
  For equal time intervals make the area difference visually obvious — minimum 3:1 ratio.
- Hohmann transfer: two concentric ellipses sharing one focus. Δv arrows must be tangential (prograde).
- Dirac cone: LINEAR (V-shaped) dispersion touching at a point — NOT parabolic.
- Game theory payoff matrix/tree: use EXACT payoff values from the question. Never substitute
  generic placeholders (a,b,c or 1,2,3) if the question specifies actual numbers.
- FSM/state diagrams: use EXACT state names and transition labels from the question text.
- Stellar nucleosynthesis onion shell: layers from outside in = H → He → C → O → Ne → Mg → Si → Fe.
```

**Fix DM-3 — Detect and abort on unresolved `<eq>` placeholder leakage** *(P1 — Medium impact, Low effort)*
File: `diagram_agent.py` — description construction step (~line 569)

The variable `equation_resolved_question_text` already exists at `diagram_agent.py:569` with placeholders replaced. Ensure the description passed to the tool is always built from `equation_resolved_question_text`, not raw `question_text`. Add an assertion/warning if `<eq ` tokens survive into the final tool call description.

---

### 3.4 `wrong_type` — 18 failures (14%)

#### What It Means
The diagram shows a fundamentally different visual structure than required. Shape/topology is wrong, not just labels or values. Regen never fixes this — all log analysis shows wrong_type on attempt 1 → wrong_type on attempt 2 → wrong_type on attempt 3 → FALLBACK.

#### Specific Persistent Examples

| Paper | Question | Wrong type shown → What was needed | Logs Affected |
|---|---|---|---|
| Topological Insulators | Q1 | Standard insulator band structure / 1D projection → 2D k-space with Dirac surface states | **All 4 logs** |
| Topological Insulators | Q5 | Gapped/parabolic dispersion → linear Dirac cone | P1–P4 |
| Stellar Nucleosynthesis | Q5 | Missing/wrong layered structure → concentric "onion shell" with all layers labeled | P1–P3 |
| QEC | Q5 | Error Rate vs Code Distance plot → correct threshold diagram or quantum circuit | P1–P4 |
| CRISPR-Cas9 | Q3 | Tangled concept map / jumbled chart → two distinct side-by-side pathway comparison | **All 4 logs** |

#### Root Causes

**A. Ambiguous or generic diagram type name in description**

- "Band structure diagram" → generator defaults to simplest parabolic semiconductor
- "CRISPR pathway diagram" → generator defaults to concept map
- "Stellar interior" → generator omits the concentric onion-shell structure

**B. No subtype disambiguation in agent prompt**
File: `diagram_agent.py:249-292`

The agent specifies WHICH tool to use but not WHICH specific visual geometry within a diagram type family.

**C. Corrected_description from Check 0 doesn't always include all 4 required fields**

The reviewer requires WRONG:/CORRECT:/VISUAL FEATURES:/DO NOT: but these are not always fully generated, leaving regen without enough precision to escape the wrong type.

#### Fix Strategies

**Fix WT-1 — Force specific diagram subtype naming in agent description rules** *(P0 — High impact, Low effort)*
File: `diagram_agent.py:249-292` (`_get_agent_prompt()`)

Add to description quality rules:
```
DIAGRAM SUBTYPE PRECISION: Always use the most specific subtype name — the description must
uniquely determine the visual geometry even without seeing the question.
- Not "band structure" → "linear Dirac cone dispersion (V-shaped, touching at Dirac point, NOT parabolic)"
- Not "crystal structure" → "FCC unit cell" or "BCC unit cell" or "simple cubic"
- Not "stellar interior" → "concentric onion-shell cross-section with layers from outside to center:
  H → He → C → O → Ne → Mg → Si → Fe core"
- Not "CRISPR pathway" → "two-column side-by-side comparison: left column = pathway A steps,
  right column = pathway B steps — NOT a flowchart or concept map"
- Not "orbit diagram" → "Hohmann transfer orbit: two concentric ellipses sharing one focus,
  inner orbit = circular departure orbit, outer orbit = circular arrival orbit, Δv arrows tangential"
```

**Fix WT-2 — Add domain-specific subtype disambiguation to subject_prompt_registry** *(P1 — Medium impact, Low effort)*
File: `subject_prompt_registry.py` — `_AGENT_SYSTEM_PROMPTS`

For condensed matter / topological physics:
```
DIAGRAM SUBTYPE DISAMBIGUATION:
- Normal insulator band structure: parabolic valence + conduction bands, gap between them, no surface states
- Topological insulator band structure: BULK bands parabolic and gapped, PLUS surface states that
  cross the gap as a linear (V-shaped or X-shaped) Dirac cone. Draw BOTH bulk bands AND surface states.
  The Dirac cone is the KEY distinguishing feature — it MUST be clearly visible.
- Wrong default to avoid: drawing ONLY the Dirac cone without bulk bands (incomplete), or drawing
  parabolic bands with a gap and no crossing states (that is a normal insulator).
```

For CRISPR-Cas9:
```
Comparison diagrams (Q3): Show as TWO DISTINCT SIDE-BY-SIDE PANELS — never as a concept map,
tangled flowchart, or single merged diagram. Panel A = one mechanism, Panel B = the other.
Each panel has its own sequential steps labeled top to bottom.
```

**Fix WT-3 — Validate Gemini Check 0 CORRECTED_DESCRIPTION completeness** *(P2 — Low effort)*
File: `gemini_diagram_reviewer.py:419-491` (`_parse_review_result()`)

After parsing, if `failure_type == "wrong_type"` and `corrected_description` is absent or missing any of the 4 required markers (WRONG:, CORRECT:, VISUAL FEATURES:, DO NOT:), retry the reviewer call once, explicitly requesting the missing fields.

---

### 3.5 `readability` — 4 failures (3%)

#### What It Means
Text in the diagram is illegible — too small, overlapping, or partially hidden by other elements.

#### Specific Examples

| Paper | Question | Issue | Log |
|---|---|---|---|
| Orbital Mechanics | Q5 | Labels "Me", "Precession direction" obscured/overlapping | P2, P4 |
| Game Theory | Q4 | Payoffs at leftmost terminal node obscured by overlapping tree branches | P2 |
| Crystallography | Q5 | "Body center atom" and other labels overlapping | P4 |

#### Root Causes

**A. Dense diagrams with many labels cause font collisions**

No minimum font size or anti-collision guidance in generator prompts.

**B. pdflatex compilation errors (partially fixed)**

`regen_papers4.log` had 52 `re.PatternError` exceptions from a regex bug in `tikz_generator.py` (now fixed by `_CANONICAL_TIKZLIB` replacement). Remaining errors in papers5/6 logs:
- `! Package pgfkeys Error: I do not know the key '/pgf/decoration/.expanded'`
- `! Dimension too large`
- `! Package tikz Error: + or - expected`

#### Fix Strategies

**Fix RD-1 — Add readability rules to generator system prompts** *(P2 — Low impact, Low effort)*
Files: `tikz_generator.py:69-89`, `circuitikz_generator.py` system prompt

```
READABILITY RULES:
- Use \footnotesize minimum for labels in dense diagrams (>8 components)
- Use \small or \normalsize for diagrams with ≤8 labeled components
- If labels would overlap: use [yshift=5pt] / [xshift=5pt] offsets or anchor adjustments
  — never drop or truncate a required label to avoid overlap
- For tree diagrams: ensure minimum 1.5cm vertical spacing between levels
```

**Fix RD-2 — pdflatex error post-processing** *(P2 — Low impact, Low effort)*
Files: `tikz_generator.py`, `circuitikz_generator.py`

After `_CANONICAL_TIKZLIB` substitution, if pdflatex returns non-zero exit code:
1. Strip any remaining `\usetikzlibrary{...}` calls not in the canonical set
2. Retry compilation once
3. Log the original error for debugging

---

## 4. Subject-Specific Fix Catalogue

### 4.1 Game Theory & Nash Equilibria (worst: 0–2/4 per run)

**Persistent failures every run:**
- Q1: `data_mismatch` — "uses generic placeholder values" (ALL 4 logs identical reason)
- Q3: `data_mismatch` — wrong payoff for (Low, High) outcome (all 4 logs)
- Q4: `answer_leak` — Nash equilibrium / optimal nodes highlighted (P1, P4)

**Root cause:** `<eq qN_eqM>` math placeholders in question text are not resolved before passing to generator. The generator can't read the actual payoff numbers and substitutes generic values.

**Targeted fixes:**
1. Use `equation_resolved_question_text` exclusively in tool descriptions (Fix DM-3)
2. Add Game Theory answer-hiding to `_AGENT_SYSTEM_PROMPTS` (Fix AL-1)
3. Add payoff matrix precision rule to geometric precision section (Fix DM-2)

### 4.2 CRISPR-Cas9 Gene Editing (1–2/5 per run)

**Persistent failures every run:**
- Q1: `answer_leak` — key residue/structure labels (all 4 logs)
- Q3: `wrong_type` — concept map instead of side-by-side pathway comparison (all 4 logs)
- Q4: `answer_leak` — color-coded outcome lines (all 4 logs)

**Targeted fixes:**
1. Add CRISPR answer-hiding to `_AGENT_SYSTEM_PROMPTS` (Fix AL-1)
2. Add CRISPR Q3 side-by-side panel disambiguation to `subject_prompt_registry` (Fix WT-2)
3. Expand reviewer Check 1 exceptions for CRISPR structural labels like "Cas9", "gRNA", "PAM" (Fix AL-2)

### 4.3 Topological Insulators (2–3/5 per run)

**Persistent failures every run:**
- Q1: `wrong_type` — bulk-only parabolic or 1D projection instead of 2D with Dirac surface states (all 4 logs)
- Q4: `answer_leak` — "Z2 Topological Invariant" labeled (all 4 logs)
- Q5: `wrong_type` — gapped parabolic dispersion instead of linear Dirac cone (P1–P4)

**Targeted fixes:**
1. Add Topological Insulators answer-hiding to `_AGENT_SYSTEM_PROMPTS` (Fix AL-1)
2. Add Topological Insulators subtype disambiguation (bulk+surface state requirement) to `subject_prompt_registry` (Fix WT-2)
3. Expand reviewer Check 1 exceptions: "Valence Band", "Conduction Band" are structural axes, not answers (Fix AL-2)

### 4.4 Crystallography & X-ray Diffraction (0–3/5 per run)

**Persistent failures every run:**
- Q4: `answer_leak` — "Systematic absences" labeled (all 4 logs)
- Q5: `missing_labels` — lattice point / body-center atom labels missing (all 4 logs + P5_v2, P6)
- Q3: `data_mismatch` — Miller plane (100)/(110)/(111) geometry incorrect (P1–P4, P5_v2, P6)

**Targeted fixes:**
1. Add Crystallography answer-hiding to `_AGENT_SYSTEM_PROMPTS` (Fix AL-1)
2. Add Miller plane intercept geometry rule to geometric precision section (Fix DM-2)
3. Add mandatory labeling rule for "lattice point" and "body-center atom" to generator prompts (Fix ML-3)

### 4.5 Stellar Nucleosynthesis (2–4/5 per run)

**Recurring failures:**
- Q1: `data_mismatch` — neutrino/gamma emission at wrong nuclear reaction step (P1–P4)
- Q3: `missing_labels` — key evolutionary region labels (main sequence, red giant) missing (P1–P4)
- Q5: `wrong_type` — onion-shell concentric structure wrong or absent (P1–P3)

**Targeted fixes:**
1. Add Stellar Nucleosynthesis answer-hiding to `_AGENT_SYSTEM_PROMPTS` (Fix AL-1)
2. Add onion-shell layer order to WT-1 diagram subtype precision rules and to DM-2 geometric precision
3. Nuclear reaction step order must be explicitly stated in subject_guidance from domain router

---

## 5. Priority Implementation Order

| Priority | Fix ID | Failure Type | Files | Impact | Effort |
|---|---|---|---|---|---|
| **P0** | ML-1 — use reviewer `issues` field in regen | missing_labels | `diagram_agent.py:1440` | High (32% of failures) | Low |
| **P0** | ML-2 — strengthen REQUIRED LABELS injection | missing_labels | `diagram_agent.py:1031` | High | Low |
| **P0** | ML-3 — add "label every named component" to generator prompts | missing_labels | `tikz_generator.py:69`, circuitikz prompt | High | Low |
| **P0** | AL-1 — add advanced domain answer-hiding to subject_prompt_registry | answer_leak | `subject_prompt_registry.py` | High (27% of failures) | Low |
| **P0** | DM-1 — make CORRECTED_DESCRIPTION mandatory for data_mismatch | data_mismatch | `gemini_diagram_reviewer.py:313` | High (23% of failures) | Low |
| **P0** | WT-1 — force specific diagram subtype naming in agent prompt | wrong_type | `diagram_agent.py:249` | High (14% of failures) | Low |
| **P1** | DM-2 — add geometric precision rules to agent prompt | data_mismatch | `diagram_agent.py:249` | Medium | Low |
| **P1** | DM-3 — ensure `equation_resolved_question_text` used in descriptions | data_mismatch (game theory) | `diagram_agent.py:~569` | Medium | Low |
| **P1** | AL-2 — expand Gemini Check 1 IMPORTANT EXCEPTIONS | answer_leak | `gemini_diagram_reviewer.py:269` | Medium | Low |
| **P1** | WT-2 — domain-specific subtype disambiguation in registry | wrong_type | `subject_prompt_registry.py` | Medium | Low |
| **P2** | AL-3 — inject answer-term blacklist into description | answer_leak | `diagram_agent.py:~579` | Medium | Medium |
| **P2** | WT-3 — validate Check 0 CORRECTED_DESCRIPTION completeness | wrong_type | `gemini_diagram_reviewer.py:419` | Low | Low |
| **P2** | ML-4 — expand `_extract_required_labels()` patterns | missing_labels | `diagram_agent.py:24` | Medium | Medium |
| **P2** | RD-1 — readability rules in generator prompts | readability | generators | Low | Low |
| **P2** | RD-2 — pdflatex error post-processing | readability | generators | Low | Medium |

---

## 6. Expected Impact

### After P0 fixes only:

| Metric | Baseline | Expected |
|---|---|---|
| Overall pass rate | 35–63% | 55–70% |
| `missing_labels` failures per ~269 | 40 | ≤15 |
| `answer_leak` failures per ~269 | 34 | ≤15 |
| `data_mismatch` failures per ~269 | 29 | ≤15 |
| `wrong_type` failures per ~269 | 18 | ≤8 |
| 1st-attempt pass rate | 22–32% | 45–55% |
| Regen fallback rate | 16–44% | ≤20% |

### After P0 + P1 + P2 fixes:

| Metric | Target |
|---|---|
| Overall pass rate | ≥ 85% |
| 1st-attempt pass rate | ≥ 65% |
| Regen fallback rate | ≤ 10% |

---

## 7. Verification

### Incremental testing after each change group:

```bash
cd /home/ubuntu/Pingu/vidya_ai_backend/question_generation_test

# Fastest feedback (no generation needed — tests reviewer and description changes):
python review_only.py question_papers6 2>&1 | tee /tmp/review_only_papers6_v2.log
grep "TOTAL:" /tmp/review_only_papers6_v2.log

# Full generation + inline review (tests agent prompt and regen loop changes):
python regen_diagrams.py --input question_papers5 --output question_papers7 \
  2>&1 | tee /tmp/regen_papers7.log

# Offline review of new generation:
python review_only.py question_papers7 2>&1 | tee /tmp/review_only_papers7.log
grep "TOTAL:" /tmp/review_only_papers7.log
```

### Regression check across all historical paper sets:

```bash
for p in question_papers1 question_papers2 question_papers3 question_papers4; do
  echo -n "$p: "
  python review_only.py $p 2>&1 | grep "TOTAL:"
done
```

### Success criteria:

| Criterion | Target |
|---|---|
| Any single paper set pass rate | ≥ 85% |
| Game Theory / CRISPR / Topological Insulators | ≥ 70% |
| First-attempt pass rate (inline review) | ≥ 65% |
| Regen fallback (3-attempt exhaustion) rate | ≤ 10% |
| No regression on papers1–4 vs baseline (59–63%) | ≥ 65% |
