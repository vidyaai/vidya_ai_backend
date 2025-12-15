# Video Cache Implementation

## Overview
Implemented session caching for S3-hosted videos to prevent downloading the entire video on every frame query.

## Problem Solved
- **Before**: Video downloaded from S3 on EVERY frame query (wasteful bandwidth, slow UX)
- **After**: Video downloaded ONCE and cached for 30 minutes of inactivity

## Architecture

### Cache Structure
```python
VIDEO_CACHE = {
    'video_id': {
        'path': '/tmp/tmpXXXXXX.mp4',      # Temp file path
        'last_access': datetime.now()       # Last time frame was extracted
    }
}
```

### Cleanup Mechanism
- **Type**: Background daemon thread (not cron job)
- **Frequency**: Checks every 5 minutes
- **TTL**: 30 minutes of inactivity
- **Thread-safe**: Uses `CACHE_LOCK` for concurrent access

### Flow Diagram

```
┌─────────────────────────────────────────────────────────────┐
│ User asks question about frame                              │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      ▼
              ┌───────────────┐
              │ Check Cache   │
              └───────┬───────┘
                      │
         ┌────────────┴────────────┐
         │                         │
    ✅ Found                   ❌ Not Found
         │                         │
         ▼                         ▼
  ┌──────────────┐        ┌──────────────────┐
  │ Use Cached   │        │ Download from S3 │
  │ Update Time  │        │ Add to Cache     │
  └──────────────┘        └──────────────────┘
         │                         │
         └────────────┬────────────┘
                      │
                      ▼
              ┌───────────────┐
              │ Extract Frame │
              └───────────────┘

Background Thread (Every 5 min):
  ┌──────────────────────────────┐
  │ Check all cached videos      │
  │ If age > 30 min:             │
  │   - Delete file from disk    │
  │   - Remove from cache dict   │
  └──────────────────────────────┘
```

## Performance Impact

### Before (No Cache):
- Query 1: Download 2GB + Extract frame = **~30 seconds**
- Query 2: Download 2GB + Extract frame = **~30 seconds**
- Query 3: Download 2GB + Extract frame = **~30 seconds**
- **Total**: 90 seconds + 6GB downloaded

### After (With Cache):
- Query 1: Download 2GB + Extract frame = **~30 seconds** (cache miss)
- Query 2: Extract frame from cache = **<1 second** (cache hit)
- Query 3: Extract frame from cache = **<1 second** (cache hit)
- **Total**: 32 seconds + 2GB downloaded

### Savings:
- **58 seconds faster** (64% reduction)
- **4GB less bandwidth** (67% reduction)
- **Lower S3 egress costs**

## Implementation Details

### Key Functions

1. **`cleanup_expired_cache()`**
   - Iterates through all cached videos
   - Calculates age since last access
   - Removes files older than 30 minutes

2. **`start_cache_cleanup_thread()`**
   - Creates daemon thread
   - Runs cleanup loop every 5 minutes
   - Started on app startup

3. **`grab_youtube_frame()` (Modified)**
   - Checks cache before downloading
   - Extracts video_id from S3 URL
   - Updates `last_access` on cache hits
   - Adds new downloads to cache

### Startup Integration
```python
@app.on_event("startup")
async def startup_event():
    start_cache_cleanup_thread()
```

## Configuration

```python
CACHE_TTL_MINUTES = 30        # Delete after 30 min inactivity
CLEANUP_INTERVAL = 300        # Check every 5 minutes (in seconds)
```

## Thread Safety

- Uses `threading.Lock()` (`CACHE_LOCK`) to prevent race conditions
- Lock acquired when:
  - Checking cache
  - Adding to cache
  - Removing from cache
  - Cleanup operations

## Disk Space Management

- Videos stored in system temp directory (`/tmp` on Unix)
- Files auto-deleted after 30 min inactivity
- Multiple videos can be cached simultaneously
- Example: 10 concurrent videos × 2GB = ~20GB max disk usage

## Logging

Cache operations are logged with emojis for easy monitoring:
- 📹 Video ID extraction
- ✨ Cache hit (reusing cached file)
- 📥 Cache miss (downloading)
- 💾 Video added to cache
- 🗑️ Cache cleanup (file deleted)

## Testing Recommendations

1. **Cache Hit**: Ask multiple questions about same video → Should see "Using CACHED video"
2. **TTL Expiry**: Wait 30+ minutes without queries → File should be deleted
3. **Multiple Videos**: Upload different videos → Each cached separately
4. **Cleanup Thread**: Check logs every 5 minutes → Should see cleanup checks

## Future Optimizations (Not Implemented)

- ❌ Byte-range downloads (download only needed frames) - OpenCV doesn't support streaming from HTTP
- ✅ Full video caching (current implementation)

## Related Files

- `src/utils/youtube_utils.py` - Cache logic
- `src/main.py` - Startup integration
- `src/controllers/db_helpers.py` - Video path resolution

## Date Implemented
November 19, 2025
