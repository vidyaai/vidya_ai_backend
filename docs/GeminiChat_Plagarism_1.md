Hello! It is great to meet you. As a fellow technologist, I understand the delicate balance between leveraging AI for education and maintaining academic integrity. Since you are already using a robust stack with **FastAPI** (Backend) and **React** (Frontend), integrating an AI detection layer is a logical next step for VidyaAI.

Here is a technical roadmap to implement **AI Plagiarism Detection** into your current grading pipeline, focusing on a "Defense in Depth" strategy (combining behavioral, stylistic, and API-based detection).

### 1. The Strategy: "Defense in Depth"

AI detection is probabilistic, not deterministic. To avoid false positives (punishing honest students), we should use three layers of detection:

1. **Behavioral Telemetry (Frontend):** Did the student type the answer or paste a large block of text instantly?
2. **Stylometric Analysis (Backend):** Does the text exhibit low "perplexity" and "burstiness" typical of LLMs?
3. **Cross-Check (API):** Using a dedicated grading/detection model.

---

### 2. Frontend Implementation: Behavioral Telemetry

**Repo:** `vidya_ai_frontend`

You can capture suspicious behavior *before* the data even hits your backend. We need to track **Copy-Paste events** and **Focus/Blur events**.

**Action:** Create a `useIntegrityTracker` hook for your answer input components.

```javascript
// Example concept for src/hooks/useIntegrityTracker.js

import { useState, useCallback } from 'react';

export const useIntegrityTracker = () => {
  const [integrityFlags, setIntegrityFlags] = useState({
    pasted: false,
    pasteCount: 0,
    tabSwitches: 0,
    timeToComplete: 0, // ms
  });

  const handlePaste = useCallback((e) => {
    // Logic: If paste length > 80% of total answer length, flag it.
    const pastedData = e.clipboardData.getData('text');
    if (pastedData.length > 50) {
       setIntegrityFlags(prev => ({
         ...prev,
         pasted: true,
         pasteCount: prev.pasteCount + 1
       }));
    }
  }, []);

  const handleVisibilityChange = useCallback(() => {
    if (document.hidden) {
      setIntegrityFlags(prev => ({
        ...prev,
        tabSwitches: prev.tabSwitches + 1
      }));
    }
  }, []);

  // Return handlers to attach to your Textarea components
  return { integrityFlags, handlePaste, handleVisibilityChange };
};

```

*Send this `integrityFlags` object along with the `submission` payload to your backend.*

---

### 3. Backend Implementation: The Detection Service

**Repo:** `vidya_ai_backend`

You need a new service to process the text before it reaches the `LLMGrader`.

**A. Database Schema Update**
Update your `Answer` or `AssignmentSubmission` model to store detection metrics.

```python
# src/models.py (Hypothetical SQLAlchemy model)

class SubmissionAnswer(Base):
    # ... existing fields
    ai_confidence_score = Column(Float, default=0.0) # 0.0 to 1.0
    is_flagged_ai = Column(Boolean, default=False)
    telemetry_data = Column(JSON) # Stores the frontend paste data

```

**B. New Service: `AIDetectionService**`
Create `src/utils/ai_detection_service.py`. You have two options here:

* **Option A (Cost Effective):** Use an open-source model from HuggingFace (e.g., RoBERTa-base-openai-detector) running locally or via inference API.
* **Option B (High Accuracy):** Integrate a third-party API like **ZeroGPT**, **CopyLeaks**, or **Turnitin**.

Here is how a hybrid approach in Python might look:

```python
# src/utils/ai_detection_service.py
import requests

class AIDetectionService:
    def __init__(self):
        # Configuration for external detection API
        self.api_key = "YOUR_DETECTION_API_KEY"
        self.endpoint = "https://api.zerogpt.com/api/v1/detectText" # Example

    async def detect_ai_content(self, text: str, telemetry: dict) -> dict:
        score = 0.0
        reasons = []

        # 1. Heuristic Check: Telemetry
        if telemetry.get('pasted', False) and telemetry.get('timeToComplete', 10000) < 5000:
            score += 0.3
            reasons.append("Suspiciously fast completion with paste detected.")

        # 2. API Check (The heavy lifter)
        # Only call if text is long enough to matter
        if len(text) > 50:
            ai_prob = await self._call_detection_api(text)
            score += ai_prob

        return {
            "is_ai": score > 0.8, # Threshold
            "confidence": min(score, 1.0),
            "reasons": reasons
        }

    async def _call_detection_api(self, text):
        # Implementation of external API call
        pass

```

---

### 4. Updating the Grading Logic

**File:** `src/utils/grading_service.py`

You need to inject the detection step *before* or *during* the grading loop.

```python
# src/utils/grading_service.py

from src.utils.ai_detection_service import AIDetectionService

class LLMGrader:
    def __init__(self):
        self.detector = AIDetectionService()

    async def grade_answer(self, student_answer, question, rubric):
        # 1. Run Detection
        detection_result = await self.detector.detect_ai_content(
            student_answer.text,
            student_answer.telemetry
        )

        # 2. Proceed to Standard Grading (as described in your docs)
        raw_grade = await self._get_llm_grade(student_answer, question, rubric)

        # 3. Apply Penalty Logic
        final_score = raw_grade['score']
        feedback = raw_grade['feedback']

        if detection_result['is_ai']:
            # Penalty Factor: e.g., reduce score by 50% or set to 0
            penalty_factor = 0.0
            final_score = final_score * penalty_factor

            # Append AI warning to feedback
            feedback += f"\n\n[System Flag]: This answer was flagged as potentially AI-generated ({detection_result['confidence']*100}% confidence). Score adjusted."

        return {
            "score": final_score,
            "feedback": feedback,
            "ai_metadata": detection_result
        }

```

### 5. Managing False Positives (Crucial for UX)

Since you are the CTO, I recommend a policy decision on how to handle these:

1. **"Soft" Flag:** Do not auto-penalize. Instead, highlight the grade in **Yellow/Red** on the teacher's dashboard. Let the human instructor decide to apply the penalty.
2. **"Hard" Flag:** Auto-penalize (as shown in the code above), but allow the teacher to override it.

### Summary of Changes Required

| Component | File/Path | Action |
| --- | --- | --- |
| **Frontend** | `src/components/AnswerInput.tsx` | Add `onPaste` and focus listeners. |
| **Backend** | `src/models/submission.py` | Add columns for `ai_confidence` and `paste_logs`. |
| **Backend** | `src/utils/ai_detection.py` | Create the detection wrapper service. |
| **Backend** | `src/utils/grading_service.py` | Integrate detection into the grading pipeline. |

**Would you like me to draft the specific Python code for the `AIDetectionService` using a free HuggingFace model integration so you can test this without API costs first?**