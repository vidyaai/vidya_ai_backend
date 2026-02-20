"""
CircuiTikZ Pipeline Integration Test

Tests the full pipeline:
  CircuiTikZ LaTeX source → pdflatex → PDF → pdf2image (youtube_fetcher venv) → PNG

Run from repo root:
    python tests/circuitikz/test_circuitikz_pipeline.py

Output PNGs are written to tests/circuitikz/output/
"""

import base64
import os
import shutil
import subprocess
import sys
import tempfile

# ── Paths ────────────────────────────────────────────────────────────────────

HERE = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(HERE, "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

PDFLATEX = shutil.which("pdflatex") or "/Library/TeX/texbin/pdflatex"

VENV_PYTHON = (
    "/Users/pingakshyagoswami/Library/Mobile Documents/"
    "com~apple~CloudDocs/youtube_fetcher/path/to/venv/bin/python"
)

# ── Helper ────────────────────────────────────────────────────────────────────

def pdf_to_png(pdf_path: str, png_path: str, dpi: int = 300) -> None:
    """Convert PDF → PNG using the youtube_fetcher venv's pdf2image."""
    script = "\n".join([
        "import sys, base64",
        "from pdf2image import convert_from_path",
        "from io import BytesIO",
        f"imgs = convert_from_path({pdf_path!r}, dpi={dpi}, fmt='png', single_file=True)",
        "buf = BytesIO()",
        "imgs[0].save(buf, format='PNG', optimize=True)",
        "sys.stdout.buffer.write(base64.b64encode(buf.getvalue()))",
    ])
    result = subprocess.run([VENV_PYTHON, "-c", script], capture_output=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(
            f"pdf2image subprocess failed:\n{result.stderr.decode(errors='replace')[-800:]}"
        )
    png_bytes = base64.b64decode(result.stdout)
    with open(png_path, "wb") as f:
        f.write(png_bytes)
    size_kb = len(png_bytes) // 1024
    print(f"    PNG written: {os.path.relpath(png_path)} ({size_kb} KB)")


def compile_latex(name: str, latex_src: str, dpi: int = 300) -> str:
    """Write LaTeX, compile with pdflatex, convert to PNG.  Returns PNG path."""
    png_path = os.path.join(OUTPUT_DIR, f"{name}.png")

    # pdflatex cannot handle spaces in paths — use a space-free tmpdir
    tmpdir = tempfile.mkdtemp(prefix=f"ctikz_{name}_")
    try:
        tex_path = os.path.join(tmpdir, f"{name}.tex")
        pdf_path = os.path.join(tmpdir, f"{name}.pdf")

        with open(tex_path, "w", encoding="utf-8") as f:
            f.write(latex_src)

        env = {**os.environ, "PATH": f"/Library/TeX/texbin:{os.environ.get('PATH', '')}"}
        for _pass in range(2):
            r = subprocess.run(
                [PDFLATEX, "-interaction=nonstopmode", "-halt-on-error",
                 "-output-directory", tmpdir, tex_path],
                capture_output=True, text=True, timeout=60, env=env,
            )
            if r.returncode != 0:
                errors = "\n".join(
                    l for l in r.stdout.splitlines()
                    if l.startswith("!") or "Error" in l
                ) or r.stdout[-600:]
                raise RuntimeError(f"pdflatex failed on pass {_pass+1}:\n{errors}")

        if not os.path.isfile(pdf_path):
            raise RuntimeError(f"pdflatex produced no PDF for {name}")

        pdf_to_png(pdf_path, png_path, dpi=dpi)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    return png_path


# ── Test circuits ─────────────────────────────────────────────────────────────

# Test 1: NMOS with Vgs and Vds — replication of the uploaded assignment diagram (textbook style)
NMOS_VGS_VDS = r"""
\documentclass[border=16pt]{standalone}
\usepackage[american]{circuitikz}
\usepackage{siunitx}
\usepackage{amsmath}
\ctikzset{voltage dir=RP}

\begin{document}
\begin{circuitikz}[scale=1.4, font=\small, line width=0.8pt]

  % ---- NMOS ----
  \node[nmos] (M) at (3,3) {};
  \node[fill=white, inner sep=2pt] at (M.east) {$M_1$};

  % ---- Source to GND ----
  \draw (M.source) -- (3,0) node[ground] {};

  % ---- Vgs voltage source (left side) ----
  \draw (0,0) node[ground] {} to[V] (0,3) -- (M.gate);
  \node[fill=white, inner sep=2pt] at (-0.6,1.5) {$V_{GS}$};
  \node[fill=white, inner sep=2pt] at (0.6,1.5) {\SI{3}{\volt}};

  % ---- Vds voltage source (right side, connecting drain to source potential) ----
  \draw (M.drain) -- (3,5.5) -- (6,5.5) -- (6,0) to[V] (6,3);
  \draw (6,0) node[ground] {};
  \node[fill=white, inner sep=2pt] at (5.4,1.5) {$V_{DS}$};
  \node[fill=white, inner sep=2pt] at (6.6,1.5) {\SI{4}{\volt}};

  % ---- Parameter boxes ----
  \node[draw, rounded corners, fill=white, inner sep=5pt] at (0,-1.2)
        {$V_{th} = \SI{1}{\volt}$};
  \node[draw, rounded corners, fill=white, inner sep=5pt] at (3,-1.2)
        {$k_n = \SI{300}{\micro\ampere\per\volt\squared}$};
  \node[draw, rounded corners, fill=white, inner sep=5pt] at (6,-1.2)
        {$I_D = ?$};

\end{circuitikz}
\end{document}
"""

# Test 2: CMOS Inverter (PMOS pull-up + NMOS pull-down) - textbook style
CMOS_INVERTER = r"""
\documentclass[border=12pt]{standalone}
\usepackage[american]{circuitikz}
\usepackage{siunitx}
\usepackage{amsmath}
\ctikzset{voltage dir=RP}

\begin{document}
\begin{circuitikz}[scale=1.3, font=\small, line width=0.8pt]

  % PMOS (pull-up)
  \node[pmos] (MP) at (3,5) {};
  \node[fill=white, inner sep=2pt] at (MP.east) {$M_P$};

  % NMOS (pull-down)
  \node[nmos] (MN) at (3,2) {};
  \node[fill=white, inner sep=2pt] at (MN.east) {$M_N$};

  % VDD: small horizontal bar at top
  \draw (MP.source) -- (3,7);
  \draw (2.7,7) -- (3.3,7);
  \node[above=2pt] at (3,7) {$V_{DD}$};

  % GND at bottom
  \draw (MN.source) -- (3,0) node[ground] {};

  % Connect PMOS drain to NMOS drain (output node)
  \draw (MP.drain) -- (MN.drain);
  \coordinate (out_node) at (3,3.5);
  \filldraw[black] (out_node) circle (1.5pt);
  \draw (out_node) to[short, -o] (5,3.5) node[right] {$V_{out}$};

  % Input: connect Vin to BOTH gates via explicit horizontal+vertical wiring
  % First draw vertical wire between gates
  \draw (MP.gate) -- (1.5,5) -- (1.5,2) -- (MN.gate);
  % Junction dot at midpoint where Vin connects
  \filldraw[black] (1.5,3.5) circle (1.5pt);
  % Vin input from left
  \draw (0,3.5) node[left] {$V_{in}$} to[short, o-] (1.5,3.5);

\end{circuitikz}
\end{document}
"""

# Test 3: Common-source amplifier with RD load and AC input (textbook style)
CS_AMPLIFIER = r"""
\documentclass[border=16pt]{standalone}
\usepackage[american]{circuitikz}
\usepackage{siunitx}
\usepackage{amsmath}
\ctikzset{voltage dir=RP}

\begin{document}
\begin{circuitikz}[scale=1.4, font=\small, line width=0.8pt]

  % ---- NMOS ----
  \node[nmos] (M) at (3,2) {};
  \node[fill=white, inner sep=2pt] at (M.east) {$M_1$};

  % ---- RD: drain to VDD with current arrow ----
  \draw (M.drain) to[R, i<_=$I_D$] (3,5.5);
  % VDD: small horizontal bar (textbook style)
  \draw (2.7,5.5) -- (3.3,5.5);
  \node[above=2pt] at (3,5.5) {$V_{DD}$};
  % RD label with white background
  \node[fill=white, inner sep=2pt] at (3.6,4) {$R_D$};

  % ---- Source to GND ----
  \draw (M.source) -- (3,0) node[ground] {};

  % ---- Vin input (open circle with label) ----
  \draw (0,2) node[left] {$V_{in}$} to[short, o-] (M.gate);

  % ---- Vout tapped at drain node (horizontal wire) ----
  \draw (M.drain) -- ++(1.5,0) coordinate (vout_tap);
  \draw (vout_tap) to[short, -o] ++(0.5,0) node[right] {$V_{OUT}$};
  % Load capacitor
  \draw (vout_tap) to[C] ++(0,-1.5) node[ground] {};
  \node[fill=white, inner sep=2pt] at (5.2,1.5) {$C_L$};

\end{circuitikz}
\end{document}
"""

# Test 4: CS amplifier with current source load and source resistor (like second reference image)
CS_CURRENT_SOURCE = r"""
\documentclass[border=16pt]{standalone}
\usepackage[american]{circuitikz}
\usepackage{siunitx}
\usepackage{amsmath}
\ctikzset{voltage dir=RP}

\begin{document}
\begin{circuitikz}[scale=1.4, font=\small, line width=0.8pt]

  % ---- NMOS ----
  \node[nmos] (M) at (3,2.5) {};
  \node[fill=white, inner sep=2pt] at (M.east) {$M_1$};

  % ---- Current source load (drain to VDD) ----
  \draw (M.drain) to[isource, l=$I_0$] (3,6);
  % VDD: small horizontal bar
  \draw (2.7,6) -- (3.3,6);
  \node[above=2pt] at (3,6) {$V_{DD}$};

  % ---- Vout tapped at drain (between NMOS and current source) ----
  \draw (M.drain) -- ++(1.2,0) to[short, -o] ++(0.3,0) node[right] {$V_{out}$};

  % ---- Source resistor Rs ----
  \draw (M.source) to[R] (3,0) node[ground] {};
  \node[fill=white, inner sep=2pt] at (3.55,1) {$R_S$};

  % ---- Vin input (open circle with label) ----
  \draw (0,2.5) node[left] {$V_{in}$} to[short, o-] (M.gate);

\end{circuitikz}
\end{document}
"""


# ── Run tests ─────────────────────────────────────────────────────────────────

def run_all():
    assert os.path.isfile(PDFLATEX), f"pdflatex not found at {PDFLATEX}"
    assert os.path.isfile(VENV_PYTHON), f"venv Python not found at {VENV_PYTHON}"

    tests = [
        ("nmos_vgs_vds",      NMOS_VGS_VDS,     "NMOS with Vgs=3V, Vds=4V (assignment diagram)"),
        ("cmos_inverter",     CMOS_INVERTER,    "CMOS inverter (PMOS + NMOS)"),
        ("cs_amplifier",      CS_AMPLIFIER,     "Common-source amplifier with RD"),
        ("cs_current_source", CS_CURRENT_SOURCE, "CS amplifier with current source load"),
    ]

    passed = 0
    for name, src, label in tests:
        print(f"\n[{name}] {label}")
        try:
            png = compile_latex(name, src)
            print(f"    PASSED")
            passed += 1
        except Exception as exc:
            print(f"    FAILED: {exc}")

    print(f"\n{'='*50}")
    print(f"Results: {passed}/{len(tests)} passed")
    print(f"Output:  {OUTPUT_DIR}/")
    if passed < len(tests):
        sys.exit(1)


if __name__ == "__main__":
    run_all()
