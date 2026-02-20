# Manometer Diagram Solutions

## Problems Identified

1. ✅ **Size**: Images too large (taking full page width)
2. ✅ **Shape**: Not showing U-tube properly - just stacked rectangles like slabs
3. ✅ **Accuracy**: Missing the fundamental U-tube geometry

## Solutions Implemented

### 1. Updated Diagram Agent Prompts

**Changes in diagram_agent.py**:
- Added manometer-specific requirements
- Specified U-tube structure requirements
- Mandated smaller figure sizes: `figsize=(6, 4)` or `(5, 4)` instead of default `(8, 6)`
- Provided example code structure for U-tube manometers

### 2. Key Requirements Now Enforced

```python
# CORRECT - What the AI should generate now:
fig, ax = plt.subplots(figsize=(6, 4))  # Compact size

# Draw U-tube structure:
# - Left vertical tube
# - Bottom horizontal connection
# - Right vertical tube
# - Fluid layers in BOTH tubes
```

## Alternative Libraries & Approaches

### Option 1: **Enhanced Matplotlib** (RECOMMENDED - Already Implemented)

**Pros**:
- ✅ Already integrated
- ✅ Precise control over shapes
- ✅ Can draw proper U-tubes with patches.Rectangle
- ✅ Good for technical diagrams
- ✅ Supports labels, dimensions, colors

**Cons**:
- ⚠️ Requires detailed code generation
- ⚠️ AI must generate correct geometry

**Usage**: Use `matplotlib.patches` to draw:
- U-tube outline (two rectangles + connection)
- Fluid layers (colored rectangles)
- Labels and dimensions (text + arrows)

**Example**:
```python
import matplotlib.pyplot as plt
import matplotlib.patches as patches

fig, ax = plt.subplots(figsize=(6, 4))
ax.set_xlim(0, 1)
ax.set_ylim(0, 1)
ax.axis('off')

# Left tube
ax.add_patch(patches.Rectangle((0.2, 0.3), 0.15, 0.6,
                                fill=False, edgecolor='black', linewidth=2))
# Bottom connection
ax.add_patch(patches.Rectangle((0.2, 0.25), 0.5, 0.05,
                                fill=False, edgecolor='black', linewidth=2))
# Right tube
ax.add_patch(patches.Rectangle((0.55, 0.3), 0.15, 0.6,
                                fill=False, edgecolor='black', linewidth=2))

# Fluid layers (mercury, oil, water in each tube)
# Left tube fluids
ax.add_patch(patches.Rectangle((0.2, 0.3), 0.15, 0.2,
                                fill=True, facecolor='gray', alpha=0.7, label='Mercury'))
ax.add_patch(patches.Rectangle((0.2, 0.5), 0.15, 0.15,
                                fill=True, facecolor='orange', alpha=0.7, label='Oil'))
ax.add_patch(patches.Rectangle((0.2, 0.65), 0.15, 0.25,
                                fill=True, facecolor='blue', alpha=0.7, label='Water'))

# Right tube fluids (different heights)
ax.add_patch(patches.Rectangle((0.55, 0.3), 0.15, 0.25,
                                fill=True, facecolor='gray', alpha=0.7))
ax.add_patch(patches.Rectangle((0.55, 0.55), 0.15, 0.1,
                                fill=True, facecolor='orange', alpha=0.7))
ax.add_patch(patches.Rectangle((0.55, 0.65), 0.15, 0.2,
                                fill=True, facecolor='blue', alpha=0.7))

# Labels
ax.text(0.1, 0.4, 'Mercury\n0.2 m', fontsize=9, ha='center')
ax.text(0.1, 0.575, 'Oil\n0.3 m', fontsize=9, ha='center')
ax.text(0.1, 0.775, 'Water\n0.5 m', fontsize=9, ha='center')

ax.legend(loc='upper right')
plt.title('U-tube Manometer with Three Fluids')
plt.savefig('output.png', dpi=100, bbox_inches='tight')
```

---

### Option 2: **Plotly** (Interactive, but adds dependency)

**Pros**:
- ✅ Modern, interactive diagrams
- ✅ Better for complex shapes
- ✅ Can export static images
- ✅ Good annotation support

**Cons**:
- ❌ Requires new dependency: `plotly` + `kaleido`
- ❌ Larger file sizes
- ❌ Not currently integrated

**When to use**: If you want interactive diagrams (zoom, hover details)

---

### Option 3: **SVG with Python** (Clean vector graphics)

**Pros**:
- ✅ Perfect for geometric shapes
- ✅ Scalable (vector format)
- ✅ Clean, crisp diagrams
- ✅ Easy to define shapes programmatically

**Cons**:
- ❌ Requires `svgwrite` library
- ❌ Need `cairosvg` to convert to PNG
- ❌ Not currently integrated

**Example**:
```python
import svgwrite

dwg = svgwrite.Drawing('manometer.svg', size=('400px', '600px'))

# Draw U-tube
dwg.add(dwg.rect((50, 100), (80, 400), stroke='black', fill='none'))  # Left
dwg.add(dwg.rect((50, 500), (200, 50), stroke='black', fill='none'))  # Bottom
dwg.add(dwg.rect((170, 100), (80, 400), stroke='black', fill='none')) # Right

# Add fluid layers...
dwg.save()
```

---

### Option 4: **PIL/Pillow** (Direct pixel manipulation)

**Pros**:
- ✅ Already installed (used in diagram_generator.py)
- ✅ Simple rectangle drawing
- ✅ Good for basic shapes

**Cons**:
- ❌ Harder to get precise technical diagrams
- ❌ Not as clean as matplotlib
- ❌ More manual work for labels/text

**When to use**: Simple block diagrams only

---

### Option 5: **TikZ/LaTeX** (Academic quality)

**Pros**:
- ✅ Publication-quality diagrams
- ✅ Perfect for technical documents
- ✅ Very precise control

**Cons**:
- ❌ Requires LaTeX installation
- ❌ Slower rendering
- ❌ Steep learning curve
- ❌ Not suitable for dynamic generation

**When to use**: Only if generating LaTeX documents directly

---

### Option 6: **Manim** (Animation library)

**Pros**:
- ✅ Beautiful technical diagrams
- ✅ Great for educational content
- ✅ Can create animations

**Cons**:
- ❌ Overkill for static diagrams
- ❌ Heavy dependency
- ❌ Slow rendering

**When to use**: If you want video explanations, not static images

---

### Option 7: **DALL-E 3 / AI Generation** (Already available)

**Pros**:
- ✅ Already integrated (dalle_tool)
- ✅ Can generate any type of diagram
- ✅ No code needed

**Cons**:
- ❌ Less precise than code-based
- ❌ Can't guarantee exact dimensions/values
- ❌ More expensive per diagram
- ❌ Not ideal for technical accuracy

**Current status**: Available but discouraged in prompts for technical diagrams

---

## Recommendations

### Immediate Fix (No New Dependencies)

**Use Enhanced Matplotlib** (already done):
1. ✅ Updated prompts to require U-tube structure
2. ✅ Specified smaller figure sizes
3. ✅ Provided example code structure

**What to do now**:
1. Regenerate your manometer assignment
2. The AI should now create proper U-tube diagrams
3. Images will be smaller and fit better in PDFs

---

### If Current Solution Still Doesn't Work Well

**Add SVG Support** (Best quality for technical diagrams):

1. Install dependencies:
```bash
pip install svgwrite cairosvg
```

2. The system already has SVG rendering in `diagram_generator.py` (line 279-307)

3. Add SVG tool to `diagram_tools.py`:
```python
{
    "type": "function",
    "function": {
        "name": "svg_tool",
        "description": "Generate technical diagrams using SVG markup",
        "parameters": {
            "type": "object",
            "properties": {
                "svg_markup": {"type": "string", "description": "Complete SVG XML"}
            }
        }
    }
}
```

---

### Long-term Recommendation

**Hybrid Approach**:
1. **Matplotlib** for: plots, graphs, circuits (via schemdraw)
2. **SVG** for: geometric diagrams like manometers, pipes, beams
3. **NetworkX** for: trees, graphs, algorithms
4. **DALL-E 3** as fallback only when code-based methods fail

This gives best quality + accuracy for each diagram type.

---

## Testing Your Fix

Regenerate with this prompt:
```
Generate 2 questions on U-tube manometer with three fluids (water, mercury, oil)
```

Expected result:
- ✅ Smaller images (6x4 inches instead of 8x6+)
- ✅ Proper U-tube shape (two tubes connected at bottom)
- ✅ Fluid layers visible in both tubes
- ✅ Clear labels with heights

---

## Files Modified

1. `/src/utils/diagram_agent.py`
   - Added manometer-specific requirements (lines 102-141)
   - Specified smaller figure sizes
   - Provided U-tube code example

---

## Next Steps

1. **Test the current fix**: Regenerate manometer questions
2. **If still not good**: Add SVG tool (15-20 min work)
3. **If need interactive**: Consider Plotly (requires new dependency)

The most practical solution is **Option 1 (Enhanced Matplotlib)** which is already implemented. Give it a try first!
