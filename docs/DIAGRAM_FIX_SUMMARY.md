# Diagram Generation Fix - Summary

## Problem Identified

When generating questions on manometer, images were not loading because:

1. **Question Generation Phase**: The AI generated questions with `hasDiagram: true` and diagram metadata (captions, page numbers)
2. **Diagram Analysis Phase**: In CONSERVATIVE mode (`diagram-analysis: false`), the agent rejected diagram generation for most questions
3. **Result**: Questions had `hasDiagram: true` but no actual S3 URL, causing broken image references in the frontend

## Changes Made

### 1. Diagram Metadata Cleanup (assignment_generator.py)

**Added**: `_cleanup_diagram_metadata()` method that:
- Removes `hasDiagram` flags from questions without actual S3 URLs
- Cleans up diagram metadata recursively (handles subquestions)
- Runs automatically after diagram analysis
- Prevents broken image references in the frontend

**Location**: Lines 127-178 in `src/utils/assignment_generator.py`

### 2. Intelligent Diagram Mode (diagram_agent.py)

**Changed**: Diagram agent behavior from CONSERVATIVE/GENEROUS to INTELLIGENT approach:

#### Previous Behavior:
- `diagram-analysis: true` → GENEROUS mode (aim for 33%+ diagrams)
- `diagram-analysis: false` → CONSERVATIVE mode (only when explicitly required)

#### New Behavior:
- **INTELLIGENT mode for all questions**: Always evaluates if diagrams add educational value
- `diagram-analysis: true` → Aims for 33%+ target
- `diagram-analysis: false` → Quality-focused, no strict percentage target
- Both modes now generate diagrams when they help students visualize problems

**Key Improvements**:

1. **Professor's Judgment**: Agent thinks like a teacher - "Would I draw this on the board?"

2. **Broader Diagram Support**:
   - Physics: Manometers, fluid systems, force diagrams
   - Electrical: Circuits, I-V curves, amplifiers
   - Mechanical: Beam diagrams, pressure systems
   - Data structures: Trees, graphs, networks

3. **Hints from Original LLM**:
   - If the question generator suggests a diagram (caption, page_number), the agent treats it as a strong hint
   - Improves coordination between generation and analysis phases

4. **Smart Criteria**:
   - ✅ Physical setups with spatial relationships
   - ✅ Multiple components/fluids with interactions
   - ✅ Numerical values assigned to specific system parts
   - ❌ Pure theory, definitions, abstract concepts

**Location**: Lines 25-120 in `src/utils/diagram_agent.py`

### 3. Enhanced Analysis Prompt

**Updated**: Question analysis to include:
- Information about original LLM's diagram suggestions
- Clear mode description (GENEROUS vs INTELLIGENT)
- Strong hint when diagram metadata already exists

**Location**: Lines 142-189 in `src/utils/diagram_agent.py`

## Example: Manometer Questions

### Before Fix:
```
Question: "Calculate pressure in a manometer with three fluids..."
hasDiagram: true
diagram: { caption: "Manometer with three fluids", page_number: 1 }
         ❌ No s3_url → Broken image in frontend
```

### After Fix:
```
Question: "For the manometer shown below with water, mercury, and oil..."
hasDiagram: true
diagram: {
  s3_url: "https://s3.../manometer.png",
  s3_key: "assignments/123/diagram_0.png",
  caption: "Manometer with three fluid columns"
}
         ✅ Actual diagram generated and displayed
```

OR if diagram not needed:
```
Question: "Explain the working principle of manometers"
hasDiagram: false
diagram: null
         ✅ Text-only question, no broken images
```

## Testing

Created test suite in `test_diagram_cleanup.py`:
- ✅ Verifies cleanup removes metadata without S3 URLs
- ✅ Preserves diagrams with valid S3 URLs
- ✅ Handles nested subquestions correctly
- ✅ All tests passing

## Impact

1. **Fixed broken images**: Questions without diagrams no longer show broken image placeholders
2. **More diagrams generated**: Intelligent mode generates diagrams when they add value, even without `diagram-analysis: true`
3. **Better coordination**: Original LLM suggestions are now used as hints for diagram agent
4. **Consistent behavior**: Same intelligent evaluation regardless of diagram-analysis setting

## Next Steps

When you regenerate assignments:
1. Questions that benefit from diagrams will get them automatically
2. Questions that don't need diagrams won't have broken image references
3. Manometer questions with complex setups will get appropriate diagrams showing fluid columns, heights, and pressures

## Files Modified

1. `/src/utils/assignment_generator.py`
   - Added `_cleanup_diagram_metadata()` method
   - Added cleanup call after diagram analysis

2. `/src/utils/diagram_agent.py`
   - Replaced CONSERVATIVE mode with INTELLIGENT mode
   - Enhanced system prompt with broader examples
   - Added LLM hint detection in analysis prompt
   - Updated logging messages

3. `/test_diagram_cleanup.py` (new)
   - Test suite for cleanup functionality
