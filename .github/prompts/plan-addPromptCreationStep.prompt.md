Plan: Add Prompt-Creation Step to Step 3

TL;DR: Insert a new prompt-preparation step between GPT-4o batching and GPT-5 generation. Add a helper `_create_batch_prompts_with_images` that presigns/embeds diagrams and returns prepared payloads; change `_generate_batch_answers` to accept prepared payloads; update `_generate_missing_answers_and_rubrics` to call the new function and then run the prepared payloads in parallel, consolidating results as before. This improves separation of concerns, makes prompts+images explicit, and enables better error handling for presigns and prompt size issues.

Steps
1. Add helper `_create_batch_prompts_with_images` in `src/utils/assignment_document_parser.py` that builds `prompt_text` and `image_contents` (using `s3_presign_url`, resizing/inline fallback), returns list of prepared batch payloads.
2. Change `_generate_batch_answers` signature to accept a `prepared_batch` dict (use keys `'prompt_text'`, `'image_contents'`, `'batch_index'`, `'batch_questions'`) and use those directly to call GPT-5; remove duplicate presign logic.
3. Update `_generate_missing_answers_and_rubrics` to: call `_group_questions_into_batches_gpt4o` (unchanged) -> call `_create_batch_prompts_with_images` -> submit `self._generate_batch_answers(prepared)` for each prepared payload in ThreadPoolExecutor, then consolidate results into `all_generated` and apply them to original questions (keep current mapping/apply logic).
4. Add improved logging, presign error handling, LLM retry/backoff config (suggest new env vars), and prompt-size estimator to `_create_batch_prompts_with_images` to split or flag oversized batches.
5. Add tests (5 tests described) and small docs/comments explaining the new flow; ensure keys/paths are normalized to strings and empty LLM responses are handled gracefully (return {} for that batch, continue others).

Further Considerations
1. Presign fallback: Option A — embed small cropped images as base64 (resize to <= ~200KB); Option B — include textual caption and mark missing images for LLM to adapt. Choose A for higher fidelity or B for simpler, smaller payloads. - Option A preferred.
2. Failure strategy: Continue processing remaining batches on per-batch failure (log and return empty mapping for failed batch). Retry LLM calls 2–3 times with exponential backoff before giving up.
3. Tests: Use mocks for `s3_presign_url` and `self.GPTclient.chat.completions.create`; assert mapping shape, logging on errors, and early-return when no generation needed.

Would you like me to implement these changes now and produce the patch, or adjust the plan (e.g., pick presign fallback strategy or exact retry/backoff parameters) first?
