# Diagram Review Results

Gemini 2.5 Pro review results across 3 regeneration runs.

---

## Run 1 — `question_papers` (baseline)

**Total: 26/49 passed (53%)**

| # | Topic | Q1 | Q2 | Q3 | Q4 | Q5 | Pass |
|---|-------|----|----|----|----|----|----|
| 1 | Quantum Error Correction (QEC) | PASS | PASS | FAIL(answer_leak) | PASS | FAIL(wrong_type) | 3/5 |
| 2 | Orbital Mechanics of Planets | FAIL(answer_leak) | FAIL(data_mismatch) | FAIL(missing_labels) | PASS | PASS | 2/5 |
| 3 | Topological Insulators | FAIL(wrong_type) | PASS | PASS | FAIL(answer_leak) | FAIL(wrong_type) | 2/5 |
| 4 | Neuromorphic Computing | PASS | PASS | PASS | PASS | PASS | 5/5 |
| 5 | Crystallography & X-ray Diffraction | PASS | PASS | PASS | FAIL(answer_leak) | FAIL(missing_labels) | 3/5 |
| 6 | Game Theory & Nash Equilibria | FAIL(data_mismatch) | NO_DIAGRAM | FAIL(data_mismatch) | FAIL(answer_leak) | PASS | 1/4 |
| 7 | CRISPR-Cas9 Gene Editing | FAIL(answer_leak) | FAIL(missing_labels) | FAIL(wrong_type) | FAIL(answer_leak) | PASS | 1/5 |
| 8 | Plasma Physics & Tokamak Confinement | FAIL(data_mismatch) | PASS | PASS | FAIL(data_mismatch) | PASS | 3/5 |
| 9 | Quantum Cryptography (BB84 Protocol) | FAIL(data_mismatch) | PASS | PASS | PASS | PASS | 4/5 |
| 10 | Stellar Nucleosynthesis | FAIL(data_mismatch) | PASS | FAIL(missing_labels) | PASS | FAIL(data_mismatch) | 2/5 |

---

## Run 2 — `question_papers2` (reviewer fixes: Check 0 wrong_type, failure_type routing, structural label exemptions, tolerance guidelines)

**Total: 27/49 passed (55%)**

| # | Topic | Q1 | Q2 | Q3 | Q4 | Q5 | Pass |
|---|-------|----|----|----|----|----|----|
| 1 | Quantum Error Correction (QEC) | PASS | PASS | FAIL(answer_leak) | PASS | FAIL(wrong_type) | 3/5 |
| 2 | Orbital Mechanics of Planets | PASS | PASS | PASS | PASS | FAIL(readability) | 4/5 |
| 3 | Topological Insulators | FAIL(wrong_type) | PASS | PASS | FAIL(answer_leak) | FAIL(wrong_type) | 2/5 |
| 4 | Neuromorphic Computing | PASS | PASS | PASS | PASS | PASS | 5/5 |
| 5 | Crystallography & X-ray Diffraction | PASS | PASS | PASS | FAIL(answer_leak) | FAIL(missing_labels) | 3/5 |
| 6 | Game Theory & Nash Equilibria | FAIL(data_mismatch) | NO_DIAGRAM | FAIL(data_mismatch) | FAIL(readability) | PASS | 1/4 |
| 7 | CRISPR-Cas9 Gene Editing | FAIL(answer_leak) | PASS | FAIL(wrong_type) | FAIL(answer_leak) | PASS | 2/5 |
| 8 | Plasma Physics & Tokamak Confinement | PASS | PASS | PASS | PASS | PASS | 5/5 |
| 9 | Quantum Cryptography (BB84 Protocol) | FAIL(missing_labels) | PASS | PASS | PASS | PASS | 4/5 |
| 10 | Stellar Nucleosynthesis | FAIL(data_mismatch) | PASS | FAIL(missing_labels) | PASS | FAIL(data_mismatch) | 2/5 |

---

## Run 3 — `question_papers3` (REQUIRED LABELS injection, preferred_tool hint, failure_type-aware regen, multi-line REASON parser fix)

**Total: 31/49 passed (63%)**

| # | Topic | Q1 | Q2 | Q3 | Q4 | Q5 | Pass |
|---|-------|----|----|----|----|----|----|
| 1 | Quantum Error Correction (QEC) | PASS | PASS | FAIL(answer_leak) | PASS | FAIL(wrong_type) | 3/5 |
| 2 | Orbital Mechanics of Planets | PASS | PASS | FAIL(missing_labels) | PASS | PASS | 4/5 |
| 3 | Topological Insulators | FAIL(wrong_type) | PASS | PASS | FAIL(answer_leak) | PASS | 3/5 |
| 4 | Neuromorphic Computing | PASS | PASS | PASS | PASS | PASS | 5/5 |
| 5 | Crystallography & X-ray Diffraction | PASS | PASS | PASS | FAIL(answer_leak) | FAIL(missing_labels) | 3/5 |
| 6 | Game Theory & Nash Equilibria | FAIL(data_mismatch) | NO_DIAGRAM | FAIL(data_mismatch) | PASS | PASS | 2/4 |
| 7 | CRISPR-Cas9 Gene Editing | FAIL(answer_leak) | PASS | FAIL(wrong_type) | FAIL(answer_leak) | PASS | 2/5 |
| 8 | Plasma Physics & Tokamak Confinement | FAIL(data_mismatch) | PASS | PASS | FAIL(missing_labels) | PASS | 3/5 |
| 9 | Quantum Cryptography (BB84 Protocol) | FAIL(data_mismatch) | PASS | PASS | PASS | PASS | 4/5 |
| 10 | Stellar Nucleosynthesis | FAIL(data_mismatch) | PASS | FAIL(missing_labels) | PASS | FAIL(wrong_type) | 2/5 |

---

## Progress Summary

| Run | Folder | Pass Rate | Key Changes |
|-----|--------|-----------|-------------|
| 1 | `question_papers` | 26/49 (53%) | Baseline |
| 2 | `question_papers2` | 27/49 (55%) | Reviewer fixes: Check 0, failure_type routing, structural label exemptions |
| 3 | `question_papers3` | 31/49 (63%) | REQUIRED LABELS injection, preferred_tool hint, failure_type-aware corrected_description |

## Persistent Failures

| Failure Type | Run 1 | Run 2 | Run 3 |
|---|---|---|---|
| answer_leak | 10 | 7 | 6 |
| data_mismatch | 8 | 5 | 5 |
| wrong_type | 5 | 5 | 4 |
| missing_labels | 4 | 4 | 4 |
| readability | 0 | 2 | 0 |

## Papers with Consistent Issues

- **Topological Insulators (3)**: Q1 consistently `wrong_type` — Claude draws a normal band structure instead of an inverted topological one
- **CRISPR-Cas9 (7)**: Q1 consistently `answer_leak`, Q4 consistently `answer_leak`
- **Stellar Nucleosynthesis (10)**: Q1 consistently `data_mismatch`, Q5 consistently `wrong_type` or `readability`
- **Game Theory (6)**: Q1, Q3 consistently `data_mismatch` — payoff values wrong; Q2 has no diagram across all runs
