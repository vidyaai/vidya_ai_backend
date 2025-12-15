# Video Download Progress Bar - Testing Guide

## Overview
A new download progress bar has been implemented to show real-time video download status when using the "Ask about current frame" feature.

## What Was Changed

### Backend Changes (`vidya_ai_backend`)

1. **`src/utils/youtube_utils.py`**
   - Modified `download_video()` to accept optional `video_id_param` parameter
   - Modified `download_file_to_path()` to track and update download progress in the database
   - Progress is updated every 5MB downloaded, showing:
     - Percentage complete
     - Bytes downloaded
     - Total file size
     - Status message

2. **`src/controllers/background_tasks.py`**
   - Updated `download_video_background()` to pass `video_id` to the download function
   - This enables progress tracking for background downloads

3. **Existing Endpoint** (`src/routes/youtube.py`)
   - The `/api/youtube/download-status/{video_id}` endpoint already returns download progress
   - No changes needed - it reads from the `download_status` field in the Video model

### Frontend Changes (`vidya_ai_frontend`)

1. **`src/components/Chat/ChatBoxComponent.jsx`**
   - Added `downloadProgress` state to track download status
   - Added `progressPollingRef` to manage polling interval
   - Implemented `pollDownloadProgress()` function that checks status every 2 seconds
   - Implemented `startDownloadProgressPolling()` to begin polling when download starts
   - Added cleanup on unmount to stop polling
   - Added beautiful progress bar UI showing:
     - Download icon with pulse animation
     - Progress message
     - Percentage with gradient progress bar
     - Downloaded MB / Total MB

## Testing Instructions

### 1. Start Both Servers (Already Running)
- ✅ Backend: http://localhost:8000
- ✅ Frontend: http://localhost:3000

### 2. Test with the Provided Video

1. **Open your browser** and go to: http://localhost:3000

2. **Login** to your account

3. **Navigate to the Chat page**

4. **Add the test video**: https://www.youtube.com/watch?v=0szKS7lMJvI
   - Click "Add Video" or use the video input field
   - Paste the URL and submit

5. **Wait for the video to appear** in your video list

6. **Click on the video** to open the chat interface

7. **Switch to "Ask about current frame" mode**
   - Select the radio button "Ask about current frame"

8. **Scrub the video** to any point (e.g., 1:30)

9. **Ask a frame-specific question** like:
   - "What is shown in this frame?"
   - "Describe what you see"
   - "What is happening at this moment?"

### 3. Expected Behavior

When you ask a frame-specific question:

**If video is still downloading:**
1. You'll see the AI response: "🎬 Something amazing is being loaded! The video is still downloading in the background..."
2. **NEW**: A progress bar will appear below the chat showing:
   - Animated download icon
   - "Downloading video... X%" message
   - Visual progress bar with gradient (indigo to purple)
   - Downloaded size in MB (e.g., "25.3 MB / 156.7 MB")
3. The progress bar updates every 2 seconds
4. Once download completes (100%), the progress bar disappears

**If video is already downloaded:**
- The AI will analyze the frame and respond normally
- No progress bar will appear

## Visual Design

The progress bar features:
- **Dark theme** matching your app (gray-900 background)
- **Animated download icon** with pulse effect
- **Gradient progress bar** (indigo-500 to purple-500)
- **Pulsing shimmer effect** on the progress bar
- **Smooth transitions** (300ms ease-out)
- **Real-time updates** every 2 seconds
- **MB counter** showing exact download progress

## How It Works

1. When you ask a frame-specific question, the backend checks if the video file exists locally
2. If not, it returns `is_downloading: true` in the response
3. Frontend detects this and starts polling `/api/youtube/download-status/{video_id}` every 2 seconds
4. Backend downloads video in chunks, updating database every 5MB with progress info
5. Frontend displays this progress in the UI
6. When download completes, polling stops and progress bar disappears

## Troubleshooting

### Progress bar doesn't appear
- Check browser console for errors
- Verify backend is running on port 8000
- Check network tab for `/api/youtube/download-status/` calls

### Progress stuck at 0%
- Check backend logs for download errors
- Verify RapidAPI key is valid
- Check if Content-Length header is available from download URL

### Progress doesn't update
- Check if polling is working (network tab should show requests every 2 seconds)
- Verify backend database updates are happening
- Check browser console for JavaScript errors

## API Endpoints

### Get Download Status
```
GET /api/youtube/download-status/{video_id}
Headers: Authorization: Bearer <token>

Response:
{
  "status": "downloading",
  "message": "Downloading video... 45%",
  "progress": 45,
  "downloaded_bytes": 47185920,
  "total_bytes": 104857600,
  "path": null
}
```

## Database Schema

The `videos` table has a `download_status` JSONB field that stores:
```json
{
  "status": "downloading" | "completed" | "failed",
  "message": "Downloading video... 45%",
  "progress": 45,
  "downloaded_bytes": 47185920,
  "total_bytes": 104857600,
  "path": "/path/to/video.mp4" (when completed)
}
```

## Notes

- Progress updates are throttled to every 5MB to avoid database overload
- Polling happens every 2 seconds for smooth UI updates
- Download progress is specific to each user's video
- If the browser is closed, polling stops but download continues in background
- When user reopens, progress bar will resume if video is still downloading

## Success Criteria

✅ Progress bar appears when asking about frames of downloading videos
✅ Progress percentage updates in real-time
✅ MB counter shows downloaded/total size
✅ Progress bar disappears when download completes
✅ Smooth animations and transitions
✅ No memory leaks (polling stops on unmount)
✅ Works with the test video: https://www.youtube.com/watch?v=0szKS7lMJvI
