"""
Shared LaTeX repair helpers for TikZ / CircuiTikZ pipelines.

Targets the two dominant pdflatex failure signatures seen in regen_papers7:
  - /pgf/decoration/.expanded unknown key
  - "Giving up on this path. Did you forget a semicolon?"
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
)

_TIKZ_CMD_RE = re.compile(r"\s*\\(draw|path|node|fill|clip)\b")


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
