# Video Chat RAG Pipeline Test Suite

Comprehensive testing suite for the Video Chat RAG (Retrieval-Augmented Generation) pipeline implementation.

## 📁 Directory Structure

```
video_chat_test/
├── README.md              # This file
├── scripts/              # Test scripts
│   ├── test_video_rag_complete.py    # Complete end-to-end test
│   ├── test_rag_pipeline.py          # RAG pipeline unit tests
│   └── test_query_response.py        # Query response tests
├── data/                 # Test data files
│   ├── test_video.mp4               # Sample test video (2.3GB)
│   └── test_video_audio.mp3         # Extracted audio
└── results/              # Test results (JSON format)
    └── test_results_*.json          # Timestamped test results
```

---

## 🚀 Quick Start

### Prerequisites

```bash
cd /home/ubuntu/Pingu/vidya_ai_backend
source vidyaai_env/bin/activate
```

### Run Complete End-to-End Test

```bash
python video_chat_test/scripts/test_video_rag_complete.py \
  --video-path video_chat_test/data/test_video.mp4
```

### Run with Clean Start (Delete Existing Data)

```bash
python video_chat_test/scripts/test_video_rag_complete.py \
  --video-path video_chat_test/data/test_video.mp4 \
  --clean
```

---

## 📊 What Gets Tested

### Phase 2: Video Summarization
- ✅ Generate hierarchical summaries
- ✅ Extract key topics
- ✅ Create section summaries with timestamps

### Phase 3: Hybrid RAG Pipeline
- ✅ Semantic chunking with timestamps
- ✅ Embedding generation (OpenAI text-embedding-3-small)
- ✅ Hybrid retrieval (BM25 + Dense)
- ✅ Progressive enhancement (RAG + Fallback)

### Query Tests
Five test questions are asked:
1. "What is the name of the student and the counsellor?"
2. "What is this conversation about?"
3. "What are the main topics discussed?"
4. "Summarize the key points of this conversation"
5. "What concerns does the student have?"

---

## 📈 Metrics Collected

### 7 Key Processing Metrics
1. ⏱️ **Audio Extraction Time**
2. ⏱️ **Transcript Generation Time** (Deepgram)
3. ⏱️ **Transcript Formatting Time**
4. ⏱️ **Summary Generation Time** (Phase 2)
5. ⏱️ **Chunk Generation Time** (Phase 3)
6. ⏱️ **Query Response Times** (per question)
7. ⏱️ **Total Processing Time**

### Query Performance Metrics
- Response time (milliseconds)
- Strategy used (RAG vs Fallback)
- Context length (characters)
- Query classification type

---

## 📝 Test Scripts

### 1. test_video_rag_complete.py
**Complete end-to-end RAG pipeline test**

**Features:**
- Extracts audio from video
- Generates transcript with Deepgram
- Formats transcript with timestamps
- Generates video summary (Phase 2)
- Creates chunks + embeddings (Phase 3)
- Tests multiple queries
- Saves detailed results to JSON

**Usage:**
```bash
# Basic usage
python video_chat_test/scripts/test_video_rag_complete.py \
  --video-path video_chat_test/data/test_video.mp4

# With clean start
python video_chat_test/scripts/test_video_rag_complete.py \
  --video-path video_chat_test/data/test_video.mp4 \
  --clean
```

**Options:**
- `--video-path`: Path to video file (default: data/test_video.mp4)
- `--clean`: Delete existing test data before running

**Output:**
- Console: Detailed progress and results table
- File: `results/test_results_<timestamp>.json`

---

### 2. test_rag_pipeline.py
**RAG pipeline unit tests**

Tests individual components of the RAG pipeline.

**Usage:**
```bash
python video_chat_test/scripts/test_rag_pipeline.py --video-id <VIDEO_ID>
```

---

### 3. test_query_response.py
**Query response tests**

Tests query processing and response generation.

**Usage:**
```bash
python video_chat_test/scripts/test_query_response.py --video-id <VIDEO_ID>
```

---

## 📊 Sample Output

### Processing Times
```
⏱️  Processing Times:
--------------------------------------------------------------------------------
  audio_extraction              :   45.23s
  transcript_generation         :  132.45s
  transcript_formatting         :    8.12s
  summary_generation            :   67.89s
  chunk_generation              :   89.34s
--------------------------------------------------------------------------------
  TOTAL PROCESSING              :  343.03s
```

### Query Results Table
```
📊 Query Results:
--------------------------------------------------------------------------------
#   Strategy        Type       Time (ms)    Context
--------------------------------------------------------------------------------
1   RAG (Hybrid)    factual    1230         4523
2   RAG (Hybrid)    summary    1456         5012
3   RAG (Hybrid)    summary    1189         4789
4   RAG (Hybrid)    summary    1345         5123
5   RAG (Hybrid)    analytical 1512         4956
--------------------------------------------------------------------------------
AVG                            1346         4881
```

### Detailed Response Example
```
[Q1] What is the name of the student and the counsellor?
Strategy: RAG (Hybrid) | Type: factual | Time: 1230ms
--------------------------------------------------------------------------------
Based on the conversation, the student's name is Anirban Mondul and the
counsellor's name is mentioned as the person conducting the guidance session.
The conversation takes place around $05:23$ to $06:15$ in the video.
--------------------------------------------------------------------------------
```

---

## 🎯 Expected Performance

### Response Times (Phase 3 RAG Active)
- **Average**: 1.0-1.5 seconds
- **p95**: < 2.0 seconds
- **p99**: < 3.0 seconds

### Cost Per Query
- **Phase 3 RAG**: ~$0.0002 (1.5K tokens)
- **Fallback**: ~$0.001 (3K tokens)
- **Old (Full transcript)**: ~$0.006 (40K tokens)

### Accuracy
- **Factual queries**: 90-95% (with timestamps)
- **Summary queries**: 85-90%
- **Analytical queries**: 80-85%

---

## 🔍 Interpreting Results

### Good Performance Indicators
✅ Response time < 1.5s for RAG queries
✅ Context length 3K-6K characters
✅ Strategy shows "RAG (Hybrid)" for most queries
✅ Timestamps included in factual responses

### Issues to Investigate
❌ Response time > 3s
❌ Strategy shows "Fallback" (chunks not generated)
❌ No timestamps in responses
❌ Context length > 10K characters

---

## 🐛 Troubleshooting

### Issue: "duplicate key value violates unique constraint"
**Solution:** Use `--clean` flag to delete existing test data

```bash
python video_chat_test/scripts/test_video_rag_complete.py \
  --video-path video_chat_test/data/test_video.mp4 \
  --clean
```

### Issue: "DEEPGRAM_API_KEY not set"
**Solution:** Check `.env` file has Deepgram API key

```bash
grep DEEPGRAM_API_KEY .env
```

### Issue: "rank-bm25 not installed"
**Solution:** Install missing dependency

```bash
pip install rank-bm25
```

### Issue: Chunks not being used (always Fallback)
**Solution:** Check if chunks were generated successfully

```bash
# Check database for chunks
python -c "
from src.utils.db import SessionLocal
from src.models import TranscriptChunk
db = SessionLocal()
count = db.query(TranscriptChunk).filter(TranscriptChunk.video_id.like('test_%')).count()
print(f'Chunks found: {count}')
"
```

---

## 📦 Test Data

### test_video.mp4
- **Size**: 2.3GB
- **Duration**: ~3 hours (11,206 seconds)
- **Type**: Counselling session conversation
- **Transcript**: ~43,000 characters
- **Use Case**: Tests long-form content retrieval

---

## 🔄 Continuous Testing

### Add to CI/CD Pipeline

```yaml
# .github/workflows/test-rag.yml
name: Test RAG Pipeline

on: [push, pull_request]

jobs:
  test-rag:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Run RAG tests
        run: |
          cd vidya_ai_backend
          source vidyaai_env/bin/activate
          python video_chat_test/scripts/test_rag_pipeline.py
```

---

## 📚 Related Documentation

- **Implementation Plan**: `/docs/video_chat_upgrade.md`
- **RAG Testing Guide**: `/RAG_TESTING.md`
- **API Documentation**: `/docs/`

---

## 🤝 Contributing

When adding new tests:
1. Place scripts in `scripts/`
2. Use test data from `data/`
3. Save results to `results/`
4. Update this README

---

## 📝 Notes

- Test results are saved with timestamp in filename
- Old test results are preserved (not overwritten)
- Test video and audio are reused if they exist
- Database test entries use `test_*` prefix for easy cleanup

---

**Last Updated**: 2026-03-23
**Status**: ✅ Active
**Maintainer**: Development Team
