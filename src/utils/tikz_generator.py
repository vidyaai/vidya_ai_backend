"""
TikZ Diagram Generator

Generates publication-quality diagrams using general TikZ (LaTeX) for any
academic subject that benefits from precise vector graphics.

Use cases (non-exhaustive):
- Physics: ray diagrams, Feynman diagrams, spring-mass systems, field lines
- Mathematics: geometric constructions, 3D coordinate systems, number lines
- Materials science: 3D crystal unit cells (BCC/FCC), lattice structures
- Mechanical engineering: free body diagrams with vector notation
- Chemistry: Lewis structures, structural formulas (via chemfig package)
- Any diagram needing LaTeX-quality rendering

Pipeline: Claude → TikZ LaTeX → pdflatex → pdf2image → PNG

Dependencies (same as circuitikz_generator):
    pdf2image, Pillow
System: pdflatex + TikZ packages
"""

import io
import os
import re
import shutil
import subprocess
import tempfile
from typing import Optional

from anthropic import Anthropic
from controllers.config import logger
from utils.latex_repair import (
    canonicalize_tikzlibrary,
    repair_latex,
    _UNCLOSED_GROUP_ERRORS,
)

try:
    from pdf2image import convert_from_path

    PDF2IMAGE_AVAILABLE = True
except ImportError:
    PDF2IMAGE_AVAILABLE = False
    logger.warning("pdf2image not installed — TikZ diagrams unavailable")

PDFLATEX_PATH = shutil.which("pdflatex") or "/Library/TeX/texbin/pdflatex"

_SYSTEM_PROMPT = r"""You are an expert TikZ diagram generator for educational content.
Given a description, produce a complete, compilable LaTeX document that renders a
clear, publication-quality educational diagram.

YOUR OUTPUT: Return ONLY the complete LaTeX document. No markdown. No code fences.
No explanation. Start with \documentclass and end with \end{document}.

DOCUMENT TEMPLATE:
\documentclass[border=10pt]{standalone}
\usepackage{tikz}
\usepackage{tikz-3dplot}
\usepackage{pgfplots}
\pgfplotsset{compat=1.18}
\usepackage{chemfig}
\usepackage{amsmath}
\usepackage{amssymb}
\usepackage{siunitx}
\usetikzlibrary{arrows.meta, calc, decorations, decorations.pathmorphing, decorations.markings,
                shapes.geometric, positioning, fit, patterns, 3d, backgrounds}

\begin{document}
\begin{tikzpicture}[...your options...]
  % diagram content
\end{tikzpicture}
\end{document}

CRITICAL RULES:
1. Only use packages listed in the template above — do NOT add extra \usepackage{}.
2. The diagram must be self-contained in a single tikzpicture environment.
3. Use \node, \draw, \fill for all elements. Avoid deprecated commands.
4. Label all components referenced in the question. Match labels exactly.
5. Do NOT show computed answer values, formulas that reveal the solution, or
   output quantities that the student is asked to find.
6. Use siunitx for all physical quantities: \SI{9.8}{\metre\per\second\squared}
7. For 3D diagrams, use tikz-3dplot: \tdplotsetmaincoords{70}{110}, then use
   \begin{scope}[tdplot_main_coords]...\end{scope} INSIDE a normal 2D tikzpicture.
   NEVER set tdplot_main_coords as the tikzpicture option itself — see rule 13.
8. For chemical structures, use chemfig: \chemfig{...}
9. Keep coordinates reasonable: typical diagram fits in a 8×6 unit box.
10. Use \draw[-{Stealth}] for arrows, \draw[dashed] for dashed lines.
11. LABEL EVERY NAMED COMPONENT: Every structural component named in the description
    MUST have that exact name as a visible text \node label in the diagram.
    - "ancilla qubit" → add \node label "ancilla qubit" on that line
    - "lattice point" → add \node label "lattice point" at ONE representative lattice
      position with a leader-line callout (see rule 14); do NOT repeat at every instance
    - "body-center atom" → add \node label "body-center atom"
    Do NOT substitute with symbols or abbreviations unless the question uses them.
    Aesthetic trade-offs do NOT justify omitting a required label.
12. READABILITY & LABEL SPACING (CRITICAL — prevents overlapping text):
    - Use \footnotesize for dense diagrams (>8 components); \small otherwise.
    - Minimum label offset from its anchor point: 12pt for single-word labels;
      at least 20pt for multi-word labels: [yshift=20pt], [xshift=20pt], etc.
    - PREFER LEADER LINES over in-place offsets for crowded 3D regions:
        \draw[<-, shorten <=2pt] (label_anchor) -- ++(offset) node[anchor=...] {Label};
    - For 3D diagrams (tdplot_main_coords scope): NEVER place labels with just
      [below] or [right] at atom positions — 3D projection maps multiple atoms to
      nearly identical 2D points. Use leader lines that extend clearly outside the
      unit cell boundary before placing the text.
    - CATEGORICAL labels (e.g. "Corner atom", "Face-centered atom", legend entries)
      MUST go in a dedicated legend \node box, NOT scattered in-scene:
        \node[draw, fill=white, align=left, font=\small, anchor=north west,
              inner sep=6pt, rounded corners=2pt] at (legend_pos) {
          \raisebox{1pt}{\tikz\fill[blue!60!white] (0,0) circle (3pt);} Bottom Layer \\[2pt]
          \raisebox{1pt}{\tikz\fill[orange] (0,0) circle (3pt);} Middle Layer
        };
    - Title/structure name goes ABOVE the diagram in plain 2D (not below where
      annotation text already lives). See rule 13 for the mandatory pattern.
13. 3D DIAGRAMS WITH LEGENDS — MANDATORY SCOPE PATTERN:
    All 3D content goes inside a scope; legend and title are placed in plain 2D
    screen space AFTER the scope closes, referencing the snapshotted bounding box.

    \begin{tikzpicture}           % plain 2D tikzpicture at root level
      \tdplotsetmaincoords{70}{110}
      \begin{scope}[tdplot_main_coords]
        % ALL 3D atoms, bonds, axes, and in-scene structural labels go here.
        % Use (x, y, z) coordinates freely — they are projected by the rotation matrix.
      \end{scope}

      % Snapshot bounding box BEFORE adding legend/title (plain 2D coords)
      \path (current bounding box.south) coordinate (diagSouth);
      \path (current bounding box.north) coordinate (diagNorth);
      \path (current bounding box.west)  coordinate (diagWest);

      % Title ABOVE — plain 2D, not rotated
      \node[font=\normalsize\bfseries, anchor=south]
        at ([yshift=8pt]diagNorth) {Title Here};

      % Legend BELOW — plain 2D, not rotated
      \node[draw, fill=white, align=left, anchor=north,
            font=\small, inner sep=6pt, rounded corners=2pt]
        at ([yshift=-12pt]diagSouth) {
          \raisebox{1pt}{\tikz\fill[blue!60!white] (0,0) circle (3pt);} Layer A \\[2pt]
          \raisebox{1pt}{\tikz\fill[orange] (0,0) circle (3pt);} Layer B
        };
    \end{tikzpicture}

    RULES:
    - NEVER place legend or title nodes INSIDE the tdplot scope.
    - NEVER use (x,y,z) three-component coordinates for legend/title nodes.
    - The bounding-box snapshot coordinates (diagSouth etc.) are always 2D;
      use them freely outside the scope.
    - For legend colour swatches, the \tikz\fill[...] pattern above keeps the
      swatch rendering correctly regardless of the outer diagram's rotation.
14. ONE LABEL PER REPEATED COMPONENT TYPE (prevents mass label collisions):
    When the same component type repeats (e.g. 8 corner atoms, 6 face-center
    atoms, multiple identical gates/resistors/springs), label ONE representative
    instance with a leader-line callout only. Do NOT draw a separate label node
    at every identical instance — N overlapping labels are worse than one clear one.

    Exception: if the question EXPLICITLY asks the student to count or identify
    each instance individually, label all instances but use staggered radial
    positions (see rule 16).

    Pattern:
      % Label only the top-right corner atom as representative
      \draw[<-, shorten <=3pt] (cornerTR) -- ++(0.5, 0.4)
        node[font=\footnotesize, fill=white, inner sep=2pt, anchor=west]
        {Corner atom};
      % All other corner atoms: draw the sphere only, no label

15. WHITE KNOCKOUT BACKGROUND ON EVERY TEXT NODE:
    Every in-scene \node that renders text — labels, annotations, axis labels,
    arrow-tip text, midway annotations — MUST include fill=white, inner sep=2pt
    so that lines or arrows drawn through or near the label do not obscure it.

    Required form:
      \node[font=\small, fill=white, inner sep=2pt, anchor=...] at (pos) {Text};
      \draw[<-, shorten <=3pt] (atom) -- ++(dir)
        node[font=\small, fill=white, inner sep=2pt, anchor=west] {Text};

    This applies to ALL text nodes without exception, including axis labels
    (c-axis, a₁, a₂), dimension labels, and force/velocity labels.

16. CENTROID-OUTWARD RADIAL PLACEMENT FOR CLUSTERS (≥4 labelled elements):
    For any cluster of ≥4 components that must each be individually labelled
    (force polygons, numbered atoms, subcircuit nodes), place each label in the
    direction AWAY from the cluster centroid.

    Method:
      \coordinate (centroid) at (cx, cy);   % average of all element positions
      % For each element E, label goes toward (E - centroid) direction:
      \node[font=\footnotesize, fill=white, inner sep=2pt,
            anchor=...] at ($(E) + 0.6*($(E)-(centroid)$)$) {Label};

    - Minimum radial offset: 0.6 TikZ units (≈16 pt at standard scale).
    - NEVER use plain [above]/[below]/[left]/[right] for elements that are not
      on a strict cardinal axis from the centroid — use [above right], [below
      left], or explicit coordinate offsets instead.

17. DIMENSION LINE ANNOTATIONS:
    For edge-length, radius, distance, or force-magnitude callouts:
    - Use \draw[<->, >=Stealth] with the label as \node[midway, fill=white,
      inner sep=2pt, font=\small].
    - Offset the dimension line ≥0.4 TikZ units away from the nearest structure
      edge — never run it through an atom or component body.
    - For a labelled arrow alongside a solid body (e.g. "Atomic radius r"):
      use a dashed leader from the surface to an offset callout text, not a
      line that passes through the sphere/cylinder.

    Pattern:
      % Horizontal dimension line 0.5 units below the bottom edge
      \draw[<->, >=Stealth]
        ([yshift=-0.5cm]edgeA) -- ([yshift=-0.5cm]edgeB)
        node[midway, fill=white, inner sep=2pt, font=\small] {$a$};

      % Radius callout with dashed leader
      \draw[dashed, thin] (sphere_surface) -- ++(0.6, 0.4)
        node[font=\small, fill=white, inner sep=2pt, anchor=west] {$r$};

ANSWER-LEAK PREVENTION (CRITICAL):
- If the question asks students to identify a structure: draw the structure without
  labeling its name or type as a title or annotation.
- If the question asks students to calculate a value: do not show that value in
  the diagram.
- If the question asks students to draw something: show only the setup/context,
  not the answer.
- If the description includes a FORBIDDEN LABELS section, do not render those
  specific terms as text labels, legend entries, annotations, titles, or note
  boxes. Where such a label would normally sit beside a structural element,
  use "?" as a placeholder so the element itself remains visible. Do NOT
  remove structural components, and do NOT replace numerical values that are
  explicitly given in the question — those are problem inputs, not answers."""


class TikZGenerator:
    """
    Generates educational diagrams using general TikZ (LaTeX).

    Works for any subject: physics, materials science, chemistry, mathematics,
    mechanical engineering, or any topic requiring precise vector graphics.
    """

    def __init__(self, api_key: Optional[str] = None):
        self.client = Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))
        self.model = "claude-opus-4-5"

    async def generate_tikz_latex(
        self,
        question_text: str,
        diagram_description: str = "",
        subject_guidance: str = "",
    ) -> str:
        """Ask Claude to generate a TikZ LaTeX document."""
        user_parts = []
        if subject_guidance:
            user_parts.append(f"Drawing instructions: {subject_guidance}")
        user_parts.append(f"Question: {question_text[:800]}")
        if diagram_description:
            user_parts.append(f"Diagram description: {diagram_description}")

        response = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": "\n\n".join(user_parts)}],
        )
        latex = response.content[0].text.strip()

        # Strip markdown fences if Claude wrapped the output
        if latex.startswith("```"):
            latex = re.sub(r"^```[a-z]*\n?", "", latex)
            latex = re.sub(r"\n?```$", "", latex)
            latex = latex.strip()

        # Replace any \usetikzlibrary{...} lines Claude generated with the
        # canonical set — prevents hallucinated library names (e.g. pathmotions)
        # from causing pdflatex failures.
        latex = canonicalize_tikzlibrary(latex)

        # Strip trailing whitespace inside [...] option lists — prevents
        # "/tikz/key " (with trailing space) unknown-key errors in pgfkeys.
        try:
            latex = re.sub(
                r"\[([^\[\]]*)\]",
                lambda m: "[" + re.sub(r"\s+,", ",", m.group(1).rstrip()) + "]",
                latex,
            )
        except re.error as e:
            logger.warning(f"option-list trim regex failed: {e}")

        return latex

    async def _ai_repair_latex(self, latex_src: str, error_summary: str) -> str:
        """
        Ask Claude to fix a TikZ document that failed pdflatex compilation.

        Sends the failing LaTeX + error message back to Claude and asks it to
        correct only the compilation errors without changing diagram content.
        Returns the original source unchanged if the API call fails.
        """
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=_SYSTEM_PROMPT,
                messages=[
                    {
                        "role": "user",
                        "content": (
                            "The following TikZ LaTeX document failed to compile with pdflatex.\n\n"
                            f"Compilation error:\n{error_summary}\n\n"
                            "Fix ONLY the compilation errors. Do not change the diagram content or structure.\n"
                            "Common causes to check:\n"
                            "- Replace `({angle}:radius, height)` coordinates with `$(angle:radius) + (0, height)$`\n"
                            "- Replace `\\macro/N` arithmetic inside coordinates with pre-computed `\\pgfmathsetmacro` values\n"
                            "- Remove duplicate \\node definitions that use invalid syntax (keep the correct form)\n\n"
                            "Return ONLY the corrected LaTeX document. No markdown, no explanation.\n\n"
                            f"Failing document:\n{latex_src}"
                        ),
                    }
                ],
            )
            fixed = response.content[0].text.strip()
            if fixed.startswith("```"):
                fixed = re.sub(r"^```[a-z]*\n?", "", fixed)
                fixed = re.sub(r"\n?```$", "", fixed)
                fixed = fixed.strip()
            return canonicalize_tikzlibrary(fixed)
        except Exception as e:
            logger.warning(f"AI repair attempt failed: {e}")
            return latex_src

    async def _regenerate_latex(
        self,
        question_text: str,
        diagram_description: str,
        subject_guidance: str,
        prior_error: str,
    ) -> str:
        """
        Ask Claude to generate a brand-new TikZ document, explicitly told what
        went wrong last time.  Used as a last resort after both deterministic
        repair and AI repair have failed.
        """
        try:
            user_parts = []
            if subject_guidance:
                user_parts.append(f"Drawing instructions: {subject_guidance}")
            user_parts.append(f"Question: {question_text[:800]}")
            if diagram_description:
                user_parts.append(f"Diagram description: {diagram_description}")
            user_parts.append(
                f"\nIMPORTANT: A previous attempt failed with:\n{prior_error}\n"
                "Generate a SIMPLER, robust diagram that avoids complex coordinate "
                "expressions. Prefer explicit numeric coordinates over computed ones. "
                "Ensure every opened {{ or [ is closed. Keep the tikzpicture content "
                "under 60 lines."
            )
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": "\n\n".join(user_parts)}],
            )
            fresh = response.content[0].text.strip()
            if fresh.startswith("```"):
                fresh = re.sub(r"^```[a-z]*\n?", "", fresh)
                fresh = re.sub(r"\n?```$", "", fresh)
                fresh = fresh.strip()
            return canonicalize_tikzlibrary(fresh)
        except Exception as e:
            logger.warning(f"Regeneration attempt failed: {e}")
            return ""

    async def generate_diagram_png(
        self,
        question_text: str,
        diagram_description: str = "",
        subject_guidance: str = "",
        output_dpi: int = 300,
    ) -> bytes:
        """
        Full pipeline: Claude → TikZ LaTeX → pdflatex → pdf2image → PNG bytes.
        """
        if not PDF2IMAGE_AVAILABLE:
            raise RuntimeError(
                "pdf2image is not installed. Run: pip install pdf2image pillow"
            )

        if not os.path.isfile(PDFLATEX_PATH):
            raise RuntimeError(
                f"pdflatex not found at {PDFLATEX_PATH}. "
                "Install TeX Live or BasicTeX."
            )

        latex_src = await self.generate_tikz_latex(
            question_text, diagram_description, subject_guidance
        )

        tmpdir = tempfile.mkdtemp(prefix="tikz_")
        try:
            tex_file = os.path.join(tmpdir, "diagram.tex")
            pdf_file = os.path.join(tmpdir, "diagram.pdf")

            with open(tex_file, "w", encoding="utf-8") as fh:
                fh.write(latex_src)

            pdflatex_env = {
                **os.environ,
                "PATH": f"/Library/TeX/texbin:{os.environ.get('PATH', '')}",
            }

            last_error: Optional[str] = None
            for _pass in range(2):
                result = subprocess.run(
                    [
                        PDFLATEX_PATH,
                        "-interaction=nonstopmode",
                        "-halt-on-error",
                        "-output-directory",
                        tmpdir,
                        tex_file,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=60,
                    env=pdflatex_env,
                )
                if result.returncode == 0:
                    break

                error_lines = [
                    l
                    for l in result.stdout.splitlines()
                    if l.startswith("!") or "Error" in l or "error" in l
                ]
                error_summary = "\n".join(error_lines[:10]) or result.stdout[-500:]
                debug_tex = os.path.join(tempfile.gettempdir(), "debug_tikz.tex")
                with open(debug_tex, "w") as f:
                    f.write(latex_src)
                logger.error(
                    f"pdflatex pass {_pass + 1} failed (rc={result.returncode}):\n"
                    f"{error_summary}\nDebug LaTeX saved to {debug_tex}"
                )

                if _pass == 0:
                    repaired = repair_latex(latex_src, ("tikzpicture",))
                    if repaired != latex_src:
                        logger.info(
                            "pdflatex pass 1 failed — applying deterministic repairs and retrying"
                        )
                        latex_src = repaired
                        with open(tex_file, "w", encoding="utf-8") as fh:
                            fh.write(latex_src)
                        continue

                # Both deterministic passes exhausted — try AI repair
                last_error = error_summary
                break

            # AI repair fallback: triggered when both deterministic passes failed
            if last_error is not None:
                logger.info(
                    "pdflatex failed after deterministic repair — attempting AI-assisted repair"
                )
                ai_latex = await self._ai_repair_latex(latex_src, last_error)
                if ai_latex != latex_src:
                    latex_src = ai_latex
                    with open(tex_file, "w", encoding="utf-8") as fh:
                        fh.write(latex_src)
                    result = subprocess.run(
                        [
                            PDFLATEX_PATH,
                            "-interaction=nonstopmode",
                            "-halt-on-error",
                            "-output-directory",
                            tmpdir,
                            tex_file,
                        ],
                        capture_output=True,
                        text=True,
                        timeout=60,
                        env=pdflatex_env,
                    )
                    if result.returncode == 0:
                        pass  # AI repair succeeded — fall through to PDF conversion
                    else:
                        ai_error_lines = [
                            l
                            for l in result.stdout.splitlines()
                            if l.startswith("!") or "Error" in l or "error" in l
                        ]
                        ai_error_summary = (
                            "\n".join(ai_error_lines[:10]) or result.stdout[-500:]
                        )
                        # Last resort: regenerate from scratch
                        logger.warning(
                            "AI repair still failed — attempting full regeneration from scratch"
                        )
                        fresh_latex = await self._regenerate_latex(
                            question_text,
                            diagram_description,
                            subject_guidance,
                            ai_error_summary,
                        )
                        if fresh_latex:
                            # Apply deterministic repairs to the fresh source too
                            fresh_latex = repair_latex(fresh_latex, ("tikzpicture",))
                            latex_src = fresh_latex
                            with open(tex_file, "w", encoding="utf-8") as fh:
                                fh.write(latex_src)
                            result = subprocess.run(
                                [
                                    PDFLATEX_PATH,
                                    "-interaction=nonstopmode",
                                    "-halt-on-error",
                                    "-output-directory",
                                    tmpdir,
                                    tex_file,
                                ],
                                capture_output=True,
                                text=True,
                                timeout=60,
                                env=pdflatex_env,
                            )
                            if result.returncode != 0:
                                regen_error_lines = [
                                    l
                                    for l in result.stdout.splitlines()
                                    if l.startswith("!") or "Error" in l or "error" in l
                                ]
                                regen_error = (
                                    "\n".join(regen_error_lines[:10])
                                    or result.stdout[-500:]
                                )
                                raise RuntimeError(
                                    f"pdflatex compilation failed:\n{regen_error}"
                                )
                        else:
                            raise RuntimeError(
                                f"pdflatex compilation failed:\n{ai_error_summary}"
                            )
                else:
                    # AI repair returned the same source — try regeneration directly
                    logger.warning(
                        "AI repair made no changes — attempting full regeneration from scratch"
                    )
                    fresh_latex = await self._regenerate_latex(
                        question_text, diagram_description, subject_guidance, last_error
                    )
                    if fresh_latex:
                        fresh_latex = repair_latex(fresh_latex, ("tikzpicture",))
                        latex_src = fresh_latex
                        with open(tex_file, "w", encoding="utf-8") as fh:
                            fh.write(latex_src)
                        result = subprocess.run(
                            [
                                PDFLATEX_PATH,
                                "-interaction=nonstopmode",
                                "-halt-on-error",
                                "-output-directory",
                                tmpdir,
                                tex_file,
                            ],
                            capture_output=True,
                            text=True,
                            timeout=60,
                            env=pdflatex_env,
                        )
                        if result.returncode != 0:
                            regen_error_lines = [
                                l
                                for l in result.stdout.splitlines()
                                if l.startswith("!") or "Error" in l or "error" in l
                            ]
                            regen_error = (
                                "\n".join(regen_error_lines[:10])
                                or result.stdout[-500:]
                            )
                            raise RuntimeError(
                                f"pdflatex compilation failed:\n{regen_error}"
                            )
                    else:
                        raise RuntimeError(
                            f"pdflatex compilation failed:\n{last_error}"
                        )

            if not os.path.isfile(pdf_file):
                raise RuntimeError("pdflatex ran but produced no PDF")

            images = convert_from_path(
                pdf_file, dpi=output_dpi, fmt="png", single_file=True
            )
            if not images:
                raise RuntimeError("pdf2image returned no images")

            buf = io.BytesIO()
            images[0].save(buf, format="PNG", optimize=True)
            png_bytes = buf.getvalue()
            logger.info(
                f"TikZ→PNG success: {len(png_bytes):,} bytes "
                f"({images[0].width}×{images[0].height}px at {output_dpi}dpi)"
            )
            return png_bytes

        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
