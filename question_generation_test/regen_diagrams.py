#!/usr/bin/env python3
"""
Diagram regeneration script — re-runs diagram generation for all 10 existing
question papers using the improved anti-leak pipeline (3-attempt review loop).

Reads questions from question_papers/, regenerates all diagrams, and saves
updated JSON + PDFs to question_papers2/.

Usage:
    cd vidya_ai_backend
    python question_generation_test/regen_diagrams.py
"""

import sys
import os
import json
import time
import traceback
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"), override=True)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from utils.diagram_agent import DiagramAnalysisAgent
from utils.pdf_generator import AssignmentPDFGenerator
from controllers.config import logger


def load_papers(input_dir: Path) -> list:
    """Load all 10 question JSON files, sorted by paper number."""
    files = sorted(
        [f for f in input_dir.glob("*.json") if f.name != "batch_results.json"]
    )
    papers = []
    for f in files:
        data = json.loads(f.read_text())
        papers.append({
            "filename": f.name,
            "topic": data.get("topic", f.stem),
            "subject": data.get("subject", "engineering"),
            "prompt": data.get("prompt", ""),
            "questions": data.get("questions", []),
        })
    return papers


def strip_diagrams(questions: list) -> list:
    """
    Remove existing diagram data so the agent regenerates from scratch.
    Keeps hasDiagram=True for diagram-analysis questions so the agent
    knows they need diagrams.
    """
    stripped = []
    for q in questions:
        q2 = dict(q)
        # Clear the old S3 reference — force regeneration
        q2["diagram"] = None
        # Keep hasDiagram=True if the question type expects one, but
        # set it to False so the agent re-evaluates and re-generates.
        q2["hasDiagram"] = False
        stripped.append(q2)
    return stripped


def regen_paper(paper: dict, paper_idx: int, output_dir: Path) -> dict:
    topic = paper["topic"]
    subject = paper["subject"]
    print(f"\n{'='*60}")
    print(f"[{paper_idx}/10] {topic}")
    print(f"{'='*60}")

    start = time.time()
    result = {
        "id": paper_idx,
        "topic": topic,
        "subject": subject,
        "status": "FAIL",
        "questions": 0,
        "diagrams": 0,
        "tools_used": [],
        "pdf_kb": 0,
        "time_s": 0,
        "error": "",
    }

    try:
        assignment_id = f"batch_regen_{paper_idx}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        # Strip diagrams so the agent regenerates all of them
        questions = strip_diagrams(paper["questions"])

        # Run diagram generation with improved pipeline (3-attempt review loop)
        agent = DiagramAnalysisAgent(engine="nonai", subject=subject)
        questions = agent.analyze_and_generate_diagrams(
            questions=questions,
            assignment_id=assignment_id,
            has_diagram_analysis=True,
            generation_prompt=paper["prompt"],
        )

        diagram_count = sum(1 for q in questions if q.get("hasDiagram"))

        # Collect tools used
        tools_used = set()
        for q in questions:
            diag = q.get("diagram") or {}
            tool = diag.get("tool") or diag.get("generator") or ""
            if tool:
                tools_used.add(tool)

        # Generate PDF
        safe_topic = (
            topic.replace(" ", "_")
            .replace("(", "").replace(")", "")
            .replace("&", "and").replace("/", "-")
        )
        pdf_generator = AssignmentPDFGenerator()
        pdf_assignment = {
            "title": f"{topic} — Graduate Exam",
            "description": f"Diagram-based questions on {topic}",
            "total_points": sum(q.get("points", 10) for q in questions),
            "questions": questions,
        }
        pdf_bytes = pdf_generator.generate_assignment_pdf(pdf_assignment)

        pdf_filename = f"{paper_idx:02d}_{safe_topic}.pdf"
        pdf_path = output_dir / pdf_filename
        with open(pdf_path, "wb") as f:
            f.write(pdf_bytes)

        json_path = output_dir / f"{paper_idx:02d}_{safe_topic}.json"
        with open(json_path, "w") as f:
            json.dump({
                "topic": topic,
                "subject": subject,
                "prompt": paper["prompt"],
                "questions": questions,
                "statistics": {
                    "total_questions": len(questions),
                    "questions_with_diagrams": diagram_count,
                },
            }, f, indent=2)

        elapsed = time.time() - start
        result.update({
            "status": "OK",
            "questions": len(questions),
            "diagrams": diagram_count,
            "tools_used": sorted(tools_used) or ["claude_code"],
            "pdf_kb": round(len(pdf_bytes) / 1024, 1),
            "time_s": round(elapsed, 0),
            "pdf_file": pdf_filename,
        })
        print(f"  OK  {len(questions)} questions, {diagram_count} diagrams — {pdf_filename} ({result['pdf_kb']} KB)")

    except Exception as e:
        elapsed = time.time() - start
        result["time_s"] = round(elapsed, 0)
        result["error"] = str(e)[:120]
        print(f"  FAIL: {e}")
        logger.error(f"Paper {paper_idx} ({topic}) failed", exc_info=True)

    return result


def print_table(results: list):
    print(f"\n\n{'='*110}")
    print("REGEN RESULTS SUMMARY")
    print(f"{'='*110}")
    header = f"{'#':>2}  {'Topic':<40}  {'Subj':<10}  {'Status':<6}  {'Qs':>3}  {'Diags':>5}  {'PDF KB':>7}  {'Time(s)':>7}  {'Error / Tools':<20}"
    print(header)
    print("-" * 110)
    for r in results:
        tools_or_err = r["error"] if r["status"] == "FAIL" else ", ".join(r.get("tools_used", []))
        row = (
            f"{r['id']:>2}  "
            f"{r['topic']:<40}  "
            f"{r['subject']:<10}  "
            f"{r['status']:<6}  "
            f"{r['questions']:>3}  "
            f"{r['diagrams']:>5}  "
            f"{r['pdf_kb']:>7}  "
            f"{r['time_s']:>7.0f}  "
            f"{tools_or_err:<20}"
        )
        print(row)
    print("-" * 110)
    ok = sum(1 for r in results if r["status"] == "OK")
    total_diags = sum(r["diagrams"] for r in results)
    total_time = sum(r["time_s"] for r in results)
    print(f"  {'TOTAL':<40}    {'':<10}    {ok}/10  {sum(r['questions'] for r in results):>3}  {total_diags:>5}  {'':>7}  {total_time:>7.0f}")
    print(f"{'='*110}\n")


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="question_papers", help="Input folder name")
    parser.add_argument("--output", default="question_papers2", help="Output folder name")
    args = parser.parse_args()

    base = Path(__file__).parent
    input_dir = base / args.input
    output_dir = base / args.output
    output_dir.mkdir(exist_ok=True)

    print(f"\n{'='*60}")
    print("DIAGRAM REGENERATION — 10 PAPERS (IMPROVED PIPELINE)")
    print(f"{'='*60}")
    print(f"Input:  {input_dir}")
    print(f"Output: {output_dir}")
    print(f"Engine: nonai | Review loop: 3 attempts | Anti-leak: ON")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    papers = load_papers(input_dir)
    print(f"Loaded {len(papers)} papers\n")

    results = []
    for idx, paper in enumerate(papers, 1):
        result = regen_paper(paper, idx, output_dir)
        results.append(result)

    print_table(results)

    results_path = output_dir / "batch_results.json"
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"Results saved to: {results_path}")

    ok = sum(1 for r in results if r["status"] == "OK")
    print(f"\n{'='*60}")
    print(f"COMPLETE: {ok}/{len(papers)} papers regenerated")
    print(f"PDFs saved to: {output_dir}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
