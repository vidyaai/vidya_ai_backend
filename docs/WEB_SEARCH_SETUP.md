# Web Search Integration - Setup Guide

## Overview

Vidya AI now includes **intelligent web search augmentation** that automatically enhances video-based answers with relevant information from the internet, similar to Claude or ChatGPT. The system:

✅ Automatically detects when web search would be helpful
✅ Performs targeted searches for concepts not fully covered in the video
✅ Synthesizes answers combining video content + web sources
✅ Provides proper citations for all sources

## How It Works

### 1. **Intelligent Decision Making**
When a student asks a question, the AI agent analyzes:
- Is the video content sufficient to answer?
- Would additional context from the web help?
- Are there related concepts not covered in the video?

### 2. **Automatic Search**
If web search is beneficial:
- Generates an optimized search query
- Searches the internet using your chosen provider
- Retrieves 3-5 most relevant results

### 3. **Smart Synthesis**
The AI then:
- Combines video content (primary source)
- Supplements with web findings
- Generates a natural, conversational answer
- Adds citations at the end

### Example Response Format

```
Great question! The video explains gradient descent at $08:45$ as a way to
minimize error by adjusting parameters step by step.

To add to what the video covers, gradient descent is widely used in training
neural networks because it's computationally efficient for large datasets [1].
The key is choosing the right learning rate - too high and you might miss the
minimum, too low and training takes forever [2].

Does that help clarify things? Want me to explain the math behind it at $15:30$?

**Sources:**
- Video: $08:45$, $15:30$
- [1] Deep Learning Fundamentals - https://...
- [2] Gradient Descent Explained - https://...
```

## Setup Instructions

### Step 1: Choose a Search Provider

We support three providers (choose ONE):

#### **Option 1: Tavily API** (RECOMMENDED)

**Why Tavily?**
- Purpose-built for AI/LLM applications
- Returns clean, citation-ready results
- Filters out low-quality content automatically
- Fast (< 1 second response time)

**Setup:**
1. Go to https://tavily.com
2. Sign up for an account
3. Get your API key from the dashboard
4. Add to `.env`:
   ```bash
   TAVILY_API_KEY=tvly-xxxxxxxxxxxxx
   ```

**Pricing:** ~$0.005 per search (~200 searches for $1)

---

#### **Option 2: Serper API** (Google Search - Budget Option)

**Why Serper?**
- 5x cheaper than Tavily
- Uses Google search results
- Good for high-volume use cases

**Setup:**
1. Go to https://serper.dev
2. Sign up and get API key
3. Add to `.env`:
   ```bash
   SERPER_API_KEY=xxxxxxxxxxxxx
   ```

**Pricing:** ~$0.001 per search (~1,000 searches for $1)

---

#### **Option 3: Google Custom Search API**

**Why Google CSE?**
- Free tier available (100 queries/day)
- Customizable search parameters
- Direct from Google

**Setup:**
1. Go to https://console.cloud.google.com/apis/credentials
2. Create API credentials
3. Set up Custom Search Engine at https://cse.google.com
4. Add to `.env`:
   ```bash
   GOOGLE_SEARCH_API_KEY=xxxxxxxxxxxxx
   GOOGLE_CSE_ID=xxxxxxxxxxxxx
   ```

**Pricing:** Free for 100/day, then $5 per 1,000 queries

---

### Step 2: Update Your .env File

Copy `.env.example` to `.env` if you haven't already:

```bash
cp .env.example .env
```

Then add your chosen API key:

```bash
# For Tavily (recommended)
TAVILY_API_KEY=your_api_key_here

# OR for Serper
# SERPER_API_KEY=your_api_key_here

# OR for Google
# GOOGLE_SEARCH_API_KEY=your_api_key_here
# GOOGLE_CSE_ID=your_cse_id_here
```

### Step 3: Configure the Provider (Optional)

The default provider is Tavily. To change it, update `src/utils/ml_models.py`:

```python
self.search_client = WebSearchClient(provider="tavily")  # or "serper" or "google"
```

### Step 4: Test the Integration

Start your backend server:

```bash
cd vidya_ai_backend
uvicorn src.main:app --reload
```

Ask a test question that would benefit from web search:

```bash
curl -X POST http://localhost:8000/api/query/video \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{
    "video_id": "test_video",
    "query": "What are the latest advances in gradient descent optimization?",
    "session_id": "test-session"
  }'
```

Check the response for:
- `"used_web_search": true` (indicates web search was used)
- `"web_sources": [...]` (list of source URLs)
- Citations in the response text

## Advanced Configuration

### Disable Web Search for Specific Users

In `src/routes/query.py`, you can conditionally enable/disable:

```python
# Check user's plan or preferences
enable_search = user.plan != "free"  # Only for paid users

web_result = vision_client.ask_with_web_augmentation(
    prompt=query,
    context=transcript_to_use,
    conversation_history=conversation_context,
    video_title=video_title,
    enable_search=enable_search,  # Control here
)
```

### Adjust Search Depth

For Tavily, you can use "advanced" search depth (more thorough but slower):

```python
search_results = self.search_client.search(
    query=search_query,
    max_results=5,  # Get more results
    search_depth="advanced"  # or "basic"
)
```

### Control Search Trigger Sensitivity

In `src/utils/web_search.py`, adjust the confidence threshold:

```python
# Lower threshold = more searches
# Higher threshold = fewer searches
if decision.get("should_search") and decision.get("confidence", 0) > 0.5:  # Default is 0.6
    # Perform search
```

## Monitoring & Debugging

### Check if Web Search is Working

Look for these log messages:

```
INFO: Web search decision: True (confidence: 0.85)
INFO: Performing web search for: gradient descent optimization techniques
INFO: Tavily search returned 3 results for: gradient descent optimization
INFO: Web-augmented answer generated with 3 sources
```

### Common Issues

#### "TAVILY_API_KEY not set, skipping web search"
**Solution:** Add `TAVILY_API_KEY` to your `.env` file

#### "Tavily search error: 401 Unauthorized"
**Solution:** Check that your API key is valid

#### Web search never triggers
**Solution:** The AI agent determined the video content was sufficient. This is working as intended - searches only trigger when needed.

#### Empty search results
**Solution:** Check your search query in logs. The query might be too specific or the provider might be rate-limited.

## Cost Estimation

Based on typical usage:

| Provider | Cost per Search | 1,000 searches | 10,000 searches |
|----------|----------------|----------------|-----------------|
| Tavily   | $0.005         | $5             | $50             |
| Serper   | $0.001         | $1             | $10             |
| Google CSE | $0.005 (after free tier) | $5 | $50 |

**Typical usage:** ~10-20% of queries trigger web search
- For 1,000 total queries → ~100-200 searches → $0.10-$1 (Tavily)

## API Key Security

**Important:** Never commit your `.env` file to version control!

Add to `.gitignore`:
```
.env
.env.local
*.key
```

For production, use environment variables via your hosting platform:
- Render: Settings → Environment
- Railway: Variables tab
- AWS: Parameter Store / Secrets Manager
- Heroku: Config Vars

## Feature Flags

To completely disable web search without removing code:

```python
# In routes/query.py
ENABLE_WEB_SEARCH = os.getenv("ENABLE_WEB_SEARCH", "false").lower() == "true"

# Then
enable_search=ENABLE_WEB_SEARCH
```

## FAQ

**Q: Does this use extra OpenAI credits?**
A: Yes, the synthesis step uses one additional OpenAI API call (GPT-4o) when web search is triggered.

**Q: How do I know if web search was used?**
A: Check the response field `"used_web_search": true/false`

**Q: Can I use multiple search providers?**
A: Yes, modify `WebSearchClient` to try providers in fallback order.

**Q: Does this work with image queries?**
A: Currently no. Web search only augments text-based queries. Image queries rely solely on the video frame + transcript.

**Q: How accurate are the citations?**
A: Citations are extracted from the actual search results. The AI synthesizes content but sources are real URLs from the search provider.

## Next Steps

- ✅ Choose and set up a search provider
- ✅ Test with sample queries
- ✅ Monitor usage and costs
- ✅ Consider implementing per-user or per-plan controls
- ✅ Add feedback collection to improve search triggers

## Support

For issues or questions:
- Check logs for error messages
- Verify API keys are correct
- Test provider API directly (use curl)
- Review the `src/utils/web_search.py` code

Happy searching! 🔍
