import httpx


async def get_video_title(video_id: str) -> str:
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"https://www.youtube.com/oembed?url=http://www.youtube.com/watch?v={video_id}&format=json"
            )
            if response.status_code == 200:
                data = response.json()
                return data.get("title", f"YouTube Video ({video_id})")
    except Exception:
        pass
    return f"YouTube Video ({video_id})"
