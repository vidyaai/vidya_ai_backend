## Plan: Unified Dynamic Batching & Language Filtering (Step 0)

Replace steps 0a and 0b with a single GPT-4o-powered step that dynamically filters question pages by language and groups them into optimal batches. This step also extracts the assignment title and description. Downstream steps remain compatible and legacy methods are removed.

### Steps
1. Implement `_filter_and_group_pages_gpt4o`:
   - Accepts all PDF page images.
   - Uses GPT-4o to:
     - Detect all languages present.
     - If only one language, filter question pages and group into batches.
     - If English and another language, filter English question pages and group into batches.
     - If multiple non-English languages, filter question pages in any one language and group into batches.
     - Dynamically optimize batch sizes for parallel extraction (no fixed batch size).
     - Extract assignment title and description from the document.
     - Return: `{"batches": [[(image, page_number), ...], ...], "title": ..., "description": ...}`
2. Refactor `parse_pdf_images_to_assignment`:
   - Replace calls to `_filter_question_pages` and `_group_pages_into_batches` with `_filter_and_group_pages_gpt4o`.
   - Pass only batches (without title/description) to step 1 extraction.
   - Use extracted title and description from step 0 for normalization.
3. Remove legacy methods: `_filter_question_pages`, `_group_pages_into_batches`, `_find_safe_batch_boundary`.
4. Ensure downstream steps (`_extract_all_content_parallel`, diagram assignment, etc.) work with new batch structure and title/description extraction.
5. Update logging and error handling to reflect new logic and failure modes.

### Further Considerations
1. Confirm prompt design for GPT-4o to handle multi-language logic and batch optimization.
2. Validate that title/description extraction is robust for all supported languages.
3. Ensure step 1 does not duplicate title/description extraction.
