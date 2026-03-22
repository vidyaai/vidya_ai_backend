# Phase 2 Deployment Status

## ✅ Step 1: Database Migration - COMPLETE

```bash
# Migration executed successfully
python -m alembic upgrade head
# ✓ video_summaries table created
```

**Table Structure:**
- `id` (PK)
- `video_id` (FK to videos, unique index)
- `overview_summary` (text)
- `key_topics` (JSON array)
- `sections` (JSON array with timestamps)
- `total_duration_seconds` (float)
- `processing_status` (pending/processing/completed/failed)
- `error_message` (text)
- `created_at`, `updated_at`

---

## 🔄 Step 2: Generate Summaries for Existing Videos

### Option A: Test with Small Batch First (Recommended)

```bash
# Generate summaries for 5 videos to test
python -m src.management_commands.generate_summaries --limit 5
```

### Option B: Process All Videos

```bash
# Generate summaries for all existing videos
python -m src.management_commands.generate_summaries
```

### What Happens:
1. Script fetches videos from database
2. For each video:
   - Checks if summary already exists
   - Gets formatted transcript (preferred) or raw transcript
   - Generates hierarchical summary using GPT-4o-mini
   - Stores in `video_summaries` table
3. Takes ~2-5 seconds per video

### Expected Output:

```
[1/5] Processing video: abc123
  Title: Introduction to Neural Networks
  Using formatted transcript
  Generating summary...
  ✓ Summary generated in 3.2s
    - Overview: 95 chars
    - Sections: 7
    - Topics: 5

[2/5] Processing video: def456
  ✓ Summary already exists, skipping

...

========================================
Summary Generation Complete
========================================
Total videos: 5
✓ Successfully generated: 3
⊘ Skipped (already exist): 1
✗ Errors: 1
```

---

## 🧪 Step 3: Test Query Routing

### Test Broad Query (Should Use Summary)

```bash
curl -X POST http://localhost:8000/api/query/video \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{
    "video_id": "YOUR_VIDEO_ID",
    "query": "What is this video about?",
    "session_id": "test"
  }'
```

**Expected Response:**
```json
{
  "response": "This video covers neural networks...",
  "retrieval_strategy": "summary_only",  // ✓ Using summary!
  "classified_query_type": "broad",
  "web_sources": [],
  "used_web_search": false
}
```

### Test Specific Query (Should Use Full Transcript)

```bash
curl -X POST http://localhost:8000/api/query/video \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{
    "video_id": "YOUR_VIDEO_ID",
    "query": "How does backpropagation work?",
    "session_id": "test"
  }'
```

**Expected Response:**
```json
{
  "response": "Backpropagation works by...",
  "retrieval_strategy": "full_transcript",  // ✓ Using full context
  "classified_query_type": "specific",
  ...
}
```

---

## 📊 Step 4: Monitor & Verify

### Check Summary Generation Status

```sql
-- View summary statistics
SELECT
  processing_status,
  COUNT(*) as count,
  ROUND(AVG(jsonb_array_length(sections))) as avg_sections
FROM video_summaries
GROUP BY processing_status;

-- Expected output:
-- completed | 45 | 7
-- pending   | 5  | NULL
-- failed    | 2  | NULL
```

### Check Recent Summaries

```sql
-- View recent summaries with details
SELECT
  v.id,
  v.title,
  s.processing_status,
  LEFT(s.overview_summary, 100) as overview_preview,
  jsonb_array_length(s.sections) as num_sections,
  s.created_at
FROM videos v
LEFT JOIN video_summaries s ON v.id = s.video_id
ORDER BY s.created_at DESC
LIMIT 10;
```

### Check for Failures

```sql
-- See failed summaries with error messages
SELECT
  video_id,
  error_message,
  created_at
FROM video_summaries
WHERE processing_status = 'failed';
```

### Monitor Query Usage

```bash
# Check logs for query classification
grep "Query classified as" logs/app.log | tail -20

# Check logs for retrieval strategy
grep "Using summary-only context" logs/app.log | wc -l
grep "retrieval_strategy" logs/app.log | tail -20
```

---

## 🎯 Success Criteria

### ✅ All Systems Go When:

1. **Database**
   - [x] `video_summaries` table exists
   - [ ] At least 5 test summaries completed successfully
   - [ ] No critical errors in failed summaries

2. **Query Routing**
   - [ ] Broad queries return `retrieval_strategy: "summary_only"`
   - [ ] Specific queries return `retrieval_strategy: "full_transcript"`
   - [ ] Responses maintain quality

3. **Token Savings**
   - [ ] Broad queries use ~500 tokens (vs 5000+)
   - [ ] Specific queries use full context (~5000 tokens)
   - [ ] Average reduction ~55%

4. **Automatic Processing**
   - [ ] New videos trigger summary generation after formatting
   - [ ] Background generation doesn't block requests
   - [ ] Errors logged but don't crash the system

---

## 🚀 Production Deployment Checklist

### Before Full Rollout:

- [ ] Test with 10-20 videos across different types
- [ ] Verify summary quality manually (spot check 5 summaries)
- [ ] Check logs for any unexpected errors
- [ ] Monitor token usage reduction
- [ ] Verify timestamps are preserved correctly

### After Full Rollout:

- [ ] Monitor error rates
- [ ] Track token savings metrics
- [ ] Collect user feedback (optional)
- [ ] Fine-tune classification heuristics if needed

---

## 🔧 Troubleshooting

### Summary Generation Fails

**Symptom:** Many `processing_status = 'failed'` records

**Check:**
```sql
SELECT video_id, error_message
FROM video_summaries
WHERE processing_status = 'failed';
```

**Common Causes:**
- No transcript available for video
- API rate limits (OpenAI)
- Malformed transcript data

**Fix:**
```bash
# Retry failed videos
python -m src.management_commands.generate_summaries --video-id FAILED_VIDEO_ID --force
```

### Query Not Using Summary

**Symptom:** All queries show `retrieval_strategy: "full_transcript"`

**Check:**
1. Does summary exist? `SELECT * FROM video_summaries WHERE video_id = 'XXX'`
2. Is status completed? `processing_status = 'completed'`
3. Check logs for classification: `grep "Query classified" logs/app.log`

**Adjust Classification:**
Edit `src/services/summary_service.py` → `QueryRouter.classify_query()`

### New Videos Not Getting Summaries

**Check:** Is proactive generation enabled in `background_tasks.py` line 189-207?

**Verify:**
```bash
grep "Generating summary for video" logs/app.log
```

If not appearing, summary will be generated on first query (lazy mode).

---

## 📈 Next Steps

### Immediate (This Week)
1. ✅ Run migration
2. ⏳ Generate summaries for existing videos
3. ⏳ Test query routing with sample queries
4. ⏳ Monitor for 24-48 hours

### Short Term (Next Week)
- Analyze token savings metrics
- Fine-tune query classification if needed
- Generate summaries for any missed videos

### Long Term (Optional)
- **Phase 3:** Analytics & adaptive optimization
- **Phase 4:** Advanced retrieval (embeddings + hybrid search)
- Dashboard for monitoring token savings

---

## 📞 Support

**Documentation:**
- [QUICKSTART.md](QUICKSTART.md) - Quick setup guide
- [PHASE2_IMPLEMENTATION.md](PHASE2_IMPLEMENTATION.md) - Complete documentation
- [video_understanding.md](video_understanding.md) - Full 4-phase plan

**Logs:**
```bash
# Application logs
tail -f logs/app.log

# Summary generation logs
grep "summary" logs/app.log -i

# Query routing logs
grep "Query classified\|retrieval_strategy" logs/app.log
```

**Database Queries:**
See SQL queries above in "Monitor & Verify" section.
