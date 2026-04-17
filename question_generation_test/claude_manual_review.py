#!/usr/bin/env python3
"""
Manual diagram review using Claude Opus — sends each diagram image directly
to Claude Opus and asks it to assess correctness, answer leaks, labels, readability.
"""

import json
import re
import base64
import requests
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from anthropic import Anthropic

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"), override=True)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

REVIEW_PROMPT_TEMPLATE = """You are reviewing an educational diagram for correctness and appropriateness as an exam question aid.

QUESTION: {question}

Review the attached diagram image and assess:
1. CORRECT TYPE: Is the diagram the right type for this question (e.g. right orbit type, right crystal structure, right chart type)?
2. ANSWER LEAK: Does the diagram directly reveal the answer the student is supposed to find, calculate, or identify?
3. LABELS: Are all key structural components mentioned in the question labeled clearly in the diagram?
4. READABLE: Is the text legible and the diagram usable?

Respond in this exact format:
VERDICT: PASS or FAIL
REASON: one clear sentence summarizing your verdict
ISSUES: list specific problems found, or "none" if PASS"""


def download_image(url: str) -> bytes | None:
    try:
        resp = requests.get(url, timeout=20)
        if resp.status_code == 200:
            return resp.content
    except Exception as e:
        print(f"    Download error: {e}", flush=True)
    return None


def review_with_claude(img_bytes: bytes, question_text: str) -> dict:
    img_b64 = base64.standard_b64encode(img_bytes).decode()
    prompt = REVIEW_PROMPT_TEMPLATE.format(question=question_text[:600])

    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=400,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": "image/png", "data": img_b64},
                },
                {"type": "text", "text": prompt},
            ],
        }],
    )
    text = response.content[0].text.strip()
    verdict = "PASS" if "VERDICT: PASS" in text else "FAIL"
    reason_match = re.search(r"REASON:\s*(.+)", text)
    issues_match = re.search(r"ISSUES:\s*(.+)", text)
    return {
        "verdict": verdict,
        "reason": reason_match.group(1).strip() if reason_match else text[:120],
        "issues": issues_match.group(1).strip() if issues_match else "none",
    }


def main():
    folder = sys.argv[1] if len(sys.argv) > 1 else "question_papers7"
    base = Path(__file__).parent / folder
    papers = sorted(f for f in base.glob("*.json") if f.name != "batch_results.json")

    all_results = []

    for paper_path in papers:
        data = json.loads(paper_path.read_text())
        topic = data.get("topic", paper_path.stem)
        questions = data.get("questions", [])
        paper_results = []

        print(f"\n{'='*60}", flush=True)
        print(f"{topic}", flush=True)
        print(f"{'='*60}", flush=True)

        for i, q in enumerate(questions, 1):
            diag = q.get("diagram") or {}
            url = diag.get("s3_url", "")
            # Substitute <eq id> placeholders with the per-question equations[]
            # entries so the reviewer sees concrete values (matches pdf_generator.py).
            raw_q_text = q.get("question", q.get("text", ""))
            eq_lookup = {e["id"]: e.get("latex", "") for e in q.get("equations", [])}
            q_text = re.sub(
                r"<eq\s+(\S+?)>",
                lambda m: eq_lookup.get(m.group(1), ""),
                raw_q_text,
            )

            if not url:
                paper_results.append({"q": i, "verdict": "NO_IMAGE", "reason": "No S3 URL", "issues": ""})
                print(f"  Q{i}: NO_IMAGE", flush=True)
                continue

            img_bytes = download_image(url)
            if not img_bytes:
                paper_results.append({"q": i, "verdict": "DOWNLOAD_FAIL", "reason": "Could not download", "issues": ""})
                print(f"  Q{i}: DOWNLOAD_FAIL", flush=True)
                continue

            try:
                result = review_with_claude(img_bytes, q_text)
                paper_results.append({"q": i, **result})
                print(f"  Q{i}: {result['verdict']} — {result['reason'][:80]}", flush=True)
            except Exception as e:
                paper_results.append({"q": i, "verdict": "ERROR", "reason": str(e)[:80], "issues": ""})
                print(f"  Q{i}: ERROR — {e}", flush=True)

        all_results.append({"topic": topic, "questions": paper_results})

    # Summary table
    print(f"\n\n{'='*115}")
    print(f"CLAUDE OPUS MANUAL REVIEW — {folder}")
    print(f"{'='*115}")
    header = (
        f"{'#':>2}  {'Topic':<42}  "
        f"{'Q1':^14}  {'Q2':^14}  {'Q3':^14}  {'Q4':^14}  {'Q5':^14}  Pass"
    )
    print(header)
    print("-" * 115)

    total_pass = total_diag = 0
    for idx, paper in enumerate(all_results, 1):
        qs = paper["questions"]
        cells = [q["verdict"] for q in qs]
        while len(cells) < 5:
            cells.append("-")
        pp = sum(1 for q in qs if q["verdict"] == "PASS")
        pt = sum(1 for q in qs if q["verdict"] in ("PASS", "FAIL"))
        total_pass += pp
        total_diag += pt
        row = (
            f"{idx:>2}  {paper['topic']:<42}  "
            + "  ".join(f"{c:^14}" for c in cells)
            + f"  {pp}/{pt}"
        )
        print(row)

    print("-" * 115)
    pct = 100 * total_pass // total_diag if total_diag else 0
    print(f"TOTAL: {total_pass}/{total_diag} passed ({pct}%)")
    print(f"{'='*115}\n")


if __name__ == "__main__":
    main()
