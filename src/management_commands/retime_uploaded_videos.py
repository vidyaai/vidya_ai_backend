#!/usr/bin/env python
"""
Repair formatted transcripts for uploaded ("gallery") videos that were
transcribed BEFORE the timed-transcription fix.

Background
----------
Uploaded videos used to be transcribed with the plain (timestamp-less) Deepgram
function, so the formatter fell back to fabricating a uniform 15s-per-chunk
timeline. A ~57 min lecture therefore came out as perfectly uniform 30s buckets
compressed into a fake ~34:45 (Video.formatted_transcript), with no
Video.transcript_json. The course-material flow was unaffected because it has
always used timed Deepgram segments.

This command re-runs Deepgram in timed (utterance-level) mode against the stored
S3 video, persists Video.transcript_json + transcript_text, and regenerates
Video.formatted_transcript with REAL timestamps using the same formatter the
upload pipeline now uses (format_uploaded_transcript_background).

Candidate selection (default): source_type == "uploaded", has an s3_key, and
transcript_json IS NULL (the tell-tale sign of the fabricated path). New uploads
always populate transcript_json now, so they are skipped automatically.

Usage (from src/ with the venv active and Deepgram/OpenAI/AWS configured):
    cd src && python -m management_commands.retime_uploaded_videos [options]

Options:
    --video-id ID   Only this Video (ignores the transcript_json filter)
    --limit N       Only process the first N candidates
    --all           Also re-do videos that already have transcript_json
    --reindex       Delete existing TranscriptChunk + VideoSummary first so the
                    RAG index/summary rebuild from the corrected transcript
                    (otherwise they are left as-is because they already exist)
    --dry-run       List candidates only; do NOT call Deepgram/OpenAI or write
"""

import argparse
import sys

from dotenv import load_dotenv
load_dotenv()

from controllers.background_tasks import format_uploaded_transcript_background
from controllers.config import logger
from controllers.storage import (
    s3_presign_url,
    transcribe_video_with_deepgram_url_timed,
)
from models import Video, TranscriptChunk, VideoSummary
from utils.db import SessionLocal


def _select_candidates(db, video_id=None, include_all=False, limit=None):
    query = db.query(Video).filter(Video.source_type == "uploaded")
    if video_id:
        query = query.filter(Video.id == video_id)
    else:
        query = query.filter(Video.s3_key.isnot(None))
        if not include_all:
            # The fabricated path never stored timed segments.
            query = query.filter(Video.transcript_json.is_(None))
    if limit:
        query = query.limit(limit)
    return query.all()


def _retime_one(video_id: str, title: str, s3_key: str, reindex: bool) -> bool:
    """Re-run timed Deepgram for one video and regenerate its transcript."""
    db = SessionLocal()
    try:
        presigned = s3_presign_url(s3_key, expires_in=60 * 60 * 12)
        timed = transcribe_video_with_deepgram_url_timed(
            presigned, video_title=(title or "Uploaded Video")
        )
        segments = (timed or {}).get("transcription") or []
        transcript_text = " ".join(s.get("text", "") for s in segments).strip()
        if not transcript_text:
            logger.warning(
                f"[{video_id}] timed transcription returned no segments; skipping"
            )
            return False

        video = db.query(Video).filter(Video.id == video_id).first()
        if not video:
            return False
        video.transcript_text = transcript_text
        video.transcript_json = timed
        db.commit()

        if reindex:
            # Drop index/summary built from the fabricated transcript so the
            # background job rebuilds them from the corrected one.
            db.query(TranscriptChunk).filter(
                TranscriptChunk.video_id == video_id
            ).delete(synchronize_session=False)
            db.query(VideoSummary).filter(
                VideoSummary.video_id == video_id
            ).delete(synchronize_session=False)
            db.commit()
    finally:
        db.close()

    # Regenerate formatted_transcript (+ optional chunks/summary) exactly like a
    # fresh upload, now that transcript_json carries real timing.
    format_uploaded_transcript_background(
        video_id,
        transcript_text,
        title or "Uploaded Video",
        transcript_json=timed,
    )
    return True


def retime(
    video_id: str = None,
    include_all: bool = False,
    limit: int = None,
    reindex: bool = False,
    dry_run: bool = False,
) -> None:
    db = SessionLocal()
    try:
        candidates = _select_candidates(
            db, video_id=video_id, include_all=include_all, limit=limit
        )
        # Snapshot the fields we need before closing the read session.
        rows = [(v.id, v.title, v.s3_key) for v in candidates if v.s3_key]
        skipped_no_s3 = len(candidates) - len(rows)
    finally:
        db.close()

    logger.info(
        f"retime_uploaded_videos: {len(rows)} candidate(s)"
        + (f", {skipped_no_s3} skipped (no s3_key)" if skipped_no_s3 else "")
        + (" [DRY RUN]" if dry_run else "")
    )

    if dry_run:
        for vid, title, _ in rows:
            logger.info(f"  would re-time {vid} ({title})")
        return

    ok = 0
    for i, (vid, title, s3_key) in enumerate(rows, start=1):
        logger.info(f"[{i}/{len(rows)}] re-timing {vid} ({title})")
        try:
            if _retime_one(vid, title, s3_key, reindex):
                ok += 1
        except Exception as e:
            logger.error(f"Failed to re-time {vid}: {e}")
    logger.info(f"retime_uploaded_videos: {ok}/{len(rows)} repaired")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video-id", type=str, default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--all", dest="include_all", action="store_true")
    parser.add_argument("--reindex", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    retime(
        video_id=args.video_id,
        include_all=args.include_all,
        limit=args.limit,
        reindex=args.reindex,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    sys.exit(main())
