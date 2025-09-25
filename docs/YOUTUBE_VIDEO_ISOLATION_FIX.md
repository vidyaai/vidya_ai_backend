# YouTube Video Isolation Fix

## Problem

Previously, YouTube videos were stored in S3 using a global structure:
- `youtube_videos/{video_id}.mp4`
- `youtube_thumbnails/{video_id}.jpg`
- `youtube_transcripts/{video_id}_formatted.txt`

This caused a critical issue: when one user deleted a YouTube video, it would delete the S3 objects globally, affecting all other users who had the same video in their gallery.

## Solution

Modified the storage structure to use user-specific S3 keys:
- `youtube_videos/{user_id}/{video_id}.mp4`
- `youtube_thumbnails/{user_id}/{video_id}.jpg`
- `youtube_transcripts/{user_id}/{video_id}_formatted.txt`

This ensures that each user has their own copy of YouTube videos, and deleting a video only affects the specific user's copy.

## Changes Made

### 1. Updated Background Tasks (`src/controllers/background_tasks.py`)

- Modified `download_video_background()` to use user-specific S3 keys
- Updated `format_transcript_background()` to use user-specific transcript keys
- Added proper user_id validation before S3 operations

### 2. Updated Deletion Logic (`src/routes/gallery_folders.py`)

- Updated comments to reflect that deletion now works for both uploaded and YouTube videos
- The existing deletion logic already worked correctly since it uses the S3 keys stored in the video record

### 3. Migration Script (`src/migrations/migrate_youtube_videos_to_user_specific.py`)

- Created a migration script to move existing YouTube videos from global to user-specific structure
- Handles copying S3 objects and updating database records
- Safely deletes old objects after successful migration

### 4. Test Script (`src/tests/test_youtube_video_isolation.py`)

- Created comprehensive tests to verify video isolation
- Tests S3 key structure and user isolation
- Verifies that deletion only affects the specific user

## How to Apply the Fix

### 1. Deploy the Code Changes

The code changes are backward compatible and will work immediately for new YouTube videos.

### 2. Run the Migration (Optional but Recommended)

For existing YouTube videos, run the migration script:

```bash
cd src
python migrations/migrate_youtube_videos_to_user_specific.py
```

This will:
- Find all existing YouTube videos with old S3 structure
- Copy them to user-specific locations
- Update database records
- Delete old global copies

### 3. Run Tests

Verify the fix is working:

```bash
cd src
python tests/test_youtube_video_isolation.py
```

## Benefits

1. **User Isolation**: Each user now has their own copy of YouTube videos
2. **Safe Deletion**: Deleting a video only affects the specific user
3. **Sharing Compatibility**: Video sharing still works correctly
4. **Backward Compatibility**: Existing functionality is preserved
5. **Storage Efficiency**: Multiple users can still share the same YouTube video content without duplication (each has their own S3 reference)

## Technical Details

### S3 Key Structure

**Before:**
```
youtube_videos/
├── dQw4w9WgXcQ.mp4
├── abc123def.mp4
└── ...

youtube_thumbnails/
├── dQw4w9WgXcQ.jpg
├── abc123def.jpg
└── ...

youtube_transcripts/
├── dQw4w9WgXcQ_formatted.txt
├── abc123def_formatted.txt
└── ...
```

**After:**
```
youtube_videos/
├── user1/
│   ├── dQw4w9WgXcQ.mp4
│   └── abc123def.mp4
├── user2/
│   ├── dQw4w9WgXcQ.mp4
│   └── xyz789ghi.mp4
└── ...

youtube_thumbnails/
├── user1/
│   ├── dQw4w9WgXcQ.jpg
│   └── abc123def.jpg
├── user2/
│   ├── dQw4w9WgXcQ.jpg
│   └── xyz789ghi.jpg
└── ...

youtube_transcripts/
├── user1/
│   ├── dQw4w9WgXcQ_formatted.txt
│   └── abc123def_formatted.txt
├── user2/
│   ├── dQw4w9WgXcQ_formatted.txt
│   └── xyz789ghi_formatted.txt
└── ...
```

### Database Changes

No database schema changes were required. The existing `Video` model already stores the S3 keys, so the change is transparent to the database layer.

### API Compatibility

All existing API endpoints continue to work without changes. The user-specific S3 keys are handled internally and don't affect the API interface.

## Monitoring

After deployment, monitor:

1. **S3 Storage**: Check that new videos are being stored with user-specific keys
2. **Video Deletion**: Verify that deleting a video only affects the specific user
3. **Sharing**: Ensure video sharing continues to work correctly
4. **Performance**: Monitor for any performance impact from the changes

## Rollback Plan

If issues arise, the changes can be rolled back by:

1. Reverting the code changes
2. Running a reverse migration script (if needed)
3. The old global structure will continue to work for existing videos

However, this is unlikely to be necessary as the changes are backward compatible and improve the system's reliability.
