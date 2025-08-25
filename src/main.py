from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
import os
import uvicorn
from routes.youtube import router as youtube_router
from routes.user_videos import router as user_videos_router
from routes.quiz import router as quiz_router
from routes.gallery_folders import router as gallery_folders_router
from routes.files import router as files_router
from routes.misc import router as misc_router
from routes.query import router as query_router


app = FastAPI(
    title="Vidya AI Backend API",
    description="Vidya AI Backend API",
    version="1.0.0",
)


@app.options("/{path:path}")
async def options_route(path: str):
    return Response(status_code=200)


@app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Credentials"] = "true"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    response.headers["Cross-Origin-Resource-Policy"] = "cross-origin"
    response.headers["Cross-Origin-Embedder-Policy"] = "require-corp"
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://d1xrorvpgizypa.cloudfront.net",
        "https://vidyaai.co",
        "http://localhost:5173",
        "https://www.vidyaai.co",
        "https://upload-video.d2krgf8gkzw2h8.amplifyapp.com",
        "https://upload-video.d2krgf8gkzw2h8.amplifyapp.com/*",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def read_root():
    return {"status": "Vidya AI backend is running"}


app.include_router(youtube_router)
app.include_router(user_videos_router)
app.include_router(quiz_router)
app.include_router(gallery_folders_router)
app.include_router(files_router)
app.include_router(misc_router)
app.include_router(query_router)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
