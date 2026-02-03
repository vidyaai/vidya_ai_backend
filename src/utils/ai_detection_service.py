"""
AI Plagiarism Detection Service for VidyaAI

This service implements a "Defense in Depth" approach to detect AI-generated content:
1. Behavioral telemetry analysis (paste events, typing speed)
2. Stylometric analysis using HuggingFace transformers (roberta-base-openai-detector)

Flags are categorized as:
- "none": No AI detected (confidence < 0.5)
- "soft": Possible AI (0.5 <= confidence < 0.8) - No penalty, yellow highlight
- "hard": Likely AI (confidence >= 0.8) - 50% penalty, red highlight
"""

import logging
from typing import Dict, List, Optional, Any
import torch
from transformers import pipeline, AutoTokenizer, AutoModelForSequenceClassification

# Configure logging
logger = logging.getLogger(__name__)


class AIDetectionService:
    """Singleton service for detecting AI-generated content in student answers."""

    _instance = None
    _classifier = None
    _model_loaded = False

    # Detection thresholds
    SOFT_FLAG_THRESHOLD = 0.4  # Lowered to catch more suspicious cases
    HARD_FLAG_THRESHOLD = 0.7  # Lowered for stronger telemetry signals

    # Telemetry thresholds
    FAST_TYPING_WPM = 120  # Lowered - average human types 40-60 WPM
    LARGE_PASTE_LENGTH = 30  # Lowered to catch smaller paste events

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(AIDetectionService, cls).__new__(cls)
            cls._instance._initialize_model()
        return cls._instance

    def _initialize_model(self):
        """
        Loads the HuggingFace model into memory.
        Using 'roberta-base-openai-detector' as a robust baseline.
        """
        if self._model_loaded:
            return

        try:
            logger.info("Loading AI Detection Model (roberta-base-openai-detector)...")
            model_name = "roberta-base-openai-detector"

            # Check if GPU is available for faster inference
            device = 0 if torch.cuda.is_available() else -1

            self._classifier = pipeline(
                "text-classification",
                model=model_name,
                tokenizer=model_name,
                device=device,
                top_k=None,  # Return scores for all labels (Real vs Fake)
            )
            self._model_loaded = True
            logger.info(
                f"AI Detection Model loaded successfully (device: {'GPU' if device == 0 else 'CPU'})"
            )
        except Exception as e:
            logger.error(f"Failed to load AI detection model: {str(e)}")
            logger.warning("AI detection will run in fallback mode (telemetry-only)")
            self._classifier = None
            self._model_loaded = False

    def detect_ai_content(
        self,
        text: str,
        telemetry: Optional[Dict[str, Any]] = None,
        submission_method: Optional[str] = None,
        question_context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Analyzes text and telemetry to determine if an answer is AI-generated.

        Args:
            text (str): The student's answer text.
            telemetry (dict): Frontend metrics (paste count, time taken, etc.)
            question_context (str): Optional question text for context

        Returns:
            dict: {
                'flag_level': 'none'|'soft'|'hard',
                'confidence': float (0.0-1.0),
                'reasons': list[str],
                'model_score': float,
                'telemetry_score': float
            }
        """
        reasons: List[str] = []
        model_score = 0.0
        telemetry_score = 0.0

        # Skip detection for very short answers
        if not text or len(text.strip()) < 10:
            return self._create_result(
                0.0, 0.0, ["Answer too short to analyze"], "none"
            )

        # 1. Telemetry Heuristics (Behavioral Layer)
        telemetry_score = self._analyze_telemetry(text, telemetry, reasons)

        # 2. Stylometric Analysis (Model Layer)
        model_score = self._analyze_with_model(text, reasons)

        print(f"Model score: {model_score}, Telemetry score: {telemetry_score}")

        # 3. Calculate weighted final score
        if submission_method == "in-app":
            # For in-app submissions, telemetry is more reliable than model
            model_weight = 0.2
            telemetry_weight = 0.8
        else:
            # For PDF submissions, rely only on model (no telemetry available)
            model_weight = 1.0
            telemetry_weight = 0.0

        final_confidence = (model_score * model_weight) + (
            telemetry_score * telemetry_weight
        )
        final_confidence = min(final_confidence, 1.0)

        print(
            f"Final calculation: ({model_score} * {model_weight}) + ({telemetry_score} * {telemetry_weight}) = {final_confidence}"
        )

        # 4. Determine flag level
        if final_confidence >= self.HARD_FLAG_THRESHOLD:
            flag_level = "hard"
        elif final_confidence >= self.SOFT_FLAG_THRESHOLD:
            flag_level = "soft"
        else:
            flag_level = "none"

        return self._create_result(
            final_confidence, model_score, reasons, flag_level, telemetry_score
        )

    def _analyze_telemetry(
        self, text: str, telemetry: Optional[Dict[str, Any]], reasons: List[str]
    ) -> float:
        """
        Analyze behavioral telemetry for suspicious patterns.
        Returns a score between 0.0 and 1.0.
        """
        if not telemetry:
            return 0.0

        score = 0.0

        # Check for paste behavior
        paste_count = telemetry.get("pasteCount", 0)
        pasted = telemetry.get("pasted", False)

        if pasted and len(text) > self.LARGE_PASTE_LENGTH:
            # Any paste of substantial content is highly suspicious
            if paste_count > 0:
                reasons.append(f"Large content pasted ({paste_count} paste event(s))")
                # Score based on paste count: 1 paste = 0.4, 2+ pastes = 0.6
                score += min(0.4 + (paste_count - 1) * 0.2, 0.6)

        # Check typing speed
        time_seconds = telemetry.get("timeToComplete", 0) or telemetry.get(
            "time_taken_seconds", 0
        )
        if time_seconds > 0:
            word_count = len(text.split())
            wpm = (word_count / time_seconds) * 60

            if wpm > self.FAST_TYPING_WPM:
                reasons.append(f"Typing speed exceeds human average ({wpm:.0f} WPM)")
                # Scale score based on how extreme the speed is
                if wpm > 300:  # Impossible without paste
                    score += 0.4
                elif wpm > 200:  # Very suspicious
                    score += 0.3
                else:  # Just fast
                    score += 0.2

        # Check tab switching behavior (possible external tool usage)
        tab_switches = telemetry.get("tabSwitches", 0)
        if tab_switches > 5:
            reasons.append(f"Multiple tab switches detected ({tab_switches})")
            score += 0.15

        # Suspiciously fast completion with substantial text
        if time_seconds > 0 and time_seconds < 10 and len(text) > 100:
            reasons.append("Suspiciously fast completion for answer length")
            # Very fast completion is almost certainly paste
            if time_seconds < 3:
                score += 0.4
            elif time_seconds < 7:
                score += 0.3
            else:
                score += 0.2

        return min(score, 1.0)

    def _analyze_with_model(self, text: str, reasons: List[str]) -> float:
        """
        Analyze text using the HuggingFace transformer model.
        Returns a score between 0.0 and 1.0 (probability of being AI-generated).
        """
        if not self._classifier or not self._model_loaded:
            logger.debug("Model not available, skipping stylometric analysis")
            return 0.0

        # Only run model on substantial text (at least 30 characters)
        if len(text) < 30:
            return 0.0

        try:
            # Truncate to model max length (512 tokens for RoBERTa)
            text_truncated = text[:512]

            # The model returns a list of dicts: [[{'label': 'Fake', 'score': 0.9}, ...]]
            results = self._classifier(text_truncated)

            # Extract score for 'Fake' (AI-generated) label
            # For roberta-base-openai-detector: 'Fake' = AI, 'Real' = Human
            model_score = 0.0
            for res in results[0]:
                if res["label"].lower() in ["fake", "ai", "generated"]:
                    model_score = res["score"]
                    break

            if model_score > self.HARD_FLAG_THRESHOLD:
                reasons.append(
                    f"High stylistic similarity to AI-generated text ({model_score*100:.1f}%)"
                )
            elif model_score > self.SOFT_FLAG_THRESHOLD:
                reasons.append(
                    f"Moderate stylistic similarity to AI-generated text ({model_score*100:.1f}%)"
                )

            return model_score

        except Exception as e:
            logger.error(f"Error during model inference: {str(e)}")
            return 0.0

    def _create_result(
        self,
        confidence: float,
        model_score: float,
        reasons: List[str],
        flag_level: str,
        telemetry_score: float = 0.0,
    ) -> Dict[str, Any]:
        """Create a standardized detection result."""
        return {
            "flag_level": flag_level,
            "confidence": round(confidence, 3),
            "reasons": reasons,
            "model_score": round(model_score, 3),
            "telemetry_score": round(telemetry_score, 3),
            "timestamp": None,  # Will be set by caller
        }

    def detect_batch(
        self, answers: List[Dict[str, Any]], telemetry: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Dict[str, Any]]:
        """
        Detect AI content for multiple answers (per-question detection).

        Args:
            answers: List of dicts with 'question_id' and 'text' keys
            telemetry: Submission-level telemetry (applied to all questions)

        Returns:
            dict: Maps question_id -> detection result
        """
        results = {}

        for answer in answers:
            question_id = answer.get("question_id")
            text = answer.get("text", "")

            if not question_id:
                continue

            # Run detection for this specific answer
            result = self.detect_ai_content(
                text=text,
                telemetry=telemetry,
                question_context=answer.get("question_context"),
            )

            results[question_id] = result

        return results


# Singleton instance getter
_service_instance = None


def get_ai_detection_service() -> AIDetectionService:
    """Get or create the singleton AI detection service instance."""
    global _service_instance
    if _service_instance is None:
        _service_instance = AIDetectionService()
    return _service_instance
