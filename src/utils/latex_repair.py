"""
Shared LaTeX repair helpers for TikZ / CircuiTikZ pipelines.

Targets the dominant pdflatex failure signatures:
  - /pgf/decoration/.expanded unknown key
  - "Giving up on this path. Did you forget a semicolon?"
  - "File ended while scanning use of \\tikz@scan@no@calculator" (unclosed braces)
  - "Missing number" (hybrid polar+height coordinates)
"""

import re
from typing import Tuple

from controllers.config import logger

CANONICAL_TIKZLIBRARIES = (
    r"\usetikzlibrary{arrows.meta, calc, decorations, decorations.pathmorphing, "
    r"decorations.markings, shapes.geometric, positioning, fit, patterns, 3d, backgrounds}"
)

_REPAIRS: Tuple[Tuple[str, str], ...] = (
    (r",?\s*/pgf/decoration/\.expanded[^,}\]]*", ""),
    (r",?\s*/tikz/normal\s+[^,}\]]*", ""),
    (r"decoration=\{\s*\.expanded[^}]*\}\s*,?", ""),
    # Convert invalid hybrid polar+height coordinates to TikZ calc form.
    # Claude sometimes generates `at ({angle}:radius, height)` which mixes
    # polar and Cartesian syntax and causes "Missing number" errors.
    # Fix: at ({angle}:radius, height) → at ($(angle:radius) + (0, height)$)
    (
        r"at \((\{[^}]+\}|\d+(?:\.\d+)?):([^,)]+),\s*([^)\n]+)\)",
        r"at ($(\1:\2) + (0, \3)$)",
    ),
)

_TIKZ_CMD_RE = re.compile(r"\s*\\(draw|path|node|fill|clip)\b")

# Error messages that indicate unclosed groups (braces or brackets)
_UNCLOSED_GROUP_ERRORS = (
    "file ended while scanning",
    "emergency stop",
    "\\tikz@scan@no@calculator",
    "\\pgfmath@parse",
    "runaway argument",
)


def repair_unclosed_groups(latex: str) -> str:
    """
    Balance unmatched ``{``/``}`` and ``[``/``]`` in a LaTeX document.

    Claude occasionally generates TikZ with an unclosed ``{`` inside a
    coordinate expression (e.g. ``at ({60*\\i}:`` with a missing ``}``).
    pdflatex reports "File ended while scanning …" in those cases.

    Strategy
    --------
    * Strip LaTeX comments before counting so ``%}`` doesn't confuse counts.
    * Count only characters outside verbatim environments.
    * Inject missing closing characters just before ``\\end{tikzpicture}``
      (or ``\\end{document}`` as last resort) so the rest of the document
      structure stays intact.
    * Never remove characters — only append what is missing.
    """
    try:
        # Remove line comments (% to end of line) before counting
        uncommented = re.sub(r"(?<!\\)%[^\n]*", "", latex)

        open_brace = uncommented.count("{")
        close_brace = uncommented.count("}")
        open_bracket = uncommented.count("[")
        close_bracket = uncommented.count("]")

        missing_braces = open_brace - close_brace
        missing_brackets = open_bracket - close_bracket

        if missing_braces == 0 and missing_brackets == 0:
            return latex  # nothing to do

        # Build the patch string
        patch = "}" * max(0, missing_braces) + "]" * max(0, missing_brackets)
        if not patch:
            return latex

        # Try to insert before \end{tikzpicture} first, then \end{document}
        for anchor in (r"\end{tikzpicture}", r"\end{document}"):
            idx = latex.rfind(anchor)
            if idx != -1:
                logger.info(
                    f"repair_unclosed_groups: inserting {repr(patch)} before {anchor!r} "
                    f"(missing {missing_braces} braces, {missing_brackets} brackets)"
                )
                return latex[:idx] + patch + "\n" + latex[idx:]

        # Fallback: just append at the end
        logger.info(
            f"repair_unclosed_groups: appending {repr(patch)} at EOF "
            f"(missing {missing_braces} braces, {missing_brackets} brackets)"
        )
        return latex + "\n" + patch

    except Exception as e:
        logger.warning(f"repair_unclosed_groups failed: {e}")
        return latex


def canonicalize_tikzlibrary(latex: str) -> str:
    """Replace any \\usetikzlibrary{...} with the canonical superset."""
    try:
        return re.sub(
            r"\\usetikzlibrary\{[^}]*\}",
            lambda m: CANONICAL_TIKZLIBRARIES,
            latex,
        )
    except re.error as e:
        logger.warning(f"tikzlibrary canonicalization regex failed: {e}")
        return latex


def repair_latex(
    latex: str,
    picture_envs: Tuple[str, ...] = ("tikzpicture", "circuitikz"),
) -> str:
    """Apply deterministic repairs after a pdflatex failure."""
    for pattern, replacement in _REPAIRS:
        try:
            latex = re.sub(pattern, replacement, latex)
        except re.error as e:
            logger.warning(f"repair_latex regex failed ({pattern!r}): {e}")

    # Balance unclosed braces/brackets (causes "file ended while scanning")
    latex = repair_unclosed_groups(latex)

    begin_tokens = tuple(rf"\begin{{{env}}}" for env in picture_envs)
    end_tokens = tuple(rf"\end{{{env}}}" for env in picture_envs)

    try:
        inside_picture = False
        out_lines = []
        for raw_line in latex.splitlines():
            stripped = raw_line.rstrip()
            if any(tok in stripped for tok in begin_tokens):
                inside_picture = True
            elif any(tok in stripped for tok in end_tokens):
                inside_picture = False

            if (
                inside_picture
                and stripped
                and not stripped.lstrip().startswith("%")
                and _TIKZ_CMD_RE.match(stripped)
                and not stripped.endswith((";", "{", ",", "%", "[", "("))
            ):
                stripped = stripped + ";"
            out_lines.append(stripped)
        latex = "\n".join(out_lines)
    except re.error as e:
        logger.warning(f"semicolon-repair regex failed: {e}")

    return latex
