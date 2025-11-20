#!/usr/bin/env python3
"""
Test script to see what RapidAPI returns for a specific YouTube video
"""

import requests
from urllib.parse import quote
import time
import json

# Test video
youtube_url = "https://www.youtube.com/watch?v=-AeyQH7_93E"

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

print("=" * 80)
print(f"Testing YouTube URL: {youtube_url}")
print("=" * 80)

try:
    # Get initial response
    print("\n[1] Making initial request to RapidAPI...")
    response = requests.get(url, headers=headers)
    
    print(f"Status Code: {response.status_code}")
    print(f"\nInitial Response:")
    print(json.dumps(response.json(), indent=2))
    
    if response.status_code == 200:
        data = response.json()
        
        # Check for direct download URL
        download_url = data.get("url") or data.get("download_url") or data.get("link")
        
        if download_url:
            print("\n✅ Direct download URL found!")
            print(f"Download URL: {download_url[:100]}...")
            print("\nNo buffering needed - video ready immediately!")
        
        # Check for progress URL
        elif "progress_url" in data:
            progress_url = data["progress_url"]
            print(f"\n⏳ Video needs processing. Progress URL: {progress_url}")
            
            # Poll progress
            print("\n[2] Polling progress every 10 seconds...")
            for attempt in range(5):  # Try 5 times (50 seconds)
                time.sleep(10)
                
                print(f"\n--- Attempt {attempt + 1} (after {(attempt + 1) * 10}s) ---")
                progress_response = requests.get(progress_url)
                
                if progress_response.status_code == 200:
                    progress_data = progress_response.json()
                    print(f"Status Code: {progress_response.status_code}")
                    print(f"Progress Response:")
                    print(json.dumps(progress_data, indent=2))
                    
                    # Extract key fields
                    print("\n📊 Extracted Fields:")
                    print(f"  - progress: {progress_data.get('progress', 'NOT FOUND')}")
                    print(f"  - status: {progress_data.get('status', 'NOT FOUND')}")
                    print(f"  - message: {progress_data.get('message', 'NOT FOUND')}")
                    print(f"  - url: {progress_data.get('url', 'NOT FOUND')[:50] if progress_data.get('url') else 'NOT FOUND'}...")
                    print(f"  - download_url: {progress_data.get('download_url', 'NOT FOUND')[:50] if progress_data.get('download_url') else 'NOT FOUND'}...")
                    
                    # Check if ready
                    download_url = (
                        progress_data.get("url")
                        or progress_data.get("download_url")
                        or progress_data.get("download_link")
                    )
                    
                    if download_url:
                        print(f"\n✅ Download URL found after {(attempt + 1) * 10} seconds!")
                        print(f"Download URL: {download_url[:100]}...")
                        break
                    
                    if progress_data.get("status") == "completed" or progress_data.get("progress") == 100:
                        print("\n✅ Processing marked as complete!")
                        break
                else:
                    print(f"❌ Progress check failed with status: {progress_response.status_code}")
        else:
            print("\n❌ No download URL or progress URL found!")
            print("Available keys:", list(data.keys()))
    else:
        print(f"\n❌ Request failed with status: {response.status_code}")
        print(response.text)

except Exception as e:
    print(f"\n❌ Error: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 80)
print("Test complete!")
print("=" * 80)
