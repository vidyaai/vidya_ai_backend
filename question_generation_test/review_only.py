#!/usr/bin/env python3
"""
Review-only script — runs the Gemini reviewer on already-generated diagrams
in question_papers2/ without regenerating anything.

Usage:
    cd vidya_ai_backend
    python question_generation_test/review_only.py
"""

import sys
import os
import re
import json
import asyncio
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"), override=True)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from utils.gemini_diagram_reviewer import GeminiDiagramReviewer
from controllers.config import logger

import requests


def download_image(url: str) -> bytes | None:
    try:
        resp = requests.get(url, timeout=20)
        if resp.status_code == 200:
            return resp.content
    except Exception as e:
        logger.warning(f"Failed to download {url}: {e}")
    return None


async def review_paper(paper_path: Path, reviewer: GeminiDiagramReviewer) -> list[dict]:
    data = json.loads(paper_path.read_text())
    topic = data.get("topic", paper_path.stem)
    questions = data.get("questions", [])
    results = []

    for i, q in enumerate(questions):
        diag = q.get("diagram") or {}
        url = diag.get("s3_url") or diag.get("url") or ""
        q_text = q.get("question", q.get("text", ""))

        if not url:
            results.append({"q": i + 1, "status": "NO_DIAGRAM", "failure_type": "-", "reason": ""})
            continue

        img_bytes = download_image(url)
        if not img_bytes:
            results.append({"q": i + 1, "status": "DOWNLOAD_FAIL", "failure_type": "-", "reason": ""})
            continue

        # Strip <eq qN_eqM> placeholders — same as the inline reviewer does
        clean_q_text = re.sub(r"<eq\s+\S+>", "", q_text).strip()

        # Use the description exactly as saved during generation — this matches
        # what diagram_agent.py passes to the inline reviewer at the final attempt,
        # including any IMPORTANT:/CRITICAL:/CUMULATIVE LEAK CORRECTIONS: markers.
        diagram_description = diag.get("description") or clean_q_text

        result = await reviewer.review_diagram(
            image_bytes=img_bytes,
            question_text=clean_q_text,
            diagram_description=diagram_description,
            user_prompt_context=data.get("prompt", ""),
            domain=diag.get("domain", ""),
            diagram_type=diag.get("diagram_type", ""),
        )

        status = "PASS" if result["passed"] else "FAIL"
        failure_type = result.get("failure_type", "-") if not result["passed"] else "-"
        print(f"  Q{i+1}: {status} ({failure_type}) — {result['reason'][:80]}")
        results.append({
            "q": i + 1,
            "status": status,
            "failure_type": failure_type,
            "reason": result["reason"],
        })

    return results


async def main():
    base = Path(__file__).parent
    folder = sys.argv[1] if len(sys.argv) > 1 else "question_papers2"
    papers_dir = base / folder

    json_files = sorted(
        f for f in papers_dir.glob("*.json") if f.name != "batch_results.json"
    )

    reviewer = GeminiDiagramReviewer()

    all_results = []

    for pf in json_files:
        data = json.loads(pf.read_text())
        topic = data.get("topic", pf.stem)
        print(f"\n{'='*60}")
        print(f"{pf.name} — {topic}")
        print(f"{'='*60}")

        results = await review_paper(pf, reviewer)
        all_results.append({"topic": topic, "file": pf.name, "questions": results})

    # Print summary table
    print(f"\n\n{'='*100}")
    print(f"REVIEW RESULTS SUMMARY — {folder}")
    print(f"{'='*100}")
    header = f"{'#':>2}  {'Topic':<42}  {'Q1':^12}  {'Q2':^12}  {'Q3':^12}  {'Q4':^12}  {'Q5':^12}  {'Pass':>5}"
    print(header)
    print("-" * 100)

    total_pass = 0
    total_diagrams = 0

    for idx, paper in enumerate(all_results, 1):
        qs = paper["questions"]
        cells = []
        paper_pass = 0
        paper_total = 0
        for q in qs:
            if q["status"] == "PASS":
                cells.append("PASS")
                paper_pass += 1
                paper_total += 1
            elif q["status"] == "FAIL":
                ft = q["failure_type"] or "fail"
                cells.append(f"FAIL({ft[:6]})")
                paper_total += 1
            else:
                cells.append(q["status"])

        # Pad to 5
        while len(cells) < 5:
            cells.append("-")

        total_pass += paper_pass
        total_diagrams += paper_total

        row = (
            f"{idx:>2}  "
            f"{paper['topic']:<42}  "
            + "  ".join(f"{c:^12}" for c in cells)
            + f"  {paper_pass}/{paper_total:>1}"
        )
        print(row)

    print("-" * 100)
    print(f"TOTAL: {total_pass}/{total_diagrams} passed ({100*total_pass//total_diagrams if total_diagrams else 0}%)")
    print(f"{'='*100}\n")


if __name__ == "__main__":
    asyncio.run(main())
