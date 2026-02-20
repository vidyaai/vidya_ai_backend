import os
import re
from urllib.parse import quote
import time
import yt_dlp
import cv2
from youtube_transcript_api import YouTubeTranscriptApi
import http.client
import requests
from fastapi import HTTPException
from controllers.config import video_path, logger
from datetime import datetime, timedelta
import threading

# Video cache: {video_id: {'path': temp_file_path, 'last_access': datetime}}
VIDEO_CACHE = {}
CACHE_TTL_MINUTES = 30
CACHE_LOCK = threading.Lock()


def cleanup_expired_cache():
    """Remove cached video files that haven't been accessed in 30 minutes"""
    with CACHE_LOCK:
        now = datetime.now()
        expired_videos = []

        for video_id, cache_data in VIDEO_CACHE.items():
            last_access = cache_data["last_access"]
            age_minutes = (now - last_access).total_seconds() / 60

            if age_minutes >= CACHE_TTL_MINUTES:
                expired_videos.append(video_id)

        # Remove expired entries and delete files
        for video_id in expired_videos:
            cache_data = VIDEO_CACHE.pop(video_id)
            temp_path = cache_data["path"]

            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                    logger.info(
                        f"🗑️ Cache cleanup: Removed expired video cache for {video_id} (age: {age_minutes:.1f} min)"
                    )
                except Exception as e:
                    logger.warning(f"Failed to remove cached file {temp_path}: {e}")
            else:
                logger.warning(f"Cached file already removed: {temp_path}")


def start_cache_cleanup_thread():
    """Start a background thread that cleans up expired cache every 5 minutes"""

    def cleanup_loop():
        while True:
            time.sleep(300)  # Check every 5 minutes
            try:
                cleanup_expired_cache()
            except Exception as e:
                logger.error(f"Error in cache cleanup thread: {e}")

    cleanup_thread = threading.Thread(target=cleanup_loop, daemon=True)
    cleanup_thread.start()
    logger.info("🧹 Started cache cleanup background thread (checks every 5 minutes)")


def download_youtube_video(
    youtube_url,
):  # , output_path=video_path, output_filename="video65", resolution="720"):
    try:
        # Extract video ID from URL
        video_id = extract_youtube_id(youtube_url)
        if not video_id:
            raise HTTPException(status_code=400, detail="Invalid YouTube URL")

        # Get video info from RapidAPI
        headers = {
            "x-rapidapi-key": "87cb804577msh2f08e931a0d9bacp19e810jsn4f8fd6ff742b",
            "x-rapidapi-host": "youtube-media-downloader.p.rapidapi.com",
        }

        params = {
            "videoId": video_id,
            "urlAccess": "normal",
            "videos": "auto",
            "audios": "auto",
        }

        response = requests.get(
            "https://youtube-media-downloader.p.rapidapi.com/v2/video/details",
            params=params,
            headers=headers,
        )

        data = response.json()
        title = data["title"]
        download_url = data["videos"]["items"][0]["url"]

        logger.info(f"Downloading YouTube video: {title}")
        logger.info(f"Starting download for video ID: {video_id}")

        # Download video
        # video_response = requests.get(download_url)

        # Ensure videos directory exists (use configured temp path)
        os.makedirs(video_path, exist_ok=True)
        filename = os.path.join(video_path, f"{video_id}.mp4")

        with requests.get(download_url, stream=True) as video_response:
            video_response.raise_for_status()  # Raise exception for HTTP errors

            with open(filename, "wb") as f:
                # Use a smaller chunk size (1MB) to avoid memory issues
                for chunk in video_response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f.write(chunk)
                        f.flush()  # Ensure data is written to disk

        logger.info(f"Successfully downloaded video to: {filename}")

        # Verify file size is reasonable
        file_size = os.path.getsize(filename)
        if file_size < 10000:  # Less than 10KB is probably an error
            raise ValueError(
                f"Downloaded file is too small ({file_size} bytes), likely corrupted"
            )

        # with open(filename, 'wb') as f:
        #   f.write(video_response.content)

        return filename

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def download_url(
    youtube_url,
):  # , output_path="videos", output_filename="video65", resolution="720"):
    try:
        # Extract video ID from URL
        video_id = extract_youtube_id(youtube_url)
        if not video_id:
            raise HTTPException(status_code=400, detail="Invalid YouTube URL")

        # Get video info from RapidAPI
        headers = {
            "x-rapidapi-key": "87cb804577msh2f08e931a0d9bacp19e810jsn4f8fd6ff742b",
            "x-rapidapi-host": "youtube-media-downloader.p.rapidapi.com",
        }

        params = {
            "videoId": video_id,
            "urlAccess": "normal",
            "videos": "auto",
            "audios": "auto",
        }

        response = requests.get(
            "https://youtube-media-downloader.p.rapidapi.com/v2/video/details",
            params=params,
            headers=headers,
        )

        data = response.json()
        title = data["title"]
        download_url = data["videos"]["items"][0]["url"]

        return download_url

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def extract_youtube_id(url: str) -> str:
    """
    Extract the YouTube video ID from different URL formats
    """
    # Regular expressions to match various YouTube URL formats
    patterns = [
        r"(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/embed\/)([a-zA-Z0-9_-]{11})",
        r"(?:youtube\.com\/watch\?.*v=)([a-zA-Z0-9_-]{11})",
        r"(?:youtube\.com\/shorts\/)([a-zA-Z0-9_-]{11})",
    ]

    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)

    return None


def download_video(
    youtube_url, output_path=video_path, debug=False, video_id_param=None
):
    """Simple YouTube video downloader using RapidAPI with progress checking"""

    # Import here to avoid circular dependency
    from utils.db import SessionLocal
    from controllers.db_helpers import update_download_status

    def log(msg):
        if debug:
            logger.debug(msg)

    # Extract video ID
    video_id = extract_youtube_id(youtube_url)
    if not video_id:
        logger.error("Invalid YouTube URL provided")
        return None

    # Set file path
    file_path = os.path.join(output_path, f"{video_id}.mp4")

    # Check if file already exists
    if os.path.exists(file_path):
        logger.info(f"Video file already exists: {file_path}")
        return file_path

    # Create output directory if needed
    os.makedirs(output_path, exist_ok=True)

    # Your RapidAPI key
    api_key = "87cb804577msh2f08e931a0d9bacp19e810jsn4f8fd6ff742b"

    # Encode the YouTube URL
    encoded_url = quote(youtube_url, safe="")

    # API endpoint
    url = f"https://youtube-info-download-api.p.rapidapi.com/ajax/download.php?format=720&add_info=1&url={encoded_url}&audio_quality=128&allow_extended_duration=true&no_merge=false"

    headers = {
        "x-rapidapi-key": api_key,
        "x-rapidapi-host": "youtube-info-download-api.p.rapidapi.com",
    }
    try:
        # Update status to "preparing"
        if video_id_param:
            db = SessionLocal()
            try:
                status = {
                    "status": "preparing",
                    "message": "🔄 Preparing video from YouTube...",
                    "percentage": 0,
                    "mb_downloaded": 0,
                    "chunks": 0,
                }
                update_download_status(db, video_id_param, status)
                logger.info(f"Status updated to 'preparing' for video {video_id_param}")
            finally:
                db.close()

        # Get initial response
        log(f"Requesting video info for: {youtube_url}")
        response = requests.get(url, headers=headers)

        if response.status_code == 200:
            data = response.json()
            log(f"Title: {data.get('title', 'Unknown')}")

            # Check if we have direct download URL
            download_url = (
                data.get("url") or data.get("download_url") or data.get("link")
            )

            if download_url:
                return download_file_to_path(
                    download_url, file_path, debug, video_id_param or video_id
                )

            # Check if we have progress URL (processing in background)
            elif "progress_url" in data:
                progress_url = data["progress_url"]
                log(f"Video is being processed... Checking progress: {progress_url}")

                # Wait for processing to complete
                for attempt in range(30):  # Try for 5 minutes
                    time.sleep(10)  # Wait 10 seconds between checks

                    try:
                        progress_response = requests.get(progress_url)
                        if progress_response.status_code == 200:
                            progress_data = progress_response.json()
                            log(f"Progress check {attempt + 1}: {progress_data}")

                            # Extract progress information from RapidAPI response
                            raw_progress = progress_data.get("progress", 0)
                            api_status = progress_data.get("status", "processing")
                            api_message = progress_data.get("message", "")

                            # Validate and normalize progress value
                            # RapidAPI returns 0-1000 scale (1000 = 100%)
                            # Convert to 0-100 scale for display
                            if isinstance(raw_progress, (int, float)):
                                # Convert from 0-1000 to 0-100
                                api_progress = int(raw_progress / 10)
                                # Clamp to 0-100 just in case
                                api_progress = max(0, min(100, api_progress))
                                logger.info(
                                    f"Converted progress: {raw_progress}/1000 → {api_progress}%"
                                )
                            else:
                                api_progress = 0

                            # Update buffering status with actual API progress
                            if video_id_param:
                                db = SessionLocal()
                                try:
                                    elapsed_seconds = (attempt + 1) * 10

                                    # Build message based on what RapidAPI returns
                                    if api_progress > 0 and api_progress < 100:
                                        message = f"⏳ Processing video... {api_progress}% complete"
                                    elif api_progress >= 100:
                                        message = f"✅ Processing complete, starting download..."
                                    elif (
                                        api_message
                                        and "contact us" not in api_message.lower()
                                    ):
                                        # Skip the promotional message from RapidAPI
                                        message = f"⏳ {api_message} ({elapsed_seconds}s elapsed)"
                                    else:
                                        message = f"⏳ Video buffering... ({elapsed_seconds}s elapsed)"

                                    status = {
                                        "status": "buffering",
                                        "message": message,
                                        "percentage": api_progress,  # Normalized to 0-100
                                        "mb_downloaded": 0,
                                        "chunks": 0,
                                        "api_status": api_status,  # Pass through API status
                                    }
                                    update_download_status(db, video_id_param, status)
                                    logger.info(
                                        f"Buffering progress: {api_progress}% (raw: {raw_progress}/1000) - Status: {api_status}"
                                    )
                                finally:
                                    db.close()

                            # Look for download URL in progress response
                            download_url = (
                                progress_data.get("url")
                                or progress_data.get("download_url")
                                or progress_data.get("download_link")
                            )

                            if download_url:
                                log("✅ Processing complete! Starting download...")

                                # Update to "downloading" status before actual download
                                if video_id_param:
                                    db = SessionLocal()
                                    try:
                                        status = {
                                            "status": "downloading",
                                            "message": "📥 Starting download from server...",
                                            "percentage": 0,
                                            "mb_downloaded": 0,
                                            "chunks": 0,
                                        }
                                        update_download_status(
                                            db, video_id_param, status
                                        )
                                    finally:
                                        db.close()

                                return download_file_to_path(
                                    download_url,
                                    file_path,
                                    debug,
                                    video_id_param or video_id,
                                )

                            # Check if processing is complete
                            if (
                                progress_data.get("status") == "completed"
                                or progress_data.get("progress") == 100
                            ):
                                break

                    except Exception as e:
                        log(f"Progress check failed: {e}")

                logger.error("Video processing timed out or failed")

            else:
                logger.error(f"API Response error: {data}")
                logger.error("This API requires contacting them for application use")
                logger.error("Visit: https://video-download-api.com/")
        else:
            logger.error(
                f"API request failed: {response.status_code} - {response.text}"
            )

        return None

    except Exception as e:
        logger.error(f"Error downloading video: {e}")
        return None


def download_file_to_path(
    download_url, file_path, debug=False, video_id_for_progress=None
):
    """Download file from URL to specific path"""

    # Import here to avoid circular dependency
    from utils.db import SessionLocal
    from controllers.db_helpers import update_download_status

    def log(msg):
        if debug:
            logger.debug(msg)

    log(f"Downloading from: {download_url[:80]}...")

    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    try:
        video_response = requests.get(
            download_url, stream=True, headers=headers, timeout=300
        )

        if video_response.status_code == 200:
            # Get total size from Content-Length header if available
            total_size = int(video_response.headers.get("content-length", 0))

            with open(file_path, "wb") as f:
                downloaded = 0
                last_update = 0
                chunk_count = 0

                for chunk in video_response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        chunk_count += 1

                        # Update progress in database if video_id is provided
                        if video_id_for_progress and total_size > 0:
                            percentage = int((downloaded / total_size) * 100)

                            # Update every 1MB OR every 5% change OR at the end
                            percentage_change = percentage - last_update
                            should_update = (
                                downloaded % (1024 * 1024) == 0
                                or percentage_change >= 5  # Every 1MB
                                or percentage >= 99  # Every 5% change  # At the end
                            )

                            if should_update:
                                db = SessionLocal()
                                try:
                                    # Create detailed message based on progress
                                    if percentage < 10:
                                        detail_msg = "Starting download..."
                                    elif percentage < 30:
                                        detail_msg = "Downloading from server..."
                                    elif percentage < 60:
                                        detail_msg = "Download in progress..."
                                    elif percentage < 90:
                                        detail_msg = "Almost there..."
                                    else:
                                        detail_msg = "Finalizing download..."

                                    status = {
                                        "status": "downloading",
                                        "message": f"{detail_msg} {percentage}%",
                                        "progress": percentage,
                                        "downloaded_bytes": downloaded,
                                        "total_bytes": total_size,
                                        "chunks_received": chunk_count,
                                        "path": None,
                                    }
                                    update_download_status(
                                        db, video_id_for_progress, status
                                    )
                                    last_update = percentage
                                    log(
                                        f"Progress updated: {percentage}% ({downloaded / (1024*1024):.1f} MB / {total_size / (1024*1024):.1f} MB)"
                                    )
                                finally:
                                    db.close()

                        if downloaded % (5 * 1024 * 1024) == 0:
                            log(f"Downloaded: {downloaded / (1024*1024):.1f} MB")

            file_size = os.path.getsize(file_path)
            if file_size > 1000:
                logger.info(
                    f"Successfully downloaded: {file_path} ({file_size / (1024*1024):.1f} MB)"
                )
                return file_path
            else:
                logger.warning(f"Downloaded file too small: {file_size} bytes")
                os.remove(file_path)
        else:
            logger.error(f"Download failed with status: {video_response.status_code}")

    except Exception as e:
        logger.error(f"Download error: {e}")

    return None


def download_video1(youtube_url, output_path=".", debug=False):
    """
    Downloads a YouTube video using yt-dlp with full cookie support.

    Args:
        youtube_url (str): YouTube video URL
        output_path (str): Save location (default: current directory)
        debug (bool): Enable verbose logging

    Returns:
        str: File path if downloaded, else None
    """

    def log(msg):
        if debug:
            logger.debug(msg)

    video_id = extract_youtube_id(youtube_url)
    if not video_id:
        logger.error("Invalid YouTube URL provided")
        return None

    file_path = os.path.join(output_path, f"{video_id}.mp4")
    if os.path.exists(file_path):
        logger.info(f"Video file already exists: {file_path}")
        return file_path

    # Find cookies file
    cookie_locations = [
        "./cookies.txt",
        "/tmp/cookies.txt",
        os.path.expanduser("~/cookies.txt"),
    ]
    cookie_file = None
    for loc in cookie_locations:
        if os.path.isfile(loc):
            cookie_file = loc
            break

    if not cookie_file:
        logger.warning("No cookies.txt file found. YouTube may block download.")
        return None

    log(f"Using cookie file: {cookie_file}")

    ydl_opts = {
        "format": "best[height<=720]/best",
        "outtmpl": file_path,
        "quiet": not debug,
        "cookiefile": cookie_file,
        "retries": 10,
        "fragment_retries": 10,
        "socket_timeout": 30,
        "noplaylist": True,
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "*/*",
            "Referer": "https://www.youtube.com/",
        },
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            log(f"Downloading: {youtube_url}")
            ydl.download([youtube_url])

        if os.path.exists(file_path) and os.path.getsize(file_path) > 10000:
            logger.info(f"Successfully downloaded: {file_path}")
            return file_path
        else:
            raise Exception("File download failed or incomplete")
    except Exception as e:
        logger.error(f"Error during download: {e}")
        if "Sign in to confirm you're not a bot" in str(e):
            logger.error("BOT DETECTION BLOCKED DOWNLOAD.")
            logger.error("Try the following:")
            logger.error("1. Login to YouTube in your browser")
            logger.error("2. Use a cookie exporter like 'Get cookies.txt' extension")
            logger.error("3. Save cookies to ./cookies.txt")
            logger.error("4. Retry")
        return None


def download_transcript_api1(video_id):
    conn = http.client.HTTPSConnection("youtube-transcript3.p.rapidapi.com")

    headers = {
        "x-rapidapi-key": "87cb804577msh2f08e931a0d9bacp19e810jsn4f8fd6ff742b",
        "x-rapidapi-host": "youtube-transcript3.p.rapidapi.com",
    }

    url = "https://youtube-transcript3.p.rapidapi.com/api/transcript"
    querystring = {"videoId": video_id}
    response = requests.get(url, headers=headers, params=querystring)

    if response.status_code == 200:
        transcript_data = response.json()

        # RapidAPI usually returns the transcript in a specific format
        # Check if we have tr    anscript entries to process
        if "transcript" in transcript_data and transcript_data["transcript"]:
            return transcript_data["transcript"]
        else:
            logger.warning("No transcript data in the response")
            return None
    else:
        logger.error(f"Transcript API error: {response.status_code} - {response.text}")
        return None


def download_youtube_audio_rapidapi(video_id):
    """
    Download audio from YouTube using RapidAPI (downloads video then extracts audio).

    Uses 360p video format since format=audio is not always available.
    Extracts audio using FFmpeg to reduce file size for transcription.

    Args:
        video_id: YouTube video ID

    Returns:
        str: Path to temporary audio file (MP3), or None if download failed
    """
    import tempfile
    import subprocess
    import time

    try:
        youtube_url = f"https://www.youtube.com/watch?v={video_id}"
        encoded_url = quote(youtube_url, safe="")

        # Use RapidAPI to get video download URL
        api_key = "87cb804577msh2f08e931a0d9bacp19e810jsn4f8fd6ff742b"

        # Use 360p format (smaller file, has audio) - format=audio doesn't work for all videos
        url = f"https://youtube-info-download-api.p.rapidapi.com/ajax/download.php?format=360&add_info=1&url={encoded_url}&audio_quality=128&allow_extended_duration=true&no_merge=false"

        headers = {
            "x-rapidapi-key": api_key,
            "x-rapidapi-host": "youtube-info-download-api.p.rapidapi.com",
        }

        logger.info(f"Requesting video download URL from RapidAPI for {video_id}...")
        response = requests.get(url, headers=headers, timeout=30)

        if response.status_code != 200:
            logger.error(f"RapidAPI returned status {response.status_code}")
            return None

        data = response.json()

        # Check for direct download URL
        download_url = data.get("url") or data.get("download_url") or data.get("link")

        # If no direct URL, poll progress URL
        if not download_url and "progress_url" in data:
            progress_url = data["progress_url"]
            logger.info(f"Polling progress URL for download link...")

            # Poll up to 6 times (60 seconds)
            for attempt in range(6):
                if attempt > 0:
                    time.sleep(10)

                try:
                    progress_response = requests.get(progress_url, timeout=30)
                    if progress_response.status_code == 200:
                        progress_data = progress_response.json()
                        download_url = (
                            progress_data.get("url")
                            or progress_data.get("download_url")
                            or progress_data.get("download_link")
                        )
                        if download_url:
                            logger.info(f"Got download URL after {attempt * 10}s")
                            break
                except Exception as poll_error:
                    logger.warning(f"Progress poll error: {poll_error}")

        if not download_url:
            logger.error(f"No download URL found for {video_id}")
            return None

        # Download video file
        logger.info(f"Downloading video file...")
        temp_fd, video_temp_path = tempfile.mkstemp(suffix='.mp4', prefix=f'yt_video_{video_id}_')
        os.close(temp_fd)

        video_response = requests.get(download_url, stream=True, timeout=120)
        if video_response.status_code != 200:
            logger.error(f"Failed to download video: {video_response.status_code}")
            os.remove(video_temp_path)
            return None

        # Write video to temp file
        total_size = 0
        with open(video_temp_path, 'wb') as f:
            for chunk in video_response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    total_size += len(chunk)

        logger.info(f"Video downloaded: {total_size / (1024*1024):.2f} MB")

        # Extract audio using FFmpeg to reduce file size
        logger.info(f"Extracting audio from video...")
        audio_fd, audio_temp_path = tempfile.mkstemp(suffix='.mp3', prefix=f'yt_audio_{video_id}_')
        os.close(audio_fd)

        try:
            cmd = [
                'ffmpeg', '-i', video_temp_path,
                '-vn',  # No video
                '-acodec', 'libmp3lame',  # MP3 codec
                '-b:a', '128k',  # 128kbps bitrate
                '-y',  # Overwrite output
                audio_temp_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

            if result.returncode != 0:
                logger.warning(f"FFmpeg extraction failed: {result.stderr[:200]}")
                # Fall back to using video file
                os.remove(audio_temp_path)
                logger.info(f"Using video file directly for transcription")
                return video_temp_path
            else:
                audio_size = os.path.getsize(audio_temp_path) / (1024*1024)
                logger.info(f"Audio extracted: {audio_size:.2f} MB")
                # Clean up video file
                os.remove(video_temp_path)
                return audio_temp_path

        except Exception as ffmpeg_error:
            logger.warning(f"Audio extraction error: {ffmpeg_error}")
            # Fall back to video file
            if os.path.exists(audio_temp_path):
                os.remove(audio_temp_path)
            logger.info(f"Using video file directly for transcription")
            return video_temp_path

    except Exception as e:
        logger.error(f"Failed to download YouTube audio via RapidAPI for {video_id}: {e}")
        # Clean up temp files on error
        try:
            if 'video_temp_path' in locals() and os.path.exists(video_temp_path):
                os.remove(video_temp_path)
            if 'audio_temp_path' in locals() and os.path.exists(audio_temp_path):
                os.remove(audio_temp_path)
        except Exception:
            pass
        return None


def download_transcript_api(video_id):
    """
    Download transcript using RapidAPI. Falls back to Deepgram if no captions available.

    Args:
        video_id: YouTube video ID

    Returns:
        tuple: (transcript_text, json_data)
    """
    try:
        headers = {
            "x-rapidapi-key": "87cb804577msh2f08e931a0d9bacp19e810jsn4f8fd6ff742b",
            "x-rapidapi-host": "youtube-transcriptor.p.rapidapi.com",
        }

        url = "https://youtube-transcriptor.p.rapidapi.com/transcript"
        querystring = {"video_id": video_id, "lang": "en"}
        response = requests.get(url, headers=headers, params=querystring)

        if response.status_code == 200:
            transcript_data = response.json()
            # print("-----transcript data--------", transcript_data)

            if not "error" in transcript_data:
                # RapidAPI usually returns the transcript in a specific format
                # Check if we have transcript entries to process
                if (
                    "transcriptionAsText" in transcript_data[0]
                    and transcript_data[0]["transcriptionAsText"]
                ):
                    return transcript_data[0]["transcriptionAsText"], response.json()
                else:
                    logger.warning("No transcript data in the response")
                    raise Exception("No transcript data in the response")
            else:
                if "availableLangs" in transcript_data:
                    for lang in transcript_data["availableLangs"]:
                        if "en" in lang:
                            querystring["lang"] = lang
                            response = requests.get(
                                url, headers=headers, params=querystring
                            )
                            if response.status_code == 200:
                                transcript_data = response.json()
                                if (
                                    "transcriptionAsText" in transcript_data[0]
                                    and transcript_data[0]["transcriptionAsText"]
                                ):
                                    return (
                                        transcript_data[0]["transcriptionAsText"],
                                        response.json(),
                                    )
                                else:
                                    logger.warning("No transcript data in the response")
                                    raise Exception("No transcript data in the response")
                logger.error(f"Transcript error: {transcript_data['error']}")
                raise Exception("Transcription Error: ", transcript_data["error"])
        else:
            logger.error(f"Transcript API error: {response.status_code} - {response.text}")
            raise Exception(
                f"Transcription Error: {response.status_code} - {response.text}"
            )

    except Exception as e:
        error_msg = str(e).lower()

        # Check if error is due to missing captions/subtitles
        if "no subtitles" in error_msg or "transcription error" in error_msg or "no transcript" in error_msg:
            logger.warning(f"No captions found for video {video_id}, falling back to Deepgram transcription")

            temp_audio_file = None
            try:
                # Import Deepgram transcription function (file-based)
                from controllers.storage import transcribe_video_with_deepgram

                logger.info(f"Downloading audio for {video_id} to transcribe with Deepgram...")

                # Download audio to temporary file using RapidAPI
                temp_audio_file = download_youtube_audio_rapidapi(video_id)

                if not temp_audio_file:
                    raise Exception("Failed to download YouTube audio")

                logger.info(f"Starting Deepgram transcription for {video_id} (this may take a few minutes)")

                # Transcribe using Deepgram with the local audio file
                transcript_text = transcribe_video_with_deepgram(temp_audio_file)

                if not transcript_text or not transcript_text.strip():
                    raise Exception("Deepgram returned empty transcript")

                # Format response to match RapidAPI structure
                json_data = [{
                    "transcriptionAsText": transcript_text,
                    "source": "deepgram",
                    "video_id": video_id,
                    "lang": "en"
                }]

                logger.info(f"Successfully transcribed video {video_id} using Deepgram ({len(transcript_text)} chars)")

                return transcript_text, json_data

            except Exception as deepgram_error:
                logger.error(f"Deepgram transcription failed for {video_id}: {deepgram_error}")
                raise Exception(
                    f"No captions available and Deepgram transcription failed: {str(deepgram_error)}"
                )
            finally:
                # Clean up temporary audio file
                if temp_audio_file and os.path.exists(temp_audio_file):
                    try:
                        os.remove(temp_audio_file)
                        logger.info(f"Cleaned up temporary audio file: {temp_audio_file}")
                    except Exception as cleanup_error:
                        logger.warning(f"Failed to clean up temp file {temp_audio_file}: {cleanup_error}")
        else:
            # Re-raise non-caption-related errors
            raise


def format_transcript_data(transcript_data):
    """Format transcript data into readable text with proper punctuation"""
    if not transcript_data:
        return None

    # Check if we're dealing with RapidAPI format
    if isinstance(transcript_data, list) and all(
        isinstance(item, dict) for item in transcript_data
    ):
        # Extract text from each item and join with proper spacing and punctuation
        full_text = ""
        for item in transcript_data:
            # Get the text, clean HTML entities
            text = item.get("text", "").strip()
            text = text.replace("&#39;", "'")  # Replace HTML apostrophe

            # Add to full text with proper spacing and capitalization
            if (
                full_text
                and not full_text.endswith(".")
                and not full_text.endswith("?")
                and not full_text.endswith("!")
            ):
                # If previous text didn't end with punctuation, add a period
                full_text += ". "
            elif full_text:
                # If it ended with punctuation, just add space
                full_text += " "

            # Capitalize first letter if it's the start of a sentence
            if (
                not full_text
                or full_text.endswith(". ")
                or full_text.endswith("? ")
                or full_text.endswith("! ")
            ):
                text = text[0].upper() + text[1:] if text else text

            full_text += text

        # Ensure text ends with a period if it doesn't have final punctuation
        if (
            full_text
            and not full_text.endswith(".")
            and not full_text.endswith("?")
            and not full_text.endswith("!")
        ):
            full_text += "."

        return full_text

    else:
        return "Invalid transcript format"


def download_transcript(video_url_or_id):
    try:
        # Extract video ID
        if "youtube.com" in video_url_or_id or "youtu.be" in video_url_or_id:
            if "youtube.com/watch?v=" in video_url_or_id:
                video_id = video_url_or_id.split("watch?v=")[-1].split("&")[0]
            elif "youtu.be/" in video_url_or_id:
                video_id = video_url_or_id.split("youtu.be/")[-1].split("?")[0]
            else:
                raise ValueError("Invalid YouTube URL.")
        else:
            video_id = video_url_or_id

        # Fetch transcript
        transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=["en"])
        transcript_text = " ".join([item["text"] for item in transcript])
        # print(transcript_text)
        return transcript_text
    except Exception as e:
        logger.error(f"Error fetching transcript: {e}")
        return None


def grab_youtube_frame(video_path_func, timestamp, output_file="extracted_frame.jpg"):
    """
    Extract a frame from a YouTube video at a specific timestamp.

    Args:
        video_path_func (str): The path or URL to the video file
        timestamp (float): Time in seconds where you want to capture the frame
        output_file (str): Path to save the extracted frame

    Returns:
        tuple: (str, numpy.ndarray) Path to the saved frame image and the frame itself
    """
    frame = None
    video = None
    temp_file_created = False

    try:
        video_path = video_path_func
        video_id = None

        # DEBUG: Log what type of path we received
        if video_path.startswith("http://") or video_path.startswith("https://"):
            logger.info(f"🔴 RECEIVED S3 URL: {video_path[:100]}...")

            # Try to extract video_id from the S3 URL (format: .../video_id.mp4)
            try:
                # Extract filename from URL
                filename = video_path.split("/")[-1].split("?")[
                    0
                ]  # Remove query params
                video_id = filename.replace(".mp4", "").replace(".webm", "")
                logger.info(f"� Extracted video_id: {video_id}")
            except:
                logger.warning("Could not extract video_id from S3 URL")

            # Check if we have this video cached
            with CACHE_LOCK:
                if video_id and video_id in VIDEO_CACHE:
                    cache_data = VIDEO_CACHE[video_id]
                    cached_path = cache_data["path"]

                    # Verify the cached file still exists
                    if os.path.exists(cached_path):
                        age_minutes = (
                            datetime.now() - cache_data["last_access"]
                        ).total_seconds() / 60
                        logger.info(
                            f"✨ Using CACHED video! (age: {age_minutes:.1f} min, path: {cached_path})"
                        )

                        # Update last access time
                        VIDEO_CACHE[video_id]["last_access"] = datetime.now()
                        video_path = cached_path
                    else:
                        logger.warning(
                            f"⚠️ Cached file no longer exists, removing from cache"
                        )
                        VIDEO_CACHE.pop(video_id, None)
                        video_id = None  # Force re-download

            # If not in cache or cache invalid, download it
            if not video_id or video_id not in VIDEO_CACHE:
                logger.info(
                    f"📥 Video not in cache, downloading temporarily for frame extraction..."
                )

                # Download the video temporarily
                import tempfile

                temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
                temp_path = temp_file.name
                temp_file.close()
                temp_file_created = True

                # Download from S3 URL
                download_start = time.time()
                response = requests.get(video_path, stream=True, timeout=60)
                if response.status_code == 200:
                    total_size = int(response.headers.get("content-length", 0))
                    downloaded = 0

                    with open(temp_path, "wb") as f:
                        for chunk in response.iter_content(chunk_size=1024 * 1024):
                            if chunk:
                                f.write(chunk)
                                downloaded += len(chunk)

                    download_time = time.time() - download_start
                    size_mb = total_size / (1024 * 1024)
                    logger.info(
                        f"✅ Video downloaded in {download_time:.1f}s ({size_mb:.1f} MB) to: {temp_path}"
                    )

                    # Add to cache
                    if video_id:
                        with CACHE_LOCK:
                            VIDEO_CACHE[video_id] = {
                                "path": temp_path,
                                "last_access": datetime.now(),
                            }
                        logger.info(
                            f"💾 Video cached for video_id: {video_id} (will auto-delete after {CACHE_TTL_MINUTES} min of inactivity)"
                        )
                        temp_file_created = False  # Don't delete in finally block

                    video_path = temp_path
                else:
                    raise Exception(
                        f"Failed to download video from S3: {response.status_code}"
                    )

        elif video_path.startswith("/"):
            logger.info(f"🟢 RECEIVED LOCAL PATH: {video_path}")
            logger.info(f"🟢 File exists: {os.path.exists(video_path)}")
        else:
            logger.info(f"⚠️ UNKNOWN PATH TYPE: {video_path}")

        # Open the video with OpenCV
        video = cv2.VideoCapture(video_path)

        if not video.isOpened():
            raise Exception(f"Failed to open video file: {video_path}")

        # Get video properties
        fps = video.get(cv2.CAP_PROP_FPS)
        logger.info(f"Video FPS: {fps}")

        if fps == 0 or fps is None:
            raise Exception(
                "Invalid FPS value, video file may be corrupted or inaccessible"
            )

        total_frames = int(video.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = total_frames / fps

        logger.info(f"Video duration: {duration:.2f} seconds")
        logger.info(f"FPS: {fps}")

        # Calculate frame number for the given timestamp
        frame_number = int(timestamp * fps)

        # Check if timestamp is within video duration
        if timestamp > duration:
            raise ValueError(
                f"Timestamp {timestamp} exceeds video duration {duration:.2f}"
            )

        # Seek to the specified frame
        video.set(cv2.CAP_PROP_POS_FRAMES, frame_number)

        # Read the frame
        ret, frame = video.read()

        if ret:
            # Save the frame
            cv2.imwrite(output_file, frame)
            logger.info(f"Frame saved to: {output_file}")
            return output_file, frame
        else:
            raise RuntimeError(f"Failed to extract frame at timestamp {timestamp}")

    except Exception as e:
        logger.error(f"Error extracting frame: {str(e)}")
        return None, None
    finally:
        if video is not None:
            video.release()
        # Only clean up temporary file if it was NOT added to cache
        if temp_file_created and "temp_path" in locals() and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
                logger.info(
                    f"🗑️ Temporary (non-cached) video file removed: {temp_path}"
                )
            except Exception as e:
                logger.warning(f"Failed to remove temporary file: {e}")
