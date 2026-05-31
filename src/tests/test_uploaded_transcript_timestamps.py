#!/usr/bin/env python3
"""
Regression tests for uploaded ("gallery") video transcript timing.

Bug: uploaded videos were transcribed with the plain (timestamp-less) Deepgram
function, so the formatter fell back to convert_plain_text_to_transcript_data(),
which FABRICATES a uniform 15s-per-chunk timeline. A ~57 min lecture therefore
came out compressed into a fake ~34:45 of perfectly uniform 30s buckets, while
the course-material flow (which uses timed Deepgram segments) stayed correct.

These tests lock in that:
  1. create_formatted_transcript() emits REAL timestamps when given timed
     segments, and only fabricates when handed bare plain text.
  2. format_uploaded_transcript_background() formats from timed segments when
     a Deepgram transcript_json is available (instead of fabricating).

All network/DB/S3 side effects are stubbed, so these run offline.
"""

import os
import re
import sys
from pathlib import Path
from unittest.mock import MagicMock

# format_transcript builds an OpenAI() client at import time. We patch the actual
# API call in every test, so a dummy key just lets the module import in CI.
os.environ.setdefault("OPENAI_API_KEY", "sk-test-dummy")

# Add the src directory to the Python path (matches sibling tests)
sys.path.insert(0, str(Path(__file__).parent.parent))


def _max_end_seconds(formatted_lines) -> float:
    """Largest end-timestamp (in seconds) across all 'MM:SS - MM:SS' lines."""
    text = "".join(str(x) for x in formatted_lines)
    ends = []
    for m in re.finditer(r"(\d{2}):(\d{2})\s*-\s*(\d{2}):(\d{2})", text):
        ends.append(int(m.group(3)) * 60 + int(m.group(4)))
    return max(ends) if ends else -1.0


def _timed_transcript(real_duration_s: int = 3426):
    """A lecture whose speech genuinely spans ~57 min (utterance-level)."""
    segments = []
    t = 0.0
    # ~3s utterances across the whole real duration
    while t < real_duration_s:
        segments.append({"start": t, "dur": 3.0, "text": f"sentence at {int(t)} seconds."})
        t += 3.0
    segments[-1]["text"] = "Thank you for your attention."
    return {
        "title": "Lec 3 MIT Finite Element Procedures.mp4",
        "lengthInSeconds": real_duration_s,
        "transcription": segments,
    }


def test_timed_segments_yield_real_timestamps(monkeypatch):
    """Timed input -> final timestamp tracks the true duration (not compressed)."""
    from utils import format_transcript

    # Skip the OpenAI formatting call; we only care about timestamp math here.
    monkeypatch.setattr(
        format_transcript, "format_with_openai", lambda chunks, video_id=None: list(chunks)
    )

    timed = _timed_transcript(real_duration_s=3426)  # 57:06
    lines = format_transcript.create_formatted_transcript([timed])

    last_end = _max_end_seconds(lines)
    # Real timing: the final bucket must land near ~57 min, not the fabricated ~34:45.
    assert last_end >= 3000, f"expected real ~57min timing, got {last_end}s"


def test_plain_text_fabricates_compressed_timeline(monkeypatch):
    """Plain text -> fabricated uniform timeline unrelated to real duration.

    This documents the lossy fallback that caused the bug when it was the ONLY
    path uploaded videos ever took.
    """
    from utils import format_transcript

    monkeypatch.setattr(
        format_transcript, "format_with_openai", lambda chunks, video_id=None: list(chunks)
    )

    # 30 short sentences from a lecture that (in reality) ran ~57 min.
    plain = " ".join(f"This is sentence number {i}." for i in range(30))
    lines = format_transcript.create_formatted_transcript(
        {"plain_text": plain, "title": "Uploaded", "duration": 0}
    )

    last_end = _max_end_seconds(lines)
    # Fabricated 15s-per-3-sentences => ~150s total, nowhere near the real ~3426s.
    assert 0 <= last_end < 600, f"fabricated timeline should be small, got {last_end}s"


def test_uploaded_formatter_uses_timed_segments_when_available(monkeypatch):
    """The uploaded-video formatter must format from timed segments, not fabricate.

    Fails before the fix: format_uploaded_transcript_background() had no
    transcript_json parameter and always built a {"plain_text": ...} payload.
    """
    from controllers import background_tasks

    captured = {}

    def spy_create(transcript_data, output_file=None, video_id=None):
        captured["transcript_data"] = transcript_data
        return ["Title: x\n", "00:00 - 00:30\nhello\n\n"]

    # Stub every side effect: DB, S3, status writes, downstream processing.
    monkeypatch.setattr(background_tasks, "create_formatted_transcript", spy_create)
    monkeypatch.setattr(background_tasks, "s3_client", None)
    monkeypatch.setattr(background_tasks, "AWS_S3_BUCKET", None)
    monkeypatch.setattr(background_tasks, "update_formatting_status", lambda *a, **k: None)
    monkeypatch.setattr(
        background_tasks, "get_formatting_status", lambda *a, **k: {"total_chunks": 0}
    )

    fake_db = MagicMock()
    fake_db.query.return_value.filter.return_value.first.return_value = MagicMock()
    monkeypatch.setattr(background_tasks, "SessionLocal", lambda: fake_db)

    timed = _timed_transcript(real_duration_s=3426)

    background_tasks.format_uploaded_transcript_background(
        "vid-123",
        transcript_text="Thank you for your attention.",
        title="Lec 3.mp4",
        transcript_json=timed,
    )

    data = captured.get("transcript_data")
    # Must be the timed segments (a list whose [0] carries "transcription"),
    # NOT the fabricating {"plain_text": ...} payload.
    assert isinstance(data, list), f"expected timed list input, got {type(data)}"
    assert data[0].get("transcription"), "timed segments were not passed to the formatter"


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
