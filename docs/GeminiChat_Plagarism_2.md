Here is the implementation of the `AIDetectionService` using the **Hugging Face `transformers` library**. This approach runs the model locally on your server, meaning it is **free** (no API costs) and keeps student data private within your infrastructure.

### 1. Prerequisites

First, you need to add the machine learning libraries to your `requirements.txt` file (referenced in your backend repo ).

```bash
# Add these to src/requirements.txt
transformers>=4.30.0
torch>=2.0.0
scipy>=1.10.0

```

### 2. The Detection Service

Create this file at `src/utils/ai_detection_service.py`.

This service uses a pre-trained RoBERTa model fine-tuned for AI detection. It loads the model once (singleton pattern) to avoid performance hits on every request.

```python
import logging
import torch
from transformers import pipeline, AutoTokenizer, AutoModelForSequenceClassification

# Configure logging
logger = logging.getLogger(__name__)

class AIDetectionService:
    _instance = None
    _classifier = None

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
        try:
            logger.info("Loading AI Detection Model...")
            model_name = "roberta-base-openai-detector"  # You can swap this for newer models

            # Check if GPU is available for faster inference
            device = 0 if torch.cuda.is_available() else -1

            self._classifier = pipeline(
                "text-classification",
                model=model_name,
                tokenizer=model_name,
                device=device,
                top_k=None  # Return scores for all labels (Real vs Fake)
            )
            logger.info("AI Detection Model loaded successfully.")
        except Exception as e:
            logger.error(f"Failed to load AI model: {str(e)}")
            # Fallback to None to allow system to run without crashing
            self._classifier = None

    def detect_ai_content(self, text: str, telemetry: dict = None) -> dict:
        """
        Analyzes text and telemetry to determine if an answer is AI-generated.

        Args:
            text (str): The student's answer text.
            telemetry (dict): Frontend metrics (paste count, time taken, etc.)

        Returns:
            dict: { 'is_ai': bool, 'confidence': float, 'flags': list }
        """
        flags = []
        ai_probability = 0.0

        # 1. Telemetry Heuristics (Behavioral Layer)
        telemetry_score = 0.0
        if telemetry:
            # Flag if pasted and pasted content is large
            if telemetry.get('pasted', False) and len(text) > 50:
                flags.append("Significant copy-paste detected")
                telemetry_score += 0.2

            # Flag if typed suspiciously fast (e.g., > 150 words per minute)
            word_count = len(text.split())
            time_seconds = telemetry.get('time_taken_seconds', 1)
            if time_seconds > 0:
                wpm = (word_count / time_seconds) * 60
                if wpm > 150:
                    flags.append("Typing speed exceeds human average")
                    telemetry_score += 0.3

        # 2. Stylometric Analysis (Model Layer)
        model_score = 0.0
        if self._classifier and len(text) > 30: # Only run model on substantial text
            try:
                # The model returns a list of dicts, e.g., [[{'label': 'Fake', 'score': 0.9}, ...]]
                results = self._classifier(text[:512]) # Truncate to model max length

                # Extract score for 'Fake' (AI-generated) label
                # Note: Label names depend on specific model.
                # For roberta-openai-detector: 'Fake' = AI, 'Real' = Human
                for res in results[0]:
                    if res['label'] == 'Fake':
                        model_score = res['score']
                        break

                if model_score > 0.8:
                    flags.append(f"High stylistic resemblance to AI ({(model_score*100):.1f}%)")
            except Exception as e:
                logger.error(f"Error during inference: {e}")

        # 3. Weighted Final Score
        # We weigh the model higher (0.7) than telemetry (0.3)
        final_confidence = (model_score * 0.7) + (telemetry_score * 0.3)

        # Cap confidence at 1.0
        final_confidence = min(final_confidence, 1.0)

        return {
            "is_ai": final_confidence > 0.65, # Configurable threshold
            "confidence": round(final_confidence, 2),
            "telemetry_flags": flags,
            "raw_model_score": round(model_score, 2)
        }

```

### 3. Integration into `LLMGrader`

Now, modify your `src/utils/grading_service.py` to use this class.

```python
# In src/utils/grading_service.py

from src.utils.ai_detection_service import AIDetectionService

# Inside your grading function/class
async def grade_submission(self, submission_data):

    # ... existing setup code ...

    detector = AIDetectionService()

    # Run detection
    detection_result = detector.detect_ai_content(
        text=submission_data['answer_text'],
        telemetry=submission_data.get('telemetry_data', {})
    )

    # Proceed to grade
    # ... (Your existing LLM grading logic) ...

    # Post-grading adjustment
    if detection_result['is_ai']:
        # Option A: Hard penalty (reduce score by 50%)
        # final_score = final_score * 0.5

        # Option B: Add a flag for the teacher (Recommended for V1)
        feedback_text += (
            f"\n\n⚠️ **AI Detection Warning**\n"
            f"System confidence: {detection_result['confidence']*100}%\n"
            f"Flags: {', '.join(detection_result['telemetry_flags'])}"
        )

        # You might want to save this flag to the database
        submission.is_flagged_ai = True
        submission.ai_confidence = detection_result['confidence']

    return final_score, feedback_text

```

### Next Step

Since you are the CTO, you likely want to verify the model's accuracy before deploying.

**Would you like me to write a small `test_detection.py` script that you can run locally with some sample "Human" vs "AI" text to benchmark the accuracy?**