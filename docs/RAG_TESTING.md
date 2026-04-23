# RAG Pipeline Testing Guide

## Overview
This guide explains how to test the enhanced RAG (Retrieval-Augmented Generation) pipeline with Phase 2 (Summarization) and Phase 3 (Hybrid Retrieval) features.

## Prerequisites

1. **Activate virtual environment:**
   ```bash
   cd /home/ubuntu/Pingu/vidya_ai_backend
   source vidyaai_env/bin/activate
   ```

2. **Install dependencies (if not already installed):**
   ```bash
   pip install -r requirements.txt
   ```

3. **Ensure database is running** and environment variables are set in `.env`

## Test Scripts

### 1. RAG Pipeline Test (`test_rag_pipeline.py`)
Comprehensive test of all RAG components:
- Phase 2: Video summarization
- Phase 3: Chunking and embeddings
- Hybrid retrieval (BM25 + Semantic)
- Query classification
- Fallback mechanisms

**Usage:**
```bash
python test_rag_pipeline.py --video-id <YOUR_VIDEO_ID>
```

**With verbose logging:**
```bash
python test_rag_pipeline.py --video-id <YOUR_VIDEO_ID> --verbose
```

**What it tests:**
- ✅ Summary generation (hierarchical, multi-level)
- ✅ Chunk generation with timestamps
- ✅ Embedding generation
- ✅ Hybrid retrieval (BM25 + cosine similarity)
- ✅ Query classification (broad/specific/hybrid)
- ✅ Fallback extraction when RAG not ready
- ✅ Performance metrics and timing

### 2. Query Response Test (`test_query_response.py`)
End-to-end test of actual query responses:

**Usage:**
```bash
python test_query_response.py \
    --video-id <YOUR_VIDEO_ID> \
    --query "Your question here"
```

**Example:**
```bash
python test_query_response.py \
    --video-id abc123 \
    --query "What are the main concepts explained in this video?"
```

**What it tests:**
- ✅ Full query flow from question to answer
- ✅ Context building (RAG or fallback)
- ✅ LLM response generation
- ✅ Timestamp preservation
- ✅ Response time measurement
- ✅ Strategy selection (RAG vs fallback)

## Testing Workflow

### Step 1: Test with a Fresh Video (No RAG Data Yet)
```bash
# 1. Add a new video through the API or UI
# 2. Immediately test query response (should use fallback)
python test_query_response.py \
    --video-id NEW_VIDEO_ID \
    --query "Summarize this video"
```

**Expected behavior:**
- ❌ No chunks available yet
- ❌ No summary available yet
- ✅ Uses fallback extraction (smart keyword-based)
- ⏱️  Response time: ~2-3 seconds
- ✅ Still gets a good answer!

### Step 2: Wait for Background Processing
Background jobs automatically triggered when video is added:
- Summary generation: ~2-3 minutes
- Chunk + embedding generation: ~3-5 minutes

**Check progress:**
```bash
python test_rag_pipeline.py --video-id YOUR_VIDEO_ID
```

### Step 3: Test with RAG Enabled
Once background jobs complete, test again:
```bash
python test_query_response.py \
    --video-id YOUR_VIDEO_ID \
    --query "What are the main topics?"
```

**Expected behavior:**
- ✅ Chunks available
- ✅ Summary available
- ✅ Uses hybrid retrieval (BM25 + semantic)
- ⏱️  Response time: ~1-1.5 seconds (70% faster!)
- ✅ More accurate answers
- ✅ Timestamps preserved

## Performance Targets

### Before RAG (Naive Approach):
- **3-hour video**: 40K+ tokens → 5s response → $0.006/query
- **Accuracy**: 50-60% (lost in the middle problem)
- **Wait time**: 0s (but poor performance)

### After RAG (Enhanced):
- **3-hour video**: 1.5K tokens → 1.5s response → $0.0002/query
- **Accuracy**: 80-90% (hybrid retrieval)
- **Wait time**: 0s (progressive enhancement!)

### Key Improvements:
- ⚡ **70% faster responses** (5s → 1.5s)
- 💰 **97% cost reduction** ($0.006 → $0.0002)
- 🎯 **+30-50% accuracy improvement**
- ⏱️  **Zero user wait time** (background processing)

## Testing Different Query Types

### Broad Queries (Uses Summary):
```bash
python test_query_response.py --video-id VIDEO_ID --query "What is this video about?"
python test_query_response.py --video-id VIDEO_ID --query "Summarize the main topics"
```

**Expected:** Uses summary-only context (~1K tokens)

### Specific Queries (Uses Semantic Chunks):
```bash
python test_query_response.py --video-id VIDEO_ID --query "How does Karnaugh map simplification work?"
python test_query_response.py --video-id VIDEO_ID --query "Explain the difference between NAND and NOR gates"
```

**Expected:** Uses top-5 semantic chunks (~2K tokens)

### Hybrid Queries (Uses Summary + Chunks):
```bash
python test_query_response.py --video-id VIDEO_ID --query "What does the professor say about logic gates?"
```

**Expected:** Uses summary overview + top-3 relevant chunks (~2.5K tokens)

## Debugging

### Enable Verbose Logging:
```bash
python test_rag_pipeline.py --video-id VIDEO_ID --verbose
```

### Check Database Directly:
```bash
cd src
python3 << EOF
from utils.db import SessionLocal
from models import VideoSummary, TranscriptChunk

db = SessionLocal()

# Check summary
summary = db.query(VideoSummary).filter(VideoSummary.video_id == 'YOUR_VIDEO_ID').first()
print(f"Summary status: {summary.processing_status if summary else 'Not found'}")

# Check chunks
chunk_count = db.query(TranscriptChunk).filter(TranscriptChunk.video_id == 'YOUR_VIDEO_ID').count()
print(f"Chunks: {chunk_count}")

db.close()
EOF
```

### Manual Trigger (If Background Job Failed):
```bash
cd src
python3 << EOF
from utils.db import SessionLocal
from models import Video
from controllers.background_tasks import generate_summary_background

db = SessionLocal()
video = db.query(Video).filter(Video.id == 'YOUR_VIDEO_ID').first()
transcript = video.formatted_transcript or video.transcript_text

# Manually trigger
generate_summary_background(video.id, transcript)
print("Done!")
db.close()
EOF
```

## Expected Test Output

### Successful RAG Test:
```
================================================================================
RAG Pipeline Test for Video: abc123
================================================================================

✅ Video found: Digital Logic Lecture 5
   Source: youtube
   Transcript available: True
   Transcript length: 45,230 characters

================================================================================
Phase 2: Video Summarization
================================================================================
✅ Summary already exists
   Overview length: 342 characters
   Number of sections: 8
   Key topics: 6

   Overview: This lecture covers digital logic design principles...

   Topics: Boolean Algebra, Karnaugh Maps, Logic Minimization, ...

================================================================================
Phase 3: Chunking & Embeddings
================================================================================
✅ Chunks already exist: 42 chunks
   Sample chunk:
   - Text: In this section we'll discuss Karnaugh maps...
   - Timestamp: 05:23 - 07:15
   - Embedding dims: 1536

================================================================================
Phase 3: Hybrid Retrieval (BM25 + Semantic)
================================================================================

Testing hybrid retrieval...

  Query: 'main concepts'
  ├─ Semantic search: 45.2ms
  ├─ Hybrid search: 38.7ms
  ├─ Semantic results: 3
  └─ Hybrid results: 3
     Top result: 02:15 - 03:45
     Text: The main concepts we'll cover today include Boolean algebra...
     RRF score: 0.8234

...

✅ All tests completed successfully!
```

## Troubleshooting

### "No chunks available"
- **Cause**: Background job hasn't completed yet or failed
- **Solution**: Wait 3-5 minutes or manually trigger (see Debugging section)

### "Summary generation failed"
- **Cause**: OpenAI API key missing or rate limit
- **Solution**: Check `.env` file for `OPENAI_API_KEY`

### "Database connection failed"
- **Cause**: PostgreSQL not running or wrong credentials
- **Solution**: Check `.env` file for `DATABASE_URL`

### "BM25 not available" warning
- **Cause**: `rank-bm25` package not installed
- **Solution**: `pip install rank-bm25>=0.2.2`
- **Impact**: Falls back to semantic-only search (still works, just slightly less accurate)

## Next Steps

After successful testing:
1. Monitor performance in production
2. Collect user feedback on answer quality
3. Adjust retrieval parameters (top_k, alpha) if needed
4. Consider Phase 4 optimizations (see video_chat_upgrade.md)

## Support

For issues or questions:
1. Check logs in `src/controllers/config.py` logger output
2. Review implementation in `docs/video_chat_upgrade.md`
3. Test with different videos to isolate issues
