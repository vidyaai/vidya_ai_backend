#!/usr/bin/env python3
"""
Complete Video RAG Pipeline Test
Processes a video file, generates transcript, builds RAG, and tests queries.

Usage:
    python test_video_rag_complete.py --video-path tests/test_video.mp4
"""

import sys
import os
import time
import json
import argparse
from datetime import datetime
from typing import List, Dict, Any
import subprocess

# Load environment variables FIRST (before importing any modules that use them)
from dotenv import load_dotenv

load_dotenv()

# Add src to path (go up two levels: scripts -> video_chat_test -> backend -> src)
backend_dir = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
sys.path.insert(0, os.path.join(backend_dir, "src"))

from utils.db import SessionLocal
from models import Video, VideoSummary, TranscriptChunk
from services.summary_service import SummaryService, QueryRouter
from services.chunking_embedding_service import TranscriptProcessor
from utils.ml_models import OpenAIVisionClient
from utils.context_extraction import extract_relevant_context
from controllers.config import logger
from controllers.db_helpers import update_transcript_cache, update_formatting_status
from utils.format_transcript import create_formatted_transcript

# Test questions
TEST_QUESTIONS = [
    "What is the name of the student and the counsellor?",
    "What is this conversation about?",
    "What are the main topics discussed?",
    "Summarize the key points of this conversation",
    "What concerns does the student have?",
]


class VideoRAGTester:
    """Complete end-to-end video RAG testing"""

    def __init__(self, video_path: str):
        self.video_path = video_path
        self.video_id = f"test_{int(time.time())}"
        self.db = SessionLocal()

        # Services
        self.summary_service = SummaryService()
        self.query_router = QueryRouter()
        self.transcript_processor = TranscriptProcessor()
        self.vision_client = OpenAIVisionClient()

        # Results
        self.results = {
            "video_path": video_path,
            "video_id": self.video_id,
            "processing_times": {},
            "test_results": [],
            "transcript": None,
            "formatted_transcript": None,
        }

    def __del__(self):
        if hasattr(self, "db"):
            self.db.close()

    def run_complete_test(self):
        """Run complete test pipeline"""
        print("=" * 80)
        print("COMPLETE VIDEO RAG PIPELINE TEST")
        print("=" * 80)
        print(f"Video: {self.video_path}")
        print(f"Test ID: {self.video_id}")
        print(f"Timestamp: {datetime.now().isoformat()}")
        print("=" * 80)

        try:
            # Check if video already exists with transcript
            existing_video = (
                self.db.query(Video).filter(Video.id == self.video_id).first()
            )
            if existing_video and existing_video.transcript_text:
                print(
                    "\n✨ Existing video found with transcript, skipping audio/transcript generation"
                )
                print(f"   Video ID: {self.video_id}")
                print(
                    f"   Transcript length: {len(existing_video.transcript_text)} characters"
                )

                transcript_data = existing_video.transcript_text
                formatted_transcript = (
                    existing_video.formatted_transcript
                    or existing_video.transcript_text
                )

                # Skip to step 4
                step_offset = 3
            else:
                # Step 1: Extract audio
                print("\n[1/7] Extracting audio...")
                audio_path = self.extract_audio()

                # Step 2: Generate transcript with Deepgram
                print("\n[2/7] Generating transcript with Deepgram...")
                transcript_data, transcript_json = self.generate_transcript(audio_path)

                # Step 3: Format transcript
                print("\n[3/7] Formatting transcript...")
                formatted_transcript = self.format_transcript(transcript_json)

                step_offset = 0

            # Continue with remaining steps (adjusted numbering)

            # Step 4: Generate summary (Phase 2)
            print(f"\n[{4-step_offset}/7] Generating video summary...")
            self.generate_summary(formatted_transcript)

            # Step 5: Generate chunks + embeddings (Phase 3)
            print(f"\n[{5-step_offset}/7] Generating chunks and embeddings...")
            self.generate_chunks(formatted_transcript)

            # Step 6: Test queries
            print(f"\n[{6-step_offset}/7] Testing queries...")
            self.test_queries(formatted_transcript)

            # Step 7: Display results
            print(f"\n[{7-step_offset}/7] Generating results...")
            self.display_results()

            # Save results to file
            self.save_results()

            print("\n" + "=" * 80)
            print("✅ Complete test finished successfully!")
            print("=" * 80)

        except Exception as e:
            print(f"\n❌ Test failed: {e}")
            import traceback

            traceback.print_exc()

    def extract_audio(self) -> str:
        """Extract audio from video using ffmpeg"""
        start_time = time.time()

        audio_path = self.video_path.rsplit(".", 1)[0] + "_audio.mp3"

        if os.path.exists(audio_path):
            print(f"   ℹ️  Audio already exists: {audio_path}")
        else:
            cmd = [
                "ffmpeg",
                "-i",
                self.video_path,
                "-vn",  # No video
                "-acodec",
                "libmp3lame",
                "-ar",
                "16000",  # 16kHz for Deepgram
                "-ac",
                "1",  # Mono
                "-y",  # Overwrite
                audio_path,
            ]

            print(f"   Running: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True)

            if result.returncode != 0:
                raise Exception(f"ffmpeg failed: {result.stderr}")

        elapsed = time.time() - start_time
        self.results["processing_times"]["audio_extraction"] = elapsed

        file_size = os.path.getsize(audio_path) / (1024 * 1024)  # MB
        print(f"   ✅ Audio extracted: {audio_path} ({file_size:.2f} MB)")
        print(f"   ⏱️  Time: {elapsed:.2f}s")

        return audio_path

    def generate_transcript(self, audio_path: str) -> tuple:
        """Generate transcript using Deepgram"""
        start_time = time.time()

        from deepgram import DeepgramClient, PrerecordedOptions
        from dotenv import load_dotenv

        load_dotenv()

        deepgram_key = os.getenv("DEEPGRAM_API_KEY")
        if not deepgram_key:
            raise Exception("DEEPGRAM_API_KEY not found in environment")

        print(f"   Transcribing with Deepgram...")

        try:
            deepgram = DeepgramClient(deepgram_key)

            with open(audio_path, "rb") as audio_file:
                buffer_data = audio_file.read()

            payload = {"buffer": buffer_data}

            options = PrerecordedOptions(
                model="nova-2",
                smart_format=True,
                punctuate=True,
                paragraphs=True,
                utterances=True,
            )

            response = deepgram.listen.rest.v("1").transcribe_file(payload, options)

            # Extract transcript
            result_json = response.to_dict()

            # Get plain text
            transcript_text = ""
            if result_json.get("results", {}).get("channels"):
                alternatives = result_json["results"]["channels"][0]["alternatives"]
                if alternatives:
                    transcript_text = alternatives[0]["transcript"]

            # Get timed segments
            transcript_json = []
            if result_json.get("results", {}).get("utterances"):
                for utterance in result_json["results"]["utterances"]:
                    transcript_json.append(
                        {
                            "text": utterance.get("transcript", ""),
                            "start": utterance.get("start", 0),
                            "end": utterance.get("end", 0),
                        }
                    )

            elapsed = time.time() - start_time
            self.results["processing_times"]["transcript_generation"] = elapsed
            self.results["transcript"] = transcript_text

            word_count = len(transcript_text.split())
            print(f"   ✅ Transcript generated")
            print(f"   ⏱️  Time: {elapsed:.2f}s")
            print(f"   📝 Words: {word_count}")
            print(f"   📊 Segments: {len(transcript_json)}")
            print(f"\n   Preview: {transcript_text[:200]}...")

            return transcript_text, transcript_json

        except Exception as e:
            print(f"   ❌ Deepgram transcription failed: {e}")
            raise

    def format_transcript(self, transcript_json: List[Dict]) -> str:
        """Format transcript with timestamps"""
        start_time = time.time()

        # Convert to format expected by create_formatted_transcript
        formatted_data = [
            {
                "title": "Test Video",
                "lengthInSeconds": transcript_json[-1]["end"] if transcript_json else 0,
                "transcription": transcript_json,
            }
        ]

        formatted_lines = create_formatted_transcript(
            formatted_data, video_id=self.video_id
        )
        formatted_text = "".join([str(line) for line in formatted_lines])

        elapsed = time.time() - start_time
        self.results["processing_times"]["transcript_formatting"] = elapsed
        self.results["formatted_transcript"] = formatted_text

        print(f"   ✅ Transcript formatted")
        print(f"   ⏱️  Time: {elapsed:.2f}s")
        print(f"   📄 Length: {len(formatted_text)} characters")

        return formatted_text

    def generate_summary(self, transcript: str):
        """Generate video summary (Phase 2)"""
        start_time = time.time()

        try:
            # Check if video already exists
            existing_video = (
                self.db.query(Video).filter(Video.id == self.video_id).first()
            )

            if existing_video:
                print(f"   ℹ️  Video already exists, reusing: {self.video_id}")

                # Update transcript if needed
                if not existing_video.transcript_text:
                    existing_video.transcript_text = transcript
                    existing_video.formatted_transcript = transcript
                    self.db.commit()
                    print(f"   ✅ Updated transcript for existing video")
            else:
                # Create new video record
                video = Video(
                    id=self.video_id,
                    source_type="uploaded",
                    title="Test Video",
                    transcript_text=transcript,
                    formatted_transcript=transcript,
                )
                self.db.add(video)
                self.db.commit()
                print(f"   ✅ Created new video record: {self.video_id}")

            # Check if summary already exists
            existing_summary = (
                self.db.query(VideoSummary)
                .filter(VideoSummary.video_id == self.video_id)
                .first()
            )

            if existing_summary:
                print(f"   ℹ️  Summary already exists, skipping generation")
                result = {
                    "overview": existing_summary.overview_summary,
                    "sections": existing_summary.sections or [],
                    "key_topics": existing_summary.key_topics or [],
                }
            else:
                # Generate summary
                result = self.summary_service.generate_video_summary(
                    self.db, self.video_id, transcript
                )
                print(f"   ✅ Summary generated")

            elapsed = time.time() - start_time
            self.results["processing_times"]["summary_generation"] = elapsed

            print(f"   ⏱️  Time: {elapsed:.2f}s")
            print(f"   📊 Sections: {len(result.get('sections', []))}")
            print(f"   🏷️  Topics: {len(result.get('key_topics', []))}")
            if result.get("overview"):
                print(f"\n   Overview: {result['overview'][:150]}...")

        except Exception as e:
            print(f"   ❌ Summary generation failed: {e}")
            raise

    def generate_chunks(self, transcript: str):
        """Generate chunks and embeddings (Phase 3)"""
        start_time = time.time()

        try:
            # Check if chunks already exist
            existing_chunks = (
                self.db.query(TranscriptChunk)
                .filter(TranscriptChunk.video_id == self.video_id)
                .count()
            )

            if existing_chunks > 0:
                print(
                    f"   ℹ️  Chunks already exist ({existing_chunks}), skipping generation"
                )
                num_chunks = existing_chunks
            else:
                # Generate chunks
                num_chunks = self.transcript_processor.process_transcript(
                    self.db, self.video_id, transcript
                )
                print(f"   ✅ Chunks generated")

            elapsed = time.time() - start_time
            self.results["processing_times"]["chunk_generation"] = elapsed

            print(f"   ⏱️  Time: {elapsed:.2f}s")
            print(f"   📦 Chunks: {num_chunks}")
            if num_chunks > 0 and elapsed > 0:
                print(f"   ⚡ Avg time/chunk: {elapsed/num_chunks:.3f}s")

        except Exception as e:
            print(f"   ❌ Chunk generation failed: {e}")
            raise

    def test_queries(self, transcript: str):
        """Test multiple queries and record results"""
        print(f"\n   Testing {len(TEST_QUESTIONS)} questions...")
        print("   " + "-" * 76)

        for i, question in enumerate(TEST_QUESTIONS, 1):
            print(f"\n   [{i}/{len(TEST_QUESTIONS)}] {question}")

            result = self.test_single_query(question, transcript)
            self.results["test_results"].append(result)

            # Display result
            print(f"      Strategy: {result['strategy']}")
            print(f"      Response time: {result['response_time']*1000:.0f}ms")
            print(f"      Context length: {result['context_length']} chars")
            print(f"      Response: {result['response'][:100]}...")

    def test_single_query(self, question: str, transcript: str) -> Dict:
        """Test a single query"""
        start_time = time.time()

        # Classify query
        query_type = self.query_router.classify_query(question)

        # Check if chunks available
        chunks_available = (
            self.db.query(TranscriptChunk)
            .filter(TranscriptChunk.video_id == self.video_id)
            .count()
            > 0
        )

        # Build context
        if chunks_available:
            # Use RAG
            relevant_chunks = self.query_router.retrieve_relevant_chunks(
                self.db, self.video_id, question, top_k=3, use_hybrid=True
            )

            if relevant_chunks:
                context = "Relevant sections:\n\n"
                for chunk in relevant_chunks:
                    context += f"[{chunk.get('start_time', '?')} - {chunk.get('end_time', '?')}]\n"
                    context += f"{chunk.get('text', '')}\n\n"
                strategy = "RAG (Hybrid)"
            else:
                context = extract_relevant_context(
                    transcript, question, max_tokens=3000
                )
                strategy = "Fallback"
        else:
            # Use fallback
            context = extract_relevant_context(transcript, question, max_tokens=3000)
            strategy = "Fallback"

        # Generate response
        response = self.vision_client.ask_text_only(
            prompt=question, context=context, conversation_history=[]
        )

        elapsed = time.time() - start_time

        return {
            "question": question,
            "query_type": query_type,
            "strategy": strategy,
            "context_length": len(context),
            "response_time": elapsed,
            "response": response,
        }

    def display_results(self):
        """Display comprehensive results table"""
        print("\n" + "=" * 80)
        print("RESULTS SUMMARY")
        print("=" * 80)

        # Processing times
        print("\n⏱️  Processing Times:")
        print("-" * 80)
        total_processing = 0
        for step, elapsed in self.results["processing_times"].items():
            print(f"  {step:30s}: {elapsed:6.2f}s")
            total_processing += elapsed
        print("-" * 80)
        print(f"  {'TOTAL PROCESSING':30s}: {total_processing:6.2f}s")

        # Query results table
        print("\n📊 Query Results:")
        print("-" * 80)
        print(
            f"{'#':<3} {'Strategy':<15} {'Type':<10} {'Time (ms)':<12} {'Context':<10}"
        )
        print("-" * 80)

        for i, result in enumerate(self.results["test_results"], 1):
            print(
                f"{i:<3} {result['strategy']:<15} {result['query_type']:<10} "
                f"{result['response_time']*1000:<12.0f} {result['context_length']:<10}"
            )

        print("-" * 80)

        # Calculate averages
        avg_response_time = sum(
            r["response_time"] for r in self.results["test_results"]
        ) / len(self.results["test_results"])
        avg_context_length = sum(
            r["context_length"] for r in self.results["test_results"]
        ) / len(self.results["test_results"])

        print(
            f"{'AVG':<3} {'':<15} {'':<10} {avg_response_time*1000:<12.0f} {avg_context_length:<10.0f}"
        )
        print()

        # Detailed responses
        print("\n📝 Detailed Responses:")
        print("=" * 80)

        for i, result in enumerate(self.results["test_results"], 1):
            print(f"\n[Q{i}] {result['question']}")
            print(
                f"Strategy: {result['strategy']} | Type: {result['query_type']} | Time: {result['response_time']*1000:.0f}ms"
            )
            print("-" * 80)
            print(result["response"])
            print("-" * 80)

    def save_results(self):
        """Save results to JSON file"""
        results_dir = os.path.join(backend_dir, "video_chat_test", "results")
        os.makedirs(results_dir, exist_ok=True)
        output_file = os.path.join(results_dir, f"test_results_{self.video_id}.json")

        # Convert to serializable format
        output_data = {
            "video_path": self.results["video_path"],
            "video_id": self.results["video_id"],
            "timestamp": datetime.now().isoformat(),
            "processing_times": self.results["processing_times"],
            "transcript_preview": self.results["transcript"][:500]
            if self.results["transcript"]
            else None,
            "test_results": self.results["test_results"],
            "summary": {
                "total_processing_time": sum(self.results["processing_times"].values()),
                "avg_response_time": sum(
                    r["response_time"] for r in self.results["test_results"]
                )
                / len(self.results["test_results"]),
                "total_questions": len(self.results["test_results"]),
            },
        }

        with open(output_file, "w") as f:
            json.dump(output_data, f, indent=2)

        # Show relative path for cleaner output
        rel_path = os.path.relpath(output_file, backend_dir)
        print(f"\n💾 Results saved to: {rel_path}")


def main():
    parser = argparse.ArgumentParser(description="Complete Video RAG Pipeline Test")
    # Default path is relative to backend directory
    default_video = os.path.join(
        backend_dir, "video_chat_test", "data", "test_video.mp4"
    )
    parser.add_argument(
        "--video-path", default=default_video, help="Path to video file"
    )
    parser.add_argument(
        "--clean", action="store_true", help="Delete existing test data before running"
    )

    args = parser.parse_args()

    if not os.path.exists(args.video_path):
        print(f"❌ Video file not found: {args.video_path}")
        sys.exit(1)

    # Clean up old test data if requested
    if args.clean:
        print("\n🧹 Cleaning up old test data...")
        db = SessionLocal()
        try:
            # Find all test videos
            test_videos = db.query(Video).filter(Video.id.like("test_%")).all()
            for video in test_videos:
                print(f"   Deleting video: {video.id}")
                db.delete(video)
            db.commit()
            print(f"   ✅ Deleted {len(test_videos)} test video(s)")
        finally:
            db.close()

    tester = VideoRAGTester(args.video_path)
    tester.run_complete_test()


if __name__ == "__main__":
    main()
