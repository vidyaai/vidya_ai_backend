#!/usr/bin/env python3
"""
End-to-End Query Response Test
Tests actual query responses with timing and accuracy checks.

Usage:
    source vidyaai_env/bin/activate
    cd /home/ubuntu/Pingu/vidya_ai_backend
    python test_query_response.py --video-id <video_id> --query "Your question here"
"""

import sys
import os
import time
import argparse
from typing import Dict, Any

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from utils.db import SessionLocal
from models import Video, VideoSummary, TranscriptChunk
from services.summary_service import SummaryService, QueryRouter
from utils.ml_models import OpenAIVisionClient
from controllers.config import logger


class QueryResponseTester:
    """Test actual query responses end-to-end"""

    def __init__(self, video_id: str):
        self.video_id = video_id
        self.db = SessionLocal()
        self.summary_service = SummaryService()
        self.query_router = QueryRouter()
        self.vision_client = OpenAIVisionClient()

    def __del__(self):
        if hasattr(self, 'db'):
            self.db.close()

    def test_query(self, query: str):
        """Test a single query end-to-end"""
        print("="*80)
        print(f"Query Response Test")
        print("="*80)
        print(f"Video ID: {self.video_id}")
        print(f"Query: {query}")
        print("="*80)

        try:
            # Get video and transcript
            video = self.db.query(Video).filter(Video.id == self.video_id).first()
            if not video:
                print(f"❌ Video {self.video_id} not found")
                return

            transcript = video.formatted_transcript or video.transcript_text
            if not transcript:
                print("❌ No transcript available")
                return

            print(f"\n📹 Video: {video.title}")
            print(f"   Transcript length: {len(transcript):,} characters")

            # Check RAG status
            summary_exists = self.summary_service.get_summary(self.db, self.video_id) is not None
            chunks_count = self.db.query(TranscriptChunk).filter(
                TranscriptChunk.video_id == self.video_id
            ).count()

            print(f"\n📊 RAG Status:")
            print(f"   Summary available: {'✅ Yes' if summary_exists else '❌ No'}")
            print(f"   Chunks available: {'✅ Yes' if chunks_count > 0 else '❌ No'} ({chunks_count} chunks)")

            # Classify query
            query_type = self.query_router.classify_query(query)
            print(f"\n🎯 Query Classification: {query_type}")

            # Build context based on available RAG data
            print(f"\n⏳ Building context...")
            context_start = time.time()

            if chunks_count > 0:
                # Use RAG retrieval
                retrieval_strategy = "RAG (Hybrid)"
                relevant_chunks = self.query_router.retrieve_relevant_chunks(
                    self.db, self.video_id, query, top_k=3, use_hybrid=True
                )

                if relevant_chunks:
                    context = "Relevant sections from video:\n\n"
                    for i, chunk in enumerate(relevant_chunks, 1):
                        context += f"[{chunk.get('start_time', '?')} - {chunk.get('end_time', '?')}]\n"
                        context += f"{chunk.get('text', '')}\n\n"
                else:
                    context = transcript[:5000]
                    retrieval_strategy = "Fallback (no chunks matched)"
            else:
                # Use fallback extraction
                retrieval_strategy = "Fallback (chunks not ready)"
                from utils.context_extraction import extract_relevant_context
                context = extract_relevant_context(transcript, query, max_tokens=3000)

            context_time = time.time() - context_start
            print(f"✅ Context built in {context_time*1000:.0f}ms")
            print(f"   Strategy: {retrieval_strategy}")
            print(f"   Context length: {len(context):,} characters")

            # Generate response
            print(f"\n⏳ Generating response...")
            response_start = time.time()

            response = self.vision_client.ask_text_only(
                prompt=query,
                context=context,
                conversation_history=[]
            )

            response_time = time.time() - response_start
            total_time = time.time() - context_start

            print(f"\n✅ Response generated in {response_time:.2f}s")
            print(f"   Total time: {total_time:.2f}s")

            # Display response
            print(f"\n" + "="*80)
            print(f"Response:")
            print("="*80)
            print(response)
            print("="*80)

            # Performance summary
            print(f"\n📊 Performance Metrics:")
            print(f"   Context building: {context_time*1000:.0f}ms")
            print(f"   LLM generation: {response_time*1000:.0f}ms")
            print(f"   Total time: {total_time*1000:.0f}ms")
            print(f"   Strategy: {retrieval_strategy}")

            # Check for timestamps in response
            import re
            timestamps = re.findall(r'\$?\d{1,2}:\d{2}(?::\d{2})?\$?', response)
            if timestamps:
                print(f"\n⏱️  Timestamps cited: {len(timestamps)}")
                print(f"   Examples: {', '.join(timestamps[:3])}")
            else:
                print(f"\n⚠️  No timestamps cited in response")

            print(f"\n✅ Test completed successfully!")

        except Exception as e:
            print(f"\n❌ Test failed: {e}")
            import traceback
            traceback.print_exc()


def main():
    parser = argparse.ArgumentParser(description="Test Query Response")
    parser.add_argument("--video-id", required=True, help="Video ID to test")
    parser.add_argument("--query", required=True, help="Question to ask")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")

    args = parser.parse_args()

    if args.verbose:
        logger.setLevel("DEBUG")

    tester = QueryResponseTester(args.video_id)
    tester.test_query(args.query)


if __name__ == "__main__":
    main()
