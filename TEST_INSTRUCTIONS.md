# Query Rewriter Test Instructions

## Quick Test (No Frontend Needed!)

### Run the Test Script

```bash
cd /home/ubuntu/Pingu/vidya_ai_backend
python test_query_rewriter.py
```

This will test:
1. ✅ Numbered references ("question 7", "point 8", "the 2nd point")
2. ✅ Demonstrative references ("the above topic", "this", "that")
3. ✅ Implicit references ("elaborate more")
4. ✅ Self-contained queries (should NOT rewrite)
5. ✅ Empty conversation history handling
6. ✅ Different numbering styles (1., 2), 3:, etc.)

---

## What to Look For

### ✅ PASS - Working Correctly

Example output:
```
Test 1: Reference to numbered exam question
────────────────────────────────────────────────────────────────────────────────

User query: 'explain question 7 in detail'
  Has reference: True
  Resolved term: zero CF criterion
  Rewritten: 'explain the zero CF criterion in detail'
  ✅ PASS - Detected and rewrote reference
```

**Good signs:**
- `Has reference: True` for numbered references
- `Resolved term` shows the extracted topic name
- `Rewritten` query includes the actual topic (not "question 7")

### ❌ FAIL - Not Working

Example output:
```
User query: 'explain question 7 in detail'
  Has reference: False
  Resolved term: null
  Rewritten: 'explain question 7 in detail'
  ❌ FAIL - Did not detect reference
```

**Bad signs:**
- `Has reference: False` when there IS a reference
- `Rewritten` query unchanged (still says "question 7")
- Resolved term is null/None

---

## Test Cases Covered

### Test 1: Numbered Exam Questions
```
Conversation:
AI: "Here are 10 questions:
     7. What is the zero CF criterion..."
User: "explain question 7 in detail"

Expected: Rewrites to "explain the zero CF criterion in detail"
```

### Test 2: "The Above Topic"
```
Conversation:
User: "is wafer level chip packaging discussed?"
AI: "Yes, at 60:31 to 61:26"
User: "can you give me links about the above topic?"

Expected: Rewrites to "can you give me links about wafer level chip packaging?"
```

### Test 3: Self-Contained (No Rewrite)
```
Conversation:
User: "what is aerodynamics?"
AI: "Aerodynamics is the study..."
User: "what is drag?"

Expected: NO rewrite (already self-contained)
```

### Test 4: Implicit Reference
```
Conversation:
User: "what is the Bernoulli principle?"
AI: "The Bernoulli principle states..."
User: "can you elaborate more on this?"

Expected: Rewrites to "can you elaborate more on the Bernoulli principle?"
```

### Test 5: Empty History
```
User: "explain the concept"
(No conversation history)

Expected: Returns original query unchanged
```

### Test 6: Different Numbering Styles
```
Conversation:
AI: "Key concepts:
     1) Turboprops vs turbojets
     2: Propeller control systems
     3 - Flight instrumentation"
User: "tell me about topic 2"

Expected: Rewrites to "tell me about Propeller control systems"
```

---

## Debugging

### If All Tests Fail

**Check OpenAI API Key:**
```bash
echo $OPENAI_API_KEY
```

If empty, set it:
```bash
export OPENAI_API_KEY="your-key-here"
```

**Check Logs:**
The script will show debug logs from the query rewriter. Look for:
```
QUERY REWRITER DEBUG:
User query: 'explain question 7 in detail'
Conversation text sent to LLM:
--------------------------------------------------------------------------------
USER: give me 10 questions from this lecture
ASSISTANT: Here are 10 questions:
           7. What is the zero CF criterion...
--------------------------------------------------------------------------------
```

If conversation text is empty (`USER: \nUSER: \n`), the conversation history has wrong structure.

### If Some Tests Fail

**Check specific failure:**
- Test 1-2 fail: LLM not extracting numbered content properly
- Test 3 fails: LLM incorrectly detecting references
- Test 4 fails: LLM not detecting implicit references
- Test 5 fails: Empty history handling broken
- Test 6 fails: Different numbering styles not supported

---

## Next Steps After Testing

### ✅ If Tests Pass

Great! The query rewriter is working. Now test the full flow:

1. **Test relevance check:**
   - Create a conversation with numbered list
   - Ask "explain question 7 in detail"
   - Should NOT get "I noticed your question seems..." redirect
   - Should get actual answer about question 7

2. **Test from frontend:**
   - Chat with video
   - Ask for exam questions
   - Reference a numbered question
   - Verify correct answer

### ❌ If Tests Fail

1. **Check the logs** in terminal - see what LLM is receiving and returning
2. **Verify conversation history structure** - are messages populated?
3. **Check prompt** in `src/utils/ml_models.py` - is it clear enough?
4. **Test with simpler case** - modify test script to debug specific issue

---

## Example Full Test Run

```bash
$ python test_query_rewriter.py

🧪🧪🧪🧪🧪🧪🧪🧪🧪🧪🧪🧪🧪🧪🧪🧪🧪🧪🧪🧪
  QUERY REWRITER TEST SUITE
  Testing numbered reference detection and rewriting
🧪🧪🧪🧪🧪🧪🧪🧪🧪🧪🧪🧪🧪🧪🧪🧪🧪🧪🧪🧪

================================================================================
  QUERY REWRITER TEST SUITE
================================================================================

Initializing OpenAI Vision Client...
✅ Client initialized successfully

────────────────────────────────────────────────────────────────────────────────
Test 1: Reference to numbered exam question
────────────────────────────────────────────────────────────────────────────────

User query: 'explain question 7 in detail'
  Has reference: True
  Resolved term: zero CF criterion
  Rewritten: 'explain the zero CF criterion in detail'
  ✅ PASS - Detected and rewrote reference

[... more tests ...]

================================================================================
  TEST SUMMARY
================================================================================

✅ All tests completed!

If you see:
  - ✅ PASS: Query rewriter is working correctly
  - ❌ FAIL: Query rewriter needs debugging

Check the rewritten queries to verify they extracted the correct topics.
================================================================================
```

---

## Quick Reference Commands

```bash
# Run test
cd /home/ubuntu/Pingu/vidya_ai_backend
python test_query_rewriter.py

# Run with verbose logging
python test_query_rewriter.py 2>&1 | tee test_output.log

# Check just first test
python test_query_rewriter.py | head -40
```

---

**Created:** March 14, 2026
**Purpose:** Test query rewriter without frontend
**Time to run:** ~30-60 seconds (makes API calls to OpenAI)
