"""
CircuiTikZ Circuit Diagram Generator

Uses Claude to generate professional LaTeX/CircuiTikZ markup, then compiles
it with pdflatex and converts to PNG via pdf2image.

Output quality matches Sedra & Smith "Microelectronic Circuits" textbook style:
- American-style components (rectangular resistors, standard sources)
- Proper MOSFET symbols (NMOS/PMOS with drain/gate/source terminals)
- SI unit formatting via siunitx
- Clean orthogonal wiring with VDD/GND power nodes

Dependencies (add to requirements.txt):
    pdf2image>=1.17
    Pillow>=10.0

System dependency:
    poppler  (for pdf2image)
    AWS:     sudo yum install -y poppler-utils
    macOS:   brew install poppler
    Ubuntu:  sudo apt-get install -y poppler-utils
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

try:
    from pdf2image import convert_from_path
    PDF2IMAGE_AVAILABLE = True
except ImportError:
    PDF2IMAGE_AVAILABLE = False
    logger.warning("pdf2image not installed — run: pip install pdf2image pillow")

# pdflatex binary — found on PATH or at the BasicTeX macOS location
PDFLATEX_PATH = shutil.which("pdflatex") or "/Library/TeX/texbin/pdflatex"


class CircuiTikZGenerator:
    """
    Generates textbook-quality circuit diagrams using CircuiTikZ (LaTeX).

    Pipeline: Claude → CircuiTikZ LaTeX → pdflatex → pdf2image → PNG

    Output is indistinguishable from Sedra & Smith diagrams:
    - Scaled, clean strokes with proper line weights
    - SI unit annotations (\\SI{300}{\\micro\\ampere\\per\\volt\\squared})
    - Standard MOSFET/transistor symbols
    - Proper voltage source bubbles and current source arrows
    """

    def __init__(self, api_key: Optional[str] = None):
        self.client = Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))
        self.model = "claude-opus-4-5"
        self._api_key_valid: Optional[bool] = None

    # ──────────────────────────────────────────────────────────────────────────
    #  Prompt construction
    # ──────────────────────────────────────────────────────────────────────────

    def _build_system_prompt(self) -> str:
        return r"""You are an expert CircuiTikZ circuit diagram generator. You produce complete, compilable LaTeX documents using the circuitikz package that render as professional, textbook-quality circuit schematics identical to those in Sedra & Smith "Microelectronic Circuits" (8th edition).

YOUR OUTPUT: Return ONLY a complete, compilable LaTeX document. No explanations. No markdown. No code fences. Just the LaTeX starting with \documentclass and ending with \end{document}.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DOCUMENT TEMPLATE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
\documentclass[border=12pt]{standalone}
\usepackage[american]{circuitikz}
\usepackage{siunitx}
\usepackage{amsmath}

\begin{document}
\ctikzset{voltage dir=RP}
\begin{circuitikz}[scale=1.3, font=\small, line width=0.8pt]

% Your circuit here

\end{circuitikz}
\end{document}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
COORDINATE SYSTEM
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- 1 unit ≈ 1 cm at scale=1.3
- Typical MOSFET circuit: x spans 0–6, y spans 0–8
- GND always at y=0, VDD at y=7–8
- Leave ~12pt border (handled by standalone border=12pt)
- Use named coordinates for complex circuits:
    \coordinate (D) at (3,5);
    \draw (D) -- (3,7);

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
WIRE SYNTAX
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
\draw (x1,y1) -- (x2,y2);                   % plain wire
\draw (A) to[component, options] (B);        % component between two points
\draw (A) to[short, -o] (B);                 % wire ending in open circle terminal
\draw (A) to[short, o-] (B);                 % wire starting from open circle
\draw (A) to[short, *-] (B);                 % wire starting from filled junction dot

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PASSIVE COMPONENTS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
\draw (A) to[R,  l=$R_1$,    a=\SI{2}{\kilo\ohm}]           (B)   % resistor
\draw (A) to[C,  l=$C_L$,    a=\SI{2}{\femto\farad}]         (B)   % capacitor
\draw (A) to[L,  l=$L$,      a=\SI{10}{\micro\henry}]        (B)   % inductor
\draw (A) to[D,  l=$D_1$]                                    (B)   % diode (anode→cathode)
\draw (A) to[zD, l=$D_Z$,    a=\SI{5.1}{\volt}]             (B)   % zener diode

% l= (label) appears above/left; a= (annotation) appears below/right

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SOURCES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
% Independent voltage source — circle with + on top half when drawn upward
\draw (A) to[V,  l=$V_{GS}$, v=\SI{3}{\volt}]  (B)   % v= shows the voltage value with arrow
\draw (A) to[V,  l=$V_{ds}$, v_=\SI{4}{\volt}] (B)   % v_= flips arrow direction

% Independent current source — circle with arrow
\draw (A) to[I,  l=$I_D$,    i=\SI{10}{\micro\ampere}] (B)

% Dependent/controlled sources
\draw (A) to[cV, l=$g_m v_{gs}$] (B)   % current-controlled voltage source (diamond)
\draw (A) to[cI, l=$g_m v_{gs}$] (B)   % voltage-controlled current source

% DC battery
\draw (A) to[battery1, l=$V_{GS}$, v=\SI{3}{\volt}] (B)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MOSFET TRANSISTORS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
% NMOS — place node at center; drain at top, source at bottom, gate at left
% Arrow on source points OUT (away from channel)
\node[nmos] (M1) at (3,3) {};
\draw (M1.drain)  -- (3,5);     % drain wire going UP to VDD or load
\draw (M1.source) -- (3,1);     % source wire going DOWN to GND
\draw (M1.gate)   -- (1,3);     % gate wire going LEFT to gate voltage
\node[right=2pt] at (M1.drain)  {$D$};
\node[right=2pt] at (M1.source) {$S$};
\node[above=2pt] at (M1.gate)   {$G$};

% PMOS — same structure; source is at TOP (connected to VDD), drain at bottom
% Arrow on source points IN (toward channel), or bubble on gate
\node[pmos] (M2) at (3,6) {};
\draw (M2.source) -- (3,8);     % source UP to VDD
\draw (M2.drain)  -- (3,4);     % drain DOWN to output or NMOS drain
\draw (M2.gate)   -- (1,6);     % gate LEFT

% Label the transistor
\node[right=10pt] at (M1.east) {$M_1$};

% 4-terminal MOSFET (with body/bulk connection)
\node[nmos, bodydiode] (M3) at (3,3) {};
\draw (M3.body) -- ++(0.5,0);   % bulk terminal

% RULES:
% - NMOS with VDD at top: Drain is UP, Source is DOWN
% - PMOS: Source is UP (at VDD), Drain is DOWN
% - ALWAYS label each transistor (M1, M2, Q1) when multiple transistors
% - Body terminal shown if relevant (4-terminal MOSFET)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BJT TRANSISTORS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
% NPN — arrow on emitter points OUT ("Not Pointing iN")
\node[npn] (Q1) at (3,3) {};
\draw (Q1.collector) -- (3,5);  % collector UP toward supply
\draw (Q1.emitter)   -- (3,1);  % emitter DOWN toward ground
\draw (Q1.base)      -- (1,3);  % base LEFT to input
\node[right=2pt] at (Q1.collector) {$C$};
\node[right=2pt] at (Q1.emitter)   {$E$};
\node[above=2pt] at (Q1.base)      {$B$};
\node[right=10pt] at (Q1.east)     {$Q_1$};

% PNP — arrow on emitter points IN ("Pointing iN Positively")
\node[pnp] (Q2) at (3,6) {};
\draw (Q2.emitter)   -- (3,8);  % emitter UP toward VCC (for PNP)
\draw (Q2.collector) -- (3,4);  % collector DOWN
\draw (Q2.base)      -- (1,6);  % base LEFT

% RULES:
% - Collector typically toward supply, Emitter toward ground (common-emitter)
% - Transistor name label (Q1, Q2) MUST be present when multiple BJTs

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OPERATIONAL AMPLIFIERS (OP-AMPS)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
% Standard op-amp — triangle with 5 terminals
\node[op amp] (opamp) at (4,3) {};
\draw (opamp.-)   -- ++(-1,0) node[left] {$V^-$};   % inverting input (−)
\draw (opamp.+)   -- ++(-1,0) node[left] {$V^+$};   % non-inverting input (+)
\draw (opamp.out) -- ++(1,0)  node[right] {$V_{out}$}; % output
% Power supply pins (optional but show if in question)
\draw (opamp.up)   -- ++(0,0.5) node[vcc] {$V_{CC}$};
\draw (opamp.down) -- ++(0,-0.5) node[vee] {$V_{EE}$};
\node[right=10pt] at (opamp.east) {$U_1$};  % op-amp name if multiple

% Inverting amplifier configuration
\draw (opamp.-) -- ++(-1,0) to[R, l=$R_1$] ++(-2,0) node[left] {$V_{in}$};
\draw (opamp.-) -- ++(0,1.5) to[R, l=$R_f$] ++(3,0) -| (opamp.out);
\draw (opamp.+) -- ++(-1,0) node[ground] {};

% RULES:
% - Inverting input (−) and non-inverting input (+) on SAME side
% - Output on OPPOSITE vertex
% - Verify correct input polarity signs

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
POWER NODES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
\draw (3,8) node[vcc] {$V_{DD}$};   % VDD rail (arrow pointing UP at top of wire)
\draw (3,0) node[ground] {};         % GND symbol (lines at bottom)
\draw (3,0) node[vee] {$V_{SS}$};   % Negative supply (for differential circuits)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NODE LABELS AND ANNOTATIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
\node[above]      at (x,y) {$V_{out}$};     % label above a point
\node[below]      at (x,y) {$V_{in}$};
\node[right]      at (x,y) {$I_D$};
\node[left]       at (x,y) {$V_{GS}$};
\node[above right] at (x,y) {\SI{4}{\volt}};

% Open-circle terminal node (for input/output pins)
\draw (x,y) node[ocirc] {};
\draw (x,y) node[circ]  {};   % filled junction dot

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
JUNCTION DOTS (wire crossings that connect)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
\filldraw[black] (x,y) circle (1.5pt);

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SI UNITS (ALWAYS use siunitx for values)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
\SI{3}{\volt}
\SI{300}{\micro\ampere\per\volt\squared}       % 300 µA/V²  (for kn)
\SI{4}{\volt}
\SI{1}{\kilo\ohm}
\SI{2}{\micro\ampere}
\SI{10}{\femto\farad}
\SI{1}{\mega\hertz}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STANDARD CMOS CIRCUIT LAYOUT (Sedra & Smith style)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Vertical orientation, top-to-bottom:
  y=8: VDD node
  y=6: PMOS source → VDD (for CMOS inverter)
  y=5: PMOS center (node[pmos])
  y=4: PMOS drain → output node
  y=4: Output wire / load / output label
  y=3: NMOS center (node[nmos])
  y=2: NMOS source → GND
  y=0: GND node
  Left (x=0..1): Gate input voltage source
  Right (x=5..6): Optional Vds source

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
COMPLETE REFERENCE EXAMPLE: NMOS with Vgs and Vds
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
\documentclass[border=12pt]{standalone}
\usepackage[american, voltage dir=RP]{circuitikz}
\usepackage{siunitx}
\usepackage{amsmath}

\begin{document}
\begin{circuitikz}[scale=1.3, font=\small, line width=0.8pt, voltage shift=0.5]

  % NMOS transistor at center
  \node[nmos] (M) at (3,3) {};

  % Gate label
  \node[left=2pt]  at (M.gate)   {$G$};
  \node[right=2pt] at (M.drain)  {$D$};
  \node[right=2pt] at (M.source) {$S$};

  % Vgs source: left side, from GND up to gate
  \draw (0,0) to[V, l=$V_{GS}$, v=\SI{3}{\volt}] (0,3)
              -- (M.gate);
  \draw (0,0) node[ground] {};

  % Vds source: right side
  \draw (6,0) to[V, l=$V_{DS}$, v=\SI{4}{\volt}] (6,5)
              -- (5,5) -- (M.drain |- 0,5) -- (M.drain);
  \draw (6,0) node[ground] {};

  % Source to GND
  \draw (M.source) -- (3,0) node[ground] {};

  % VDD rail at top
  \draw (3,5) -- (M.drain);
  \draw (3,5) node[vcc] {$V_{DD}$};

\end{circuitikz}
\end{document}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DIGITAL LOGIC GATES (IEEE-style)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
% Use the logic port library
\ctikzset{logic ports=ieee}

% Basic gates — inputs from LEFT, output to RIGHT
\node[and port]  (AND1)  at (4,5) {};   % AND: D-shape (flat left, curved right)
\node[or port]   (OR1)   at (4,3) {};   % OR: Curved shield shape
\node[not port]  (NOT1)  at (4,1) {};   % NOT: Triangle with bubble at output
\node[nand port] (NAND1) at (4,5) {};   % NAND: AND shape with bubble on output
\node[nor port]  (NOR1)  at (4,3) {};   % NOR: OR shape with bubble on output
\node[xor port]  (XOR1)  at (4,1) {};   % XOR: OR with extra curved line on input
\node[xnor port] (XNOR1) at (4,1) {};  % XNOR: XOR with bubble on output

% Gate connections — ALWAYS label inputs and outputs
\draw (AND1.in 1) -- ++(-1,0) node[left] {$A$};
\draw (AND1.in 2) -- ++(-1,0) node[left] {$B$};
\draw (AND1.out)  -- ++(1,0) node[right] {$Y$};

% Multi-input gates
\node[and port, number inputs=3] (AND3) at (4,5) {};  % 3-input AND
\node[or port, number inputs=4]  (OR4)  at (4,3) {};  % 4-input OR

% Bubbles for active-low inputs/outputs
\node[and port, and inverted inputs={1,2}] (AND_inv) at (4,5) {};  % inverted inputs
\node[nand port]  (NAND) at (4,3) {};  % output bubble automatic

% RULES:
% - MUST use standard IEEE/ANSI symbols for ALL gates
% - Inputs ALWAYS on LEFT, outputs ALWAYS on RIGHT
% - ALL inputs and outputs must be labeled (A, B, C for inputs; Y, F, Out for output)
% - Junction dots where wires connect: \filldraw (x,y) circle (1.5pt);
% - If question asks for "gate-level": must NOT show transistor-level CMOS

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CMOS CIRCUITS (Transistor-level Digital)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
% CMOS circuits MUST show both PMOS (pull-up) and NMOS (pull-down)
% PMOS connected to VDD, NMOS connected to GND
% Output node between PMOS drain and NMOS drain
% All transistors must be properly labeled

% CMOS inverter example
\node[pmos] (MP) at (3,5) {};
\node[nmos] (MN) at (3,2) {};
\draw (MP.source) -- (3,7) node[vcc] {$V_{DD}$};
\draw (MN.source) -- (3,0) node[ground] {};
\draw (MP.drain)  -- (MN.drain);
\coordinate (out) at (3,3.5);
\draw (out) -- ++(1,0) node[right] {$V_{out}$};
\draw (MP.gate) -- (MN.gate);
\draw (MP.gate) -- ++(-1,0) node[left] {$V_{in}$};
\node[right=10pt] at (MP.east) {$M_P$};
\node[right=10pt] at (MN.east) {$M_N$};

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FLIP-FLOPS (D, JK, SR, T) — DETAILED COMPONENT RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
% Draw flip-flops as rectangles with correctly labeled pins.
% Use a consistent size: width=2, height=3.

% ─── D Flip-Flop ───
\draw[thick] (0,0) rectangle (2,3);
\node[left] at (0,2.5) {$D$};                  % Data input (top-left)
\draw (0,0.3) -- (0.3,0.5) -- (0,0.7);         % Clock edge triangle (rising edge)
\node[left] at (-0.1,0.5) {CLK};               % Clock label outside
\node[right] at (2,2.5) {$Q$};                 % Q output (top-right)
\node[right] at (2,0.5) {$\overline{Q}$};      % Q-bar output (bottom-right)
% Optional async inputs (top/bottom):
\node[above] at (1,3) {\small PRE};             % Preset at top
\node[below] at (1,0) {\small CLR};             % Clear at bottom
% Active-low bubbles on async inputs:
\draw (1,3) circle (2pt);                       % bubble for active-low PRE
\draw (1,0) circle (2pt);                       % bubble for active-low CLR

% ─── JK Flip-Flop ───
\draw[thick] (5,0) rectangle (7,3);
\node[left] at (5,2.5) {$J$};                  % J input (top-left)
\node[left] at (5,0.5) {$K$};                  % K input (bottom-left)
\draw (5,1.3) -- (5.3,1.5) -- (5,1.7);         % Clock edge triangle
\node[left] at (4.9,1.5) {CLK};
\node[right] at (7,2.5) {$Q$};
\node[right] at (7,0.5) {$\overline{Q}$};

% ─── SR Flip-Flop ───
\draw[thick] (10,0) rectangle (12,3);
\node[left] at (10,2.5) {$S$};                 % Set input
\node[left] at (10,0.5) {$R$};                 % Reset input
\draw (10,1.3) -- (10.3,1.5) -- (10,1.7);      % Clock (optional for SR latch vs FF)
\node[left] at (9.9,1.5) {CLK};
\node[right] at (12,2.5) {$Q$};
\node[right] at (12,0.5) {$\overline{Q}$};

% ─── T Flip-Flop ───
\draw[thick] (15,0) rectangle (17,3);
\node[left] at (15,2.0) {$T$};                 % Toggle input
\draw (15,0.3) -- (15.3,0.5) -- (15,0.7);      % Clock edge triangle
\node[left] at (14.9,0.5) {CLK};
\node[right] at (17,2.5) {$Q$};
\node[right] at (17,0.5) {$\overline{Q}$};

% ─── Clock edge symbols ───
% Rising edge:  small triangle ▷ inside block at CLK pin
\draw (x,y_low) -- (x+0.3,y_mid) -- (x,y_high);
% Falling edge: bubble ○ followed by triangle
\draw (x,y) circle (2pt);
\draw (x+0.15,y_low) -- (x+0.45,y_mid) -- (x+0.15,y_high);

% ─── Connecting multiple flip-flops in a chain ───
% Wire Q output of FF0 to D input of FF1:
\draw (FF0_Q) -- (FF1_D);
% All flip-flops aligned horizontally, labeled FF0, FF1, FF2:
\node[above] at (1,3) {\small FF0};
\node[above] at (4,3) {\small FF1};
\node[above] at (7,3) {\small FF2};

% RULES:
% - Clock input MUST have edge indicator triangle
% - Q and Q̄ on opposite side from inputs — Q̄ is complement of Q
% - Asynchronous inputs (PRE, CLR): top/bottom, active-low bubble if inverted
% - Multiple flip-flops MUST be labeled (FF0, FF1, FF2 or by function)
% - D input ALWAYS on the same side as CLK (left side)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SHIFT REGISTERS — COMPLETE EXAMPLES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
% A shift register is N flip-flops in series.
% Q output of each FF connects to D input of the next FF.
% All FFs share a common CLK (and optional EN/RST signals).
% Serial data input feeds the first FF's D input.

% ─── 3-bit Shift Register (SISO) with Enable ───
% FF0, FF1, FF2 placed left-to-right, uniform spacing = 4 units

% Define flip-flop dimensions
% Each FF: width=2, height=3, spaced 4 units apart

% FF0
\draw[thick] (0,0) rectangle (2,3);
\node[left] at (0,2.5) {$D_0$};
\draw (0,0.3) -- (0.3,0.5) -- (0,0.7);
\node[left] at (-0.1,0.5) {\small CLK};
\node[right] at (2,2.5) {$Q_0$};
\node[right] at (2,0.5) {$\overline{Q}_0$};
\node[above] at (1,3) {\small FF0};

% FF1
\draw[thick] (5,0) rectangle (7,3);
\node[left] at (5,2.5) {$D_1$};
\draw (5,0.3) -- (5.3,0.5) -- (5,0.7);
\node[left] at (4.9,0.5) {\small CLK};
\node[right] at (7,2.5) {$Q_1$};
\node[right] at (7,0.5) {$\overline{Q}_1$};
\node[above] at (6,3) {\small FF1};

% FF2
\draw[thick] (10,0) rectangle (12,3);
\node[left] at (10,2.5) {$D_2$};
\draw (10,0.3) -- (10.3,0.5) -- (10,0.7);
\node[left] at (9.9,0.5) {\small CLK};
\node[right] at (12,2.5) {$Q_2$};
\node[right] at (12,0.5) {$\overline{Q}_2$};
\node[above] at (11,3) {\small FF2};

% Serial data input to FF0
\draw[->] (-2,2.5) -- (0,2.5);
\node[left] at (-2,2.5) {Serial In};

% Chain connections: Q of each FF → D of next FF
\draw[->] (2,2.5) -- (5,2.5);       % Q0 → D1
\draw[->] (7,2.5) -- (10,2.5);      % Q1 → D2

% Serial output from last FF
\draw[->] (12,2.5) -- (14,2.5);
\node[right] at (14,2.5) {Serial Out};

% Common CLK line (horizontal bus at bottom)
\draw (1,-1) -- (11,-1);
\draw[->] (1,-1) -- (1,0);
\draw[->] (6,-1) -- (6,0);
\draw[->] (11,-1) -- (11,0);
\node[below] at (6,-1) {CLK};

% Enable signal (gate CLK or MUX on D input)
% Method 1: AND gate on CLK path
\node[and port, scale=0.6] (EN_AND) at (-1,-1.5) {};
\draw (EN_AND.in 1) -- ++(-1,0) node[left] {CLK};
\draw (EN_AND.in 2) -- ++(-1,0) node[left] {EN};
\draw (EN_AND.out)  -- ++(0.5,0) node[right] {Gated CLK};

% Method 2: MUX on D input (holds value when EN=0)
% Per FF: D_actual = EN ? D_in : Q_current

% ─── Combinational Decoder connected to shift register ───
% 3-input decoder detects pattern (e.g., 101)
% Inputs: Q0, Q1, Q2 from shift register outputs

\draw[thick] (6,-4) rectangle (9,-7);
\node at (7.5,-5.5) {\small DECODER};
\node at (7.5,-6) {\small (detects 101)};
\draw[->] (2,0.5) |- (6,-4.5);     % Q0 to decoder
\node[left] at (6,-4.5) {\small $Q_0$};
\draw[->] (7,0.5) |- (6,-5.5);     % Q1 to decoder
\node[left] at (6,-5.5) {\small $Q_1$};
\draw[->] (12,0.5) |- (6,-6.5);    % Q2 to decoder
\node[left] at (6,-6.5) {\small $Q_2$};
\draw[->] (9,-5.5) -- (11,-5.5);   % decoder output
\node[right] at (11,-5.5) {Detect Out};

% SHIFT REGISTER RULES:
% - Draw each FF as a labeled rectangle with D, CLK, Q, Q̄ pins
% - Chain: Q(n) → D(n+1) for SISO/SIPO; parallel load for PISO
% - Common CLK bus at bottom connected to all FFs
% - Enable signal shown as AND gate on CLK or MUX on D input
% - Serial input on leftmost FF, serial output on rightmost FF
% - Show initial contents if given: annotate inside each FF
% - Label register bits: Q0 (LSB) on left or right depending on shift direction

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
COUNTERS — BINARY, BCD, RING, JOHNSON
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
% Counters are chains of flip-flops with feedback.
% Draw like shift registers but with feedback connections.

% Block-level counter
\draw[thick] (0,0) rectangle (4,3);
\node at (2,1.5) {\large Counter};
\node[left] at (0,2.5) {CLK};
\draw (0,2.3) -- (0.3,2.5) -- (0,2.7);   % clock edge
\node[left] at (0,1.5) {EN};               % enable
\node[left] at (0,0.5) {RST};              % reset
\node[right] at (4,2.5) {$Q_3$};
\node[right] at (4,2.0) {$Q_2$};
\node[right] at (4,1.5) {$Q_1$};
\node[right] at (4,1.0) {$Q_0$};
\node[right] at (4,0.3) {TC};              % terminal count / carry out
\node[above] at (2,3) {LD};                % parallel load input

% Bus output notation
\draw[line width=2pt] (4,1.75) -- (5.5,1.75);
\draw (4.75,1.55) -- (4.75,1.95);
\node[above right] at (4.75,1.75) {/4};

% COUNTER RULES:
% - Count direction: UP, DOWN, or UP/DOWN with control signal
% - Reset (RST, CLR): synchronous or asynchronous
% - Load (LD, LOAD): parallel load input
% - Enable (EN, CE): controls whether counting occurs
% - Carry/Borrow outputs (CO, TC) for cascading
% - Output width: Q[3:0] for 4-bit counter
% - Mode label: MOD-N counter with N specified

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MUX (MULTIPLEXER) — DETAILED
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
% Trapezoid shape: wider side for inputs, narrower for output

% 4:1 MUX as trapezoid
\draw (0,0) -- (0,4) -- (1.5,3.5) -- (1.5,0.5) -- cycle;
\node[left] at (0,3.5) {$I_0$};
\node[left] at (0,2.5) {$I_1$};
\node[left] at (0,1.5) {$I_2$};
\node[left] at (0,0.5) {$I_3$};
\node[right] at (1.5,2) {$Y$};
\node[below] at (0.75,0) {$S_1\;S_0$};

% Block representation (alternative)
\draw[thick] (0,0) rectangle (2.5,3);
\node at (1.25,1.5) {MUX\\4:1};
\draw (-0.5,2.5) -- (0,2.5) node[left, xshift=-8pt] {$I_0$};
\draw (-0.5,2.0) -- (0,2.0) node[left, xshift=-8pt] {$I_1$};
\draw (-0.5,1.5) -- (0,1.5) node[left, xshift=-8pt] {$I_2$};
\draw (-0.5,1.0) -- (0,1.0) node[left, xshift=-8pt] {$I_3$};
\draw (2.5,1.75) -- (3.0,1.75) node[right] {$Y$};
\draw (1.25,-0.5) -- (1.25,0) node[below, yshift=-8pt] {SEL};
% Optional enable
\draw (0,0.3) -- (-0.5,0.3) node[left] {EN};

% MUX RULES:
% - Data inputs: I0, I1... or D0, D1... (2^n inputs for n select lines)
% - Select lines: S0, S1... at bottom
% - Single output: Y, OUT, or F
% - Optional enable (EN, G): shown with bubble if active-low
% - Size notation: 2:1, 4:1, 8:1 MUX must match pin count

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DEMUX (DEMULTIPLEXER)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
% Trapezoid: narrower on input side, wider on output side

% 1:4 DEMUX
\draw (0,0.5) -- (0,3.5) -- (1.5,4) -- (1.5,0) -- cycle;
\node[left] at (0,2) {$D$};
\node[right] at (1.5,3.5) {$Y_0$};
\node[right] at (1.5,2.5) {$Y_1$};
\node[right] at (1.5,1.5) {$Y_2$};
\node[right] at (1.5,0.5) {$Y_3$};
\node[below] at (0.75,0) {$S_1\;S_0$};

% DEMUX RULES:
% - Single data input: D, IN, or A
% - Select lines: S0, S1... (n select lines give 2^n outputs)
% - Outputs: Y0, Y1, Y2... or O0, O1, O2...
% - Optional enable (EN): active-low shown with bubble

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ENCODER / DECODER
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
% Rectangular blocks with labeled pins.

% 3-to-8 Decoder
\draw[thick] (0,0) rectangle (3,4);
\node at (1.5,3.5) {\small DECODER};
\node at (1.5,3.0) {\small 3:8};
\node[left] at (0,2.5) {$A_2$};
\node[left] at (0,2.0) {$A_1$};
\node[left] at (0,1.5) {$A_0$};
\node[left] at (0,0.5) {EN};
\node[right] at (3,3.5) {$Y_0$};
\node[right] at (3,3.0) {$Y_1$};
\node[right] at (3,2.5) {$Y_2$};
\node[right] at (3,2.0) {$Y_3$};
\node[right] at (3,1.5) {$Y_4$};
\node[right] at (3,1.0) {$Y_5$};
\node[right] at (3,0.5) {$Y_6$};
\node[right] at (3,0.0) {$Y_7$};
% Active-low outputs: add bubbles or use overbar $\overline{Y_0}$

% 8-to-3 Priority Encoder
\draw[thick] (6,0) rectangle (9,4);
\node at (7.5,3.5) {\small ENCODER};
\node at (7.5,3.0) {\small 8:3};
\node[left] at (6,2.5) {$I_7$};
\node[left] at (6,1.5) {$\vdots$};
\node[left] at (6,0.5) {$I_0$};
\node[right] at (9,2.5) {$A_2$};
\node[right] at (9,2.0) {$A_1$};
\node[right] at (9,1.5) {$A_0$};
\node[right] at (9,0.5) {$V$};  % valid output

% Seven-segment decoder: outputs labeled a, b, c, d, e, f, g

% ENCODER/DECODER RULES:
% - Decoder: n inputs → 2^n outputs, only ONE active at a time
% - Encoder: 2^n inputs → n outputs
% - Priority encoder: handles multiple active inputs
% - Enable input (EN, G1, G2A, G2B): multiple enables may be AND-ed
% - Active-low outputs: bubbles or overbar notation

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
REGISTER FILE / REGISTER BANK
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
% Block diagram with read/write ports

\draw[thick] (0,0) rectangle (4,5);
\node at (2,4.5) {\small Register File};
\node at (2,4.0) {\small $(32 \times 32)$};

% Read port 1
\node[left] at (0,3.5) {RA1};          % read address 1
\node[right] at (4,3.5) {RD1};         % read data 1
\draw[->] (-0.5,3.5) -- (0,3.5);
\draw[->] (4,3.5) -- (4.5,3.5);

% Read port 2
\node[left] at (0,2.5) {RA2};
\node[right] at (4,2.5) {RD2};
\draw[->] (-0.5,2.5) -- (0,2.5);
\draw[->] (4,2.5) -- (4.5,2.5);

% Write port
\node[left] at (0,1.5) {WA};           % write address
\node[left] at (0,0.5) {WD};           % write data
\draw[->] (-0.5,1.5) -- (0,1.5);
\draw[->] (-0.5,0.5) -- (0,0.5);

% Write enable + clock
\node[above] at (2,5) {WE};
\draw[->] (2,5.5) -- (2,5);
\node[above] at (3.5,5) {CLK};
\draw (3.5,5) -- (3.5,4.8);
\draw (3.3,5) -- (3.5,5.15) -- (3.7,5);  % clock triangle

% Bus width annotations
\draw[line width=2pt] (4.5,3.5) -- (5.5,3.5);
\draw (5,3.3) -- (5,3.7);
\node[above right] at (5,3.5) {/32};

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ALU / DATAPATH
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
% ALU as chevron/pentagon shape

% ALU block
\draw[thick] (0,0) -- (0,3) -- (1,3.5) -- (2,3) -- (2,0) -- (1,-0.5) -- cycle;
\node at (1,1.5) {\large ALU};

% Operand inputs (top)
\node[above] at (0.5,3.25) {$A$};
\draw[->] (0.5,4) -- (0.5,3.25);
\node[above] at (1.5,3.25) {$B$};
\draw[->] (1.5,4) -- (1.5,3.25);

% Result output (bottom)
\node[below] at (1,-0.5) {Result};
\draw[->] (1,-0.5) -- (1,-1.5);

% Control input (side)
\node[right] at (2,1.5) {\small ALUOp};
\draw[->] (3,1.5) -- (2,1.5);

% Status flags (side outputs)
\node[left] at (0,2.5) {\tiny Z};      % Zero flag
\node[left] at (0,2.0) {\tiny N};      % Negative
\node[left] at (0,1.5) {\tiny C};      % Carry
\node[left] at (0,1.0) {\tiny V};      % Overflow

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TIMING DIAGRAMS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
% Manual timing diagram with scope environment
% Clock signal MUST be at TOP. Each signal on its own horizontal row.
% Digital signals as rectangular waveforms (high=1, low=0).
% Signal transitions as vertical edges. Label each signal on LEFT.

\begin{scope}[xscale=0.8, yscale=0.6]
  % Clock signal (TOP ROW)
  \draw (0,8) node[left] {\small CLK};
  \draw[thick] (0,8) -- (1,8) -- (1,9) -- (2,9) -- (2,8) -- (3,8) -- (3,9) -- (4,9) -- (4,8) -- (5,8) -- (5,9) -- (6,9) -- (6,8);

  % Enable signal
  \draw (0,6) node[left] {\small EN};
  \draw[thick] (0,7) -- (2,7) -- (2,6) -- (3,6) -- (3,7) -- (6,7);

  % Data signal
  \draw (0,4) node[left] {\small D};
  \draw[thick] (0,4) -- (0.5,4) -- (0.5,5) -- (2.5,5) -- (2.5,4) -- (4,4) -- (4,5) -- (6,5);

  % Q output — LEFT BLANK for student to complete (do NOT draw actual waveform)
  \draw (0,2) node[left] {\small Q};
  \draw[dashed, gray] (0,2.5) -- (6,2.5);  % blank placeholder line
  \node[gray] at (3,2.5) {?};              % question mark indicating student must draw

  % Decoder output — LEFT BLANK for student to complete
  \draw (0,0) node[left] {\small Det};
  \draw[dashed, gray] (0,0.5) -- (6,0.5);  % blank placeholder line
  \node[gray] at (3,0.5) {?};              % question mark

  % Vertical dashed lines at clock edges for alignment
  \foreach \x in {1,2,3,4,5,6} {
    \draw[dotted, gray!50] (\x,-0.5) -- (\x,9.5);
  }

  % Time markers
  \node[below] at (0,-0.5) {\tiny $t_0$};
  \node[below] at (1,-0.5) {\tiny $t_1$};
  \node[below] at (2,-0.5) {\tiny $t_2$};
\end{scope}

% TIMING DIAGRAM RULES:
% - Clock signal ALWAYS at TOP
% - All signals vertically aligned with consistent time scale
% - Each signal labeled on LEFT side (CLK, D, Q, RST, EN, etc.)
% - High level at top, low level at bottom for each signal trace
% - Transition edges MUST be vertical (or near-vertical for rise/fall time)
% - Causality: output transitions slightly AFTER input transitions
% - Vertical dashed lines at clock edges for alignment
% - Time markers at bottom if specific timing values given
% - ANSWER HIDING: OUTPUT signals (Q, Q1, Q2, Q̄, Y) must be drawn as
%   BLANK dashed lines with "?" labels — students must fill them in
% - Only draw INPUT waveforms (CLK, D, EN, RESET) with actual values
% - For rising-edge triggered D-FF: Q changes at rising CLK edges (low→high)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SETUP/HOLD TIMING CONSTRAINTS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
% Shaded setup time region BEFORE clock edge
\fill[blue!20] (t_setup,y_low) rectangle (t_clk,y_high);
\node at (t_middle, y_label) {$t_{su}$};

% Shaded hold time region AFTER clock edge (different color)
\fill[red!20] (t_clk,y_low) rectangle (t_hold,y_high);
\node at (t_middle, y_label) {$t_h$};

% Clock edge marker
\draw[thick, ->] (t_clk, y_clk_low) -- (t_clk, y_clk_high);

% Double-headed arrows for timing measurements
\draw[<->] (t1, y_arrow) -- (t2, y_arrow) node[midway, above] {$t_{su}$};

% Clock-to-Q delay
\draw[<->] (t_clk, y) -- (t_q_change, y) node[midway, above] {$t_{clk \to Q}$};

% RULES:
% - Setup time (tsu): data must be stable BEFORE clock edge
% - Hold time (th): data must remain stable AFTER clock edge
% - Use different shading for setup vs hold regions
% - Metastability region shown if illustrating CDC concepts
% - Annotations: tsu, th, tpd, tclk→Q

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FSM STATE DIAGRAMS (use tikz automata)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
% Add to preamble: \usetikzlibrary{automata, positioning}

\begin{tikzpicture}[node distance=2.5cm, auto]
  % States as circles with labels inside
  \node[state, initial]         (S0) {$S_0$};
  \node[state, right of=S0]     (S1) {$S_1$};
  \node[state, below of=S1]     (S2) {$S_2$};
  \node[state, accepting, left of=S2] (S3) {$S_3$};

  % Transitions as labeled arrows
  \path[->]
    (S0) edge node {$0$} (S1)
    (S0) edge [loop above] node {$1$} ()
    (S1) edge node {$1$} (S2)
    (S2) edge node {$0$} (S3)
    (S3) edge node {$1$} (S0);
\end{tikzpicture}

% Moore machine: output inside state circle
\node[state] (S0) {$S_0$\\$Y=1$};

% Mealy machine: input/output on transition arrow
\path[->] (S0) edge node {$A/Y$} (S1);

% Self-loop for transitions staying in same state
\path[->] (S0) edge [loop above] node {$0/0$} ();

% Reset transition (to initial state from RESET)
\draw[->] (-1.5,0) -- (S0) node[above, midway] {RST};

% FSM RULES:
% - States as CIRCLES with state name inside
% - INITIAL state: incoming arrow from outside (no source node)
% - Accepting/final states: double circle or bold outline
% - ALL transitions accounted for (every input from every state)
% - Moore: output inside state circle
% - Mealy: input/output on transition arrow notation
% - State encoding noted if specified (binary, one-hot, gray)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
VERILOG / HDL MODULE DIAGRAMS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
% Module as rectangular block with labeled input/output ports

\draw[thick] (0,0) rectangle (5,4);
\node at (2.5,3.5) {\textbf{module\_name}};

% Input ports on LEFT with arrows pointing IN
\draw[->] (-1,3) -- (0,3) node[left, xshift=-10pt] {clk};
\draw[->] (-1,2.5) -- (0,2.5) node[left, xshift=-10pt] {rst\_n};
\draw[->] (-1,2) -- (0,2) node[left, xshift=-10pt] {data\_in[7:0]};
\draw[->] (-1,1) -- (0,1) node[left, xshift=-10pt] {en};

% Output ports on RIGHT with arrows pointing OUT
\draw[->] (5,3) -- (6,3) node[right] {data\_out[7:0]};
\draw[->] (5,2) -- (6,2) node[right] {valid};

% Bus widths in brackets
\draw[line width=2pt] (-1.5,2) -- (0,2);  % thick line for bus
\draw (-0.75,1.8) -- (-0.75,2.2);
\node[above] at (-0.75,2) {\tiny /8};

% RULES:
% - Module name at TOP CENTER
% - Inputs on LEFT, outputs on RIGHT
% - Bidirectional (inout) with double-headed arrows
% - Bus widths shown in brackets: [7:0], [15:0]
% - Clock (clk) and reset (rst, rst_n) clearly marked
% - Active-low signals: _n suffix or overbar

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BUS & INTERFACE NOTATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
% Thick line for bus
\draw[line width=2pt] (0,0) -- (5,0);
\node[above] at (2.5,0) {DATA[7:0]};

% Bus with slash notation for width
\draw (0,0) -- (5,0);
\draw (2.5,-0.2) -- (2.5,0.2);
\node[above right] at (2.5,0) {/8};

% Direction arrows on bus segments
\draw[->, line width=2pt] (0,0) -- (5,0);  % unidirectional
\draw[<->, line width=2pt] (0,0) -- (5,0); % bidirectional

% Read/Write control signals
\node at (x,y) {R/$\overline{W}$};   % R/W-bar notation

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CLOCK DOMAIN CROSSING (CDC)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
% Separate clock domains with dashed boundary line

% Domain boundary
\draw[dashed, thick, blue] (5,-1) -- (5,6) node[above] {\small CDC Boundary};

% Left domain: CLK_A
\node[above] at (2.5,5.5) {\small Clock Domain A};
\draw[thick] (1,2) rectangle (3,4);
\node at (2,3) {Source\\Logic};

% Right domain: CLK_B — 2-FF synchronizer
\node[above] at (7.5,5.5) {\small Clock Domain B};
% Synchronizer FF1
\draw[thick] (6,2) rectangle (7.5,4);
\node at (6.75,3) {\small FF1};
\draw (6,2.3) -- (6.3,2.5) -- (6,2.7);   % CLK edge
% Synchronizer FF2
\draw[thick] (8.5,2) rectangle (10,4);
\node at (9.25,3) {\small FF2};
\draw (8.5,2.3) -- (8.8,2.5) -- (8.5,2.7);
% Chain
\draw[->] (3,3) -- (6,3) node[midway, above] {\small async\_in};
\draw[->] (7.5,3) -- (8.5,3);
\draw[->] (10,3) -- (11,3) node[right] {\small sync\_out};

% Metastability annotation
\node[below, red!60!black, font=\tiny] at (7,2) {metastable\\window};

% RULES:
% - Different clock domains clearly separated (dashed boundary)
% - Synchronizer: minimum 2 flip-flops in series at boundary
% - Clock signals for each domain labeled (clk_a, clk_b)
% - FIFO for multi-bit data crossing with dual-port indication

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CRITICAL ― NEVER REVEAL ANSWERS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
These diagrams are for STUDENT ASSIGNMENTS. The student must solve the problem.
- NEVER annotate wires with computed voltages or currents
- NEVER show the answer (e.g. "I_D = 1.35 mA")
- NEVER show output values ("Output = 0", "Y = 1")
- NEVER show boolean expressions or truth tables on the diagram
- NEVER show signal values (0/1) annotated on wires
- DO show all given values from the question (Vgs=3V, Vth=1V, kn=300µA/V²)
- DO label terminals (G, D, S) and node names (VDD, GND, V_out)
- DO show circuit structure and given parameters ONLY
- DO label all inputs with variable names (A, B, C) NOT specific values

Return ONLY the complete LaTeX document. Nothing else."""

    def _build_user_prompt(
        self,
        question_text: str,
        description: str,
        subject_context: str = "",
    ) -> str:
        subject_section = (
            f"\n**Subject Context:** {subject_context}\n" if subject_context else ""
        )
        return f"""Generate a professional CircuiTikZ circuit diagram for this student assignment question.

**Question:** {question_text}

**Circuit Description:** {description}
{subject_section}
**Requirements:**
1. Match ALL component values and labels EXACTLY as stated in the question
2. Use standalone + circuitikz with american style and siunitx
3. For MOSFET/transistor circuits: vertical Sedra & Smith layout (VDD top, GND bottom)
4. For logic/schematic circuits: left-to-right signal flow
5. Label all terminals: D, G, S for MOSFETs; + / − for sources
6. All values in proper SI units via \\SI{{}}{{}}
7. Clean orthogonal wiring only — no diagonal wires

Return ONLY the complete LaTeX document starting with \\documentclass."""

    # ──────────────────────────────────────────────────────────────────────────
    #  LaTeX extraction / cleanup
    # ──────────────────────────────────────────────────────────────────────────

    def _extract_latex(self, response: str) -> str:
        """Strip markdown fences and return raw LaTeX."""
        for fence in ("```latex", "```tex", "```"):
            if fence in response:
                start = response.find(fence) + len(fence)
                end = response.find("```", start)
                if end != -1:
                    candidate = response[start:end].strip()
                    if "\\documentclass" in candidate:
                        return candidate

        # Try to find documentclass directly
        match = re.search(r"(\\documentclass[\s\S]*?\\end\{document\})", response)
        if match:
            return match.group(1).strip()

        return response.strip()

    # ──────────────────────────────────────────────────────────────────────────
    #  Core generation
    # ──────────────────────────────────────────────────────────────────────────

    async def generate_circuit_latex(
        self,
        question_text: str,
        diagram_description: str = "",
        subject_context: str = "",
    ) -> str:
        """
        Ask Claude to produce a CircuiTikZ LaTeX document.

        Returns:
            Raw LaTeX string (complete document)
        """
        if self._api_key_valid is False:
            raise RuntimeError("Anthropic API key previously failed — skipping")

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                temperature=0.1,
                system=self._build_system_prompt(),
                messages=[
                    {
                        "role": "user",
                        "content": self._build_user_prompt(
                            question_text, diagram_description, subject_context
                        ),
                    }
                ],
            )
            self._api_key_valid = True
            latex = self._extract_latex(response.content[0].text.strip())

            if "\\documentclass" not in latex:
                raise ValueError("Claude did not return valid LaTeX document")

            logger.info(f"Claude generated {len(latex)} chars of CircuiTikZ LaTeX")
            return latex

        except Exception as e:
            err = str(e)
            if "401" in err or "authentication_error" in err:
                self._api_key_valid = False
                logger.error(f"Anthropic API key INVALID: {err}")
            logger.error(f"CircuiTikZ LaTeX generation failed: {err}")
            raise

    async def generate_circuit_png(
        self,
        question_text: str,
        diagram_description: str = "",
        output_dpi: int = 300,
        subject_context: str = "",
    ) -> bytes:
        """
        Full pipeline: Claude → LaTeX → pdflatex → pdf2image → PNG bytes.

        Args:
            question_text:      Full question text for context
            diagram_description: Short circuit description
            output_dpi:         PNG resolution (300 default = print quality)
            subject_context:    Optional subject hint

        Returns:
            PNG image bytes
        """
        if not PDF2IMAGE_AVAILABLE:
            raise RuntimeError(
                "pdf2image is not installed.\n"
                "Run: pip install pdf2image pillow\n"
                "Also install poppler: brew install poppler  (macOS) "
                "or  sudo yum install -y poppler-utils  (AWS Linux)"
            )

        if not os.path.isfile(PDFLATEX_PATH):
            raise RuntimeError(
                f"pdflatex not found at {PDFLATEX_PATH}. "
                "Install BasicTeX: brew install --cask basictex"
            )

        latex_src = await self.generate_circuit_latex(
            question_text, diagram_description, subject_context
        )

        tmpdir = tempfile.mkdtemp(prefix="circuitikz_")
        try:
            tex_file = os.path.join(tmpdir, "circuit.tex")
            pdf_file = os.path.join(tmpdir, "circuit.pdf")

            with open(tex_file, "w", encoding="utf-8") as fh:
                fh.write(latex_src)

            # Run pdflatex (twice to resolve cross-references, once is usually enough
            # for circuitikz but two passes eliminates any label warnings)
            pdflatex_env = {**os.environ, "PATH": f"/Library/TeX/texbin:{os.environ.get('PATH', '')}"}

            for _pass in range(2):
                result = subprocess.run(
                    [
                        PDFLATEX_PATH,
                        "-interaction=nonstopmode",
                        "-halt-on-error",
                        "-output-directory", tmpdir,
                        tex_file,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=60,
                    env=pdflatex_env,
                )
                if result.returncode != 0:
                    # Extract the useful error lines from pdflatex output
                    error_lines = [
                        l for l in result.stdout.splitlines()
                        if l.startswith("!") or "Error" in l or "error" in l
                    ]
                    error_summary = "\n".join(error_lines[:10]) or result.stdout[-500:]
                    logger.error(
                        f"pdflatex pass {_pass+1} failed (rc={result.returncode}):\n"
                        f"{error_summary}"
                    )
                    # Save .tex for debugging
                    debug_tex = os.path.join(tempfile.gettempdir(), "debug_circuit.tex")
                    with open(debug_tex, "w") as f:
                        f.write(latex_src)
                    logger.info(f"Debug LaTeX saved to {debug_tex}")
                    raise RuntimeError(
                        f"pdflatex compilation failed:\n{error_summary}"
                    )

            if not os.path.isfile(pdf_file):
                raise RuntimeError("pdflatex ran successfully but no PDF produced")

            # Convert PDF → PNG
            images = convert_from_path(
                pdf_file,
                dpi=output_dpi,
                fmt="png",
                single_file=True,
            )
            if not images:
                raise RuntimeError("pdf2image returned no images from PDF")

            buf = io.BytesIO()
            images[0].save(buf, format="PNG", optimize=True)
            png_bytes = buf.getvalue()

            logger.info(
                f"CircuiTikZ→PNG success: {len(png_bytes):,} bytes "
                f"({images[0].width}×{images[0].height}px at {output_dpi}dpi)"
            )
            return png_bytes

        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
