#!/usr/bin/env python
"""
Backfill MaterialChunk rows for CourseMaterials that were uploaded
before the per-material chat pipeline existed.

Usage (from the repo root with the venv active):
    cd src && python -m management_commands.backfill_material_chunks [options]

Options:
    --limit N          Only process first N materials (for testing)
    --material-id ID   Process only this CourseMaterial
    --force            Re-chunk materials that already have chunking_status set

By default the script targets PDF/DOCX CourseMaterials where
chunking_status IS NULL, and runs chunk_pdf_material_background
synchronously so chunks land before the script exits.
"""

import argparse
import sys

from controllers.background_tasks import (
    chunk_pdf_material_background,
    chunk_video_material_transcript_background,
)
from controllers.config import logger
from models import CourseMaterial
from utils.db import SessionLocal


def _is_chunkable_doc(material: CourseMaterial) -> bool:
    if material.material_type == "video":
        return False
    if not material.s3_key:
        return False
    mime = (material.mime_type or "").lower()
    fname = (material.file_name or "").lower()
    return (
        mime == "application/pdf"
        or fname.endswith(".pdf")
        or "wordprocessingml" in mime
        or fname.endswith(".docx")
    )


def _is_chunkable_video(material: CourseMaterial) -> bool:
    if material.material_type != "video":
        return False
    # Gallery-linked videos use TranscriptChunk via the existing video pipeline.
    if material.video_id:
        return False
    return bool((material.transcript_text or "").strip())


def backfill(limit: int = None, material_id: str = None, force: bool = False) -> None:
    db = SessionLocal()
    try:
        query = db.query(CourseMaterial)
        if material_id:
            query = query.filter(CourseMaterial.id == material_id)
        else:
            if not force:
                query = query.filter(CourseMaterial.chunking_status.is_(None))

        if limit:
            query = query.limit(limit)

        targets = query.all()
        doc_candidates = [m for m in targets if _is_chunkable_doc(m)]
        video_candidates = [m for m in targets if _is_chunkable_video(m)]
        logger.info(
            f"Backfill: {len(doc_candidates)} PDF/DOCX + "
            f"{len(video_candidates)} video materials "
            f"(considered {len(targets)})"
        )

        for i, material in enumerate(doc_candidates, start=1):
            logger.info(
                f"[doc {i}/{len(doc_candidates)}] Chunking material {material.id} "
                f"({material.file_name})"
            )
            try:
                chunk_pdf_material_background(material.id, material.s3_key)
            except Exception as e:
                logger.error(f"Failed material {material.id}: {e}")

        for i, material in enumerate(video_candidates, start=1):
            logger.info(
                f"[video {i}/{len(video_candidates)}] Chunking transcript for "
                f"material {material.id} ({material.title})"
            )
            try:
                chunk_video_material_transcript_background(material.id)
            except Exception as e:
                logger.error(f"Failed material {material.id}: {e}")
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--material-id", type=str, default=None)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    backfill(limit=args.limit, material_id=args.material_id, force=args.force)


if __name__ == "__main__":
    sys.exit(main())
