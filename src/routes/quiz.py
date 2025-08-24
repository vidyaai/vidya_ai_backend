from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from utils.db import get_db
from controllers.db_helpers import get_transcript_cache, update_transcript_cache
from utils.youtube_utils import download_transcript_api
from controllers.config import s3_client, AWS_S3_BUCKET
from controllers.storage import s3_presign_url
from models import Video
from schemas import QuizRequest
from utils.ml_models import OpenAIQuizClient


router = APIRouter(prefix="/api/quiz", tags=["Quiz"])


@router.post("/generate")
async def generate_quiz(request: QuizRequest, db: Session = Depends(get_db)):
    try:
        video_id = request.video_id
        transcript_info = get_transcript_cache(db, video_id)
        if not transcript_info or not transcript_info.get("transcript_data"):
            video = (
                db.query(Video)
                .filter(Video.id == video_id, Video.source_type == "uploaded")
                .first()
            )
            if video and video.transcript_s3_key:
                try:
                    if s3_client and AWS_S3_BUCKET:
                        obj = s3_client.get_object(
                            Bucket=AWS_S3_BUCKET, Key=video.transcript_s3_key
                        )
                        content = obj["Body"].read().decode("utf-8")
                        update_transcript_cache(db, video_id, content, {})
                        transcript_info = {"transcript_data": content, "json_data": {}}
                except Exception:
                    pass
            else:
                try:
                    transcript_data, json_data = download_transcript_api(video_id)
                    update_transcript_cache(db, video_id, transcript_data, json_data)
                    transcript_info = {
                        "transcript_data": transcript_data,
                        "json_data": json_data,
                    }
                except Exception as e:
                    raise HTTPException(
                        status_code=404,
                        detail=f"Could not retrieve transcript for video {video_id}: {str(e)}",
                    )
        transcript_data = transcript_info.get("transcript_data", "")
        if not transcript_data or transcript_data.strip() == "":
            raise HTTPException(
                status_code=400, detail="No transcript available for this video"
            )
        quiz_client = OpenAIQuizClient()
        quiz_result = quiz_client.generate_quiz(
            transcript=transcript_data,
            num_questions=request.num_questions,
            difficulty=request.difficulty,
            include_explanations=request.include_explanations,
            language=request.language,
        )
        questions = quiz_result.get("questions", [])
        formatted_questions = []
        for i, question in enumerate(questions):
            formatted_question = {
                "id": f"q{i+1}",
                "question": question.get("question", ""),
                "options": question.get("options", []),
                "answer": question.get("answer", ""),
                "difficulty": request.difficulty,
            }
            if request.include_explanations and "explanation" in question:
                formatted_question["explanation"] = question["explanation"]
            formatted_questions.append(formatted_question)
        return {
            "success": True,
            "video_id": video_id,
            "quiz": formatted_questions,
            "message": f"Successfully generated {len(formatted_questions)} questions",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to generate quiz: {str(e)}"
        )
