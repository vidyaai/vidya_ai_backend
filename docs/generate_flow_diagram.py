#!/usr/bin/env python3
"""
Assignment Generator Flow Diagram
Creates a professional block diagram of the assignment generation pipeline.
Output: assignment_generator_flow_diagram.pdf / .png
"""

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch
import os

# ── Palette ───────────────────────────────────────────────────────────────────
C_BG = "#F7F9FC"
C_ENTRY = "#1A365D"  # navy
C_ORCH = "#2B6CB0"  # blue
C_AI = "#276749"  # green
C_TOOL = "#C05621"  # orange
C_REVIEWER = "#553C9A"  # purple
C_STORAGE = "#702459"  # magenta
C_ROUTER = "#975A16"  # amber
C_RENDER = "#C53030"  # red

C_CLUSTER_MAIN = "#EBF8FF"
C_CLUSTER_DIAG = "#FFFAF0"
C_CLUSTER_RENDER = "#FFF5F5"

ARROW = "#4A5568"
DASH = "#A0AEC0"
FONT = "DejaVu Sans"

# ── Figure ────────────────────────────────────────────────────────────────────
fig = plt.figure(figsize=(20, 22), facecolor=C_BG)
ax = fig.add_axes([0, 0, 1, 1], facecolor=C_BG)
ax.set_xlim(0, 20)
ax.set_ylim(0, 22)
ax.axis("off")

# ── Helpers ───────────────────────────────────────────────────────────────────
def box(x, y, w, h, label, sub="", color="#2B6CB0", fs=10, tc="white", bold=True, z=4):
    rect = FancyBboxPatch(
        (x - w / 2, y - h / 2),
        w,
        h,
        boxstyle="round,pad=0.09",
        lw=1.6,
        edgecolor="white",
        facecolor=color,
        zorder=z,
    )
    ax.add_patch(rect)
    fw = "bold" if bold else "normal"
    if sub:
        ax.text(
            x,
            y + 0.14,
            label,
            ha="center",
            va="center",
            fontsize=fs,
            fontweight=fw,
            color=tc,
            zorder=z + 1,
            fontfamily=FONT,
        )
        ax.text(
            x,
            y - 0.22,
            sub,
            ha="center",
            va="center",
            fontsize=fs - 1.5,
            color=tc,
            alpha=0.88,
            zorder=z + 1,
            fontfamily=FONT,
        )
    else:
        ax.text(
            x,
            y,
            label,
            ha="center",
            va="center",
            fontsize=fs,
            fontweight=fw,
            color=tc,
            zorder=z + 1,
            fontfamily=FONT,
        )


def cluster(x, y, w, h, label, fc, ec, z=1):
    rect = FancyBboxPatch(
        (x, y),
        w,
        h,
        boxstyle="round,pad=0.15",
        lw=2,
        edgecolor=ec,
        facecolor=fc,
        alpha=0.55,
        zorder=z,
    )
    ax.add_patch(rect)
    ax.text(
        x + w / 2,
        y + h + 0.05,
        label,
        ha="center",
        va="bottom",
        fontsize=10.5,
        fontweight="bold",
        color=ec,
        fontfamily=FONT,
        zorder=z + 1,
    )


def arr(x1, y1, x2, y2, label="", dashed=False, lw=1.6):
    c = DASH if dashed else ARROW
    ls = "dashed" if dashed else "solid"
    ax.annotate(
        "",
        xy=(x2, y2),
        xytext=(x1, y1),
        arrowprops=dict(
            arrowstyle="->",
            color=c,
            lw=lw,
            linestyle=ls,
            connectionstyle="arc3,rad=0.0",
        ),
    )
    if label:
        ax.text(
            (x1 + x2) / 2 + 0.12,
            (y1 + y2) / 2,
            label,
            ha="left",
            va="center",
            fontsize=8,
            color=c,
            fontstyle="italic",
            fontfamily=FONT,
        )


def arr_bend(x1, y1, x2, y2, label="", dashed=False, rad=0.25):
    c = DASH if dashed else ARROW
    ls = "dashed" if dashed else "solid"
    ax.annotate(
        "",
        xy=(x2, y2),
        xytext=(x1, y1),
        arrowprops=dict(
            arrowstyle="->",
            color=c,
            lw=1.4,
            linestyle=ls,
            connectionstyle=f"arc3,rad={rad}",
        ),
    )
    if label:
        ax.text(
            (x1 + x2) / 2,
            (y1 + y2) / 2 + 0.12,
            label,
            ha="center",
            va="bottom",
            fontsize=8,
            color=c,
            fontstyle="italic",
            fontfamily=FONT,
        )


# ═══════════════════════════════════════════════════════════════════════════════
#  NODES & CLUSTERS
# ═══════════════════════════════════════════════════════════════════════════════

# Title
ax.text(
    10,
    21.55,
    "Vidya AI — Assignment Generator Flow",
    ha="center",
    va="center",
    fontsize=18,
    fontweight="bold",
    color="#1A202C",
    fontfamily=FONT,
)
ax.text(
    10,
    21.1,
    "End-to-end pipeline: from HTTP request to stored assignment",
    ha="center",
    va="center",
    fontsize=11,
    color="#4A5568",
    fontfamily=FONT,
)

# 1. API Route
box(
    10,
    20.35,
    5.5,
    0.75,
    "HTTP API Route",
    "POST /api/assignments/generate",
    color=C_ENTRY,
    fs=10.5,
)

# ── Main Orchestrator cluster ─────────────────────────────────────────────────
cluster(
    1.2,
    6.8,
    17.6,
    12.9,
    "AssignmentGenerator  (Main Orchestrator)",
    C_CLUSTER_MAIN,
    C_ORCH,
    z=1,
)

# Stage 1
box(
    10,
    19.45,
    5.5,
    0.75,
    "Stage 1 · Content Extraction",
    "DocumentProcessor  (PDF / DOCX / Video transcripts)",
    color="#3182CE",
    fs=10,
)

# Stage 2
box(
    10,
    18.3,
    5.5,
    0.75,
    "Stage 2 · Question Generation Agent",
    "GPT-4o  ·  Structured Output (Pydantic)",
    color=C_AI,
    fs=10,
)

# Equation Extractor (side)
box(
    16.4,
    18.3,
    3.8,
    0.75,
    "Equation Extractor",
    "GPT-4o  ·  LaTeX / placeholder IDs",
    color=C_AI,
    fs=9.5,
)

# Stage 3 label
box(
    10,
    17.15,
    5.5,
    0.75,
    "Stage 3 · Diagram Analysis Agent",
    "Multi-Agent orchestration  →  see cluster below",
    color=C_TOOL,
    fs=10,
)

# Stage 4
box(
    10,
    7.45,
    5.5,
    0.75,
    "Stage 4 · Question Review Agent",
    "GPT-4o  ·  Alignment & quality validation",
    color=C_REVIEWER,
    fs=10,
)

# ── Diagram Analysis Agent cluster ───────────────────────────────────────────
cluster(
    1.5,
    8.35,
    17.0,
    8.4,
    "Diagram Analysis Agent  (Multi-Agent System)",
    C_CLUSTER_DIAG,
    C_TOOL,
    z=2,
)

# Domain Router
box(
    5.5,
    16.25,
    4.4,
    0.75,
    "Domain Router",
    "GPT-4o-mini  ·  domain / diagram_type / ai_suitable",
    color=C_ROUTER,
    fs=9.5,
    tc="white",
)

# Subject Prompt Registry
box(
    14.5,
    16.25,
    4.4,
    0.75,
    "Subject Prompt Registry",
    "Guidance injection  ·  per-domain prompts",
    color=C_ROUTER,
    fs=9.5,
    tc="white",
)

# Tool Selection
box(
    10,
    15.1,
    4.8,
    0.75,
    "Tool Selection Agent",
    "GPT-4o  ·  tool_choice=auto",
    color=C_TOOL,
    fs=10,
)

# Fallback Router
box(
    15.7,
    15.1,
    3.3,
    0.75,
    "Fallback Router",
    "domain → tool mapping",
    color=C_ROUTER,
    fs=9.5,
    tc="white",
)

# ── Rendering cluster ──────────────────────────────────────────────────────────
cluster(2.0, 10.3, 16.0, 4.3, "Rendering Engine", C_CLUSTER_RENDER, "#E53E3E", z=3)

box(
    5.0,
    13.8,
    4.0,
    0.75,
    "Circuitikz Tool",
    "LaTeX → compiled PDF/PNG",
    color=C_RENDER,
    fs=9.5,
)
box(
    10.0,
    13.8,
    4.2,
    0.75,
    "Claude Code Tool",
    "Claude API → Matplotlib / NetworkX",
    color=C_RENDER,
    fs=9.5,
)
box(
    15.2,
    13.8,
    3.8,
    0.75,
    "Gemini Image Gen",
    "Gemini 2.5 Flash / Pro",
    color=C_RENDER,
    fs=9.5,
)

# Diagram Executor
box(
    7.5,
    12.5,
    5.0,
    0.75,
    "Diagram Executor",
    "DiagramGenerator  ·  render & encode PNG",
    color="#9B2C2C",
    fs=9.5,
)

# Gemini Reviewer
box(
    10,
    11.2,
    5.0,
    0.75,
    "Gemini Diagram Reviewer",
    "Gemini 2.5 Pro Vision  ·  technical validation",
    color=C_REVIEWER,
    fs=9.5,
)

# Retry annotation
ax.text(
    15.6,
    11.2,
    "↺ retry loop\n(max 3 attempts)",
    ha="center",
    va="center",
    fontsize=8.5,
    color="#744210",
    fontstyle="italic",
    bbox=dict(
        boxstyle="round,pad=0.3", facecolor="#FEFCBF", edgecolor="#D69E2E", alpha=0.9
    ),
    zorder=6,
)

# Upload node
box(
    10,
    9.9,
    4.2,
    0.65,
    "Upload to AWS S3",
    "s3://vidya-diagrams/<assignment_id>/",
    color="#6B46C1",
    fs=9,
    bold=False,
)

# ── Storage ───────────────────────────────────────────────────────────────────
box(5.5, 6.5, 4.0, 0.75, "AWS S3", "Diagram image storage", color=C_STORAGE, fs=9.5)
box(
    14.5,
    6.5,
    4.0,
    0.75,
    "Database",
    "Assignment + questions store",
    color=C_ENTRY,
    fs=9.5,
)

# ═══════════════════════════════════════════════════════════════════════════════
#  ARROWS
# ═══════════════════════════════════════════════════════════════════════════════

# Entry → Stage 1
arr(10, 19.97, 10, 19.82)

# Stage 1 → Stage 2
arr(10, 19.07, 10, 18.67)

# Stage 2 ↔ Equation Extractor
arr(12.75, 18.3, 14.5, 18.3, label="extract", dashed=True)
arr_bend(16.4, 17.93, 12.75, 18.13, label="return w/ LaTeX", dashed=True, rad=-0.25)

# Stage 2 → Stage 3
arr(10, 17.93, 10, 17.53)

# Stage 3 → Domain Router
arr(8.05, 16.78, 6.0, 16.62)

# Stage 3 → Subject Prompt Registry
arr(11.95, 16.78, 13.8, 16.62)

# Domain Router → Tool Selection
arr(5.5, 15.88, 8.15, 15.48)

# Subject Registry → Tool Selection
arr(14.5, 15.88, 11.85, 15.48)

# Tool Selection → Fallback Router
arr(12.4, 15.1, 14.05, 15.1, label="fallback", dashed=True)

# Tool Selection → 3 rendering tools
arr(7.5, 14.72, 5.0, 14.17)
arr(10.0, 14.72, 10.0, 14.17)
arr(12.5, 14.72, 15.0, 14.17)

# Fallback → renders
arr_bend(15.7, 14.72, 5.3, 14.17, dashed=True, rad=0.0)

# Circuitikz + Claude Code → Executor
arr(5.0, 13.42, 7.0, 12.88)
arr(10.0, 13.42, 9.0, 12.88)

# Gemini Image Gen → Reviewer (bypass Executor)
arr(15.2, 13.42, 11.7, 11.58)

# Executor → Reviewer
arr(9.5, 12.12, 9.8, 11.58)

# Reviewer retry annotation arrow
ax.annotate(
    "",
    xy=(13.0, 11.2),
    xytext=(12.5, 11.2),
    arrowprops=dict(
        arrowstyle="->",
        color="#D69E2E",
        lw=1.4,
        linestyle="dashed",
        connectionstyle="arc3,rad=0.0",
    ),
)

# Reviewer → Upload S3
arr(10, 10.82, 10, 10.23)

# Upload S3 → Stage 4
arr(10, 9.58, 10, 7.83)

# Stage 4 → Database
arr(12.75, 7.45, 12.5, 6.87)

# Upload (internal) → external S3 storage
arr_bend(8.0, 9.9, 5.5, 6.87, rad=0.3)

# ── Legend ────────────────────────────────────────────────────────────────────
lx, ly = 1.3, 6.0
ax.text(
    lx, ly, "Legend:", fontsize=9.5, fontweight="bold", color="#2D3748", fontfamily=FONT
)
items = [
    (C_ENTRY, "Entry / Storage"),
    (C_AI, "AI Agent  (GPT-4o)"),
    (C_TOOL, "Tool Executor / Orchestrator"),
    (C_REVIEWER, "Reviewer Agent"),
    (C_ROUTER, "Router / Registry"),
    (C_RENDER, "Rendering Tool"),
]
for i, (c, lbl) in enumerate(items):
    xi = lx + (i % 3) * 5.8
    yi = ly - 0.58 - (i // 3) * 0.58
    rect = FancyBboxPatch(
        (xi, yi - 0.17),
        0.55,
        0.35,
        boxstyle="round,pad=0.04",
        facecolor=c,
        edgecolor="white",
        lw=1,
        zorder=5,
    )
    ax.add_patch(rect)
    ax.text(
        xi + 0.72, yi, lbl, va="center", fontsize=8.5, color="#2D3748", fontfamily=FONT
    )

# Footer
ax.text(
    10,
    0.25,
    "Vidya AI Backend  ·  Assignment Generation Pipeline  ·  2026",
    ha="center",
    va="center",
    fontsize=8.5,
    color="#A0AEC0",
    fontfamily=FONT,
)

# ── Save ──────────────────────────────────────────────────────────────────────
DOCS = os.path.dirname(__file__)
out = os.path.join(DOCS, "assignment_generator_flow_diagram")
plt.savefig(out + ".pdf", format="pdf", dpi=150, bbox_inches="tight", facecolor=C_BG)
plt.savefig(out + ".png", format="png", dpi=150, bbox_inches="tight", facecolor=C_BG)
print(f"Saved: {out}.pdf")
print(f"Saved: {out}.png")
