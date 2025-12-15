## Plan: YOLO Diagram Assignment for Relevant Pages

Optimize diagram detection by running YOLO only on pages where questions require diagrams, as identified in Step 1. Assign diagrams to questions by ymin order, leaving unmatched diagrams/questions empty.

### Steps
1. After Step 1, analyze extracted questions to identify which pages have questions requiring diagrams (with saved page numbers).
2. For each such page, run YOLO once to detect all diagrams.
3. For pages with multiple questions needing diagrams, sort detected bounding boxes by confidence
  a) if diagrams >= questions, the first n_question diagrams will be sorted by ymin (topmost first).
  b) if diagrams < questions, all detected diagrams will be sorted by ymin.
4. For pages with single question needing diagram, assign the highest confidence diagram detected on that page.
5. Update question objects with assigned diagram bounding box coordinates.
6. Remove Gemini-specific diagram extraction logic from `_enrich_question` and related code.
7. Make sure that third step i.e. "Generating missing answers and rubrics" gets s3 urls of diagrams from question objects.

### Further Considerations
1. Ensure robust handling for edge cases (no diagrams, extra diagrams, overlapping diagrams).
2. Confirm YOLO model path and inference code are accessible and error-handled in backend.
