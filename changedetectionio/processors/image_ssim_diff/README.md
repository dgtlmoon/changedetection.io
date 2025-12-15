# SSIM Image Comparison Processor

Visual/screenshot change detection using Structural Similarity Index (SSIM) algorithm.

## Current Features

- **SSIM-based comparison**: Robust to antialiasing and minor rendering differences
- **MD5 pre-check**: Fast identical image detection before expensive SSIM calculation
- **Configurable sensitivity**: Low/Medium/High/Very High threshold levels
- **Three-panel diff view**: Previous | Current | Difference (with red highlights)
- **Direct image support**: Works with browser screenshots AND direct image URLs (JPEG, PNG, etc.)

## Architecture

The processor uses:
- `scikit-image` for SSIM calculation and image analysis
- `Pillow (PIL)` for image loading and manipulation
- `numpy` for array operations

## How It Works

1. **Fetch**: Screenshot captured via browser OR direct image URL fetched
2. **MD5 Check**: Quick hash comparison - if identical, skip SSIM (raises `checksumFromPreviousCheckWasTheSame`)
3. **SSIM Calculation**: Structural similarity between previous and current image
4. **Change Detection**: Score below threshold = change detected
5. **Visualization**: Generate diff image with red-highlighted changed regions

## SSIM Score Interpretation

- **1.0** = Identical images
- **0.95-1.0** = Very similar (minor differences, antialiasing)
- **0.90-0.95** = Noticeable differences
- **0.85-0.90** = Significant differences
- **<0.85** = Major differences

## Available Libraries & Capabilities

We have access to powerful image analysis capabilities through scikit-image and other libraries. Below are high-value features that could add real user value:

### 1. 🚀 Perceptual Hashing (pHash)

**What**: Ultra-fast similarity check based on overall image perception
**Speed**: Microseconds vs SSIM milliseconds
**Use Case**: Pre-screening filter before expensive SSIM
**Value**: "Probably unchanged" quick check for high-frequency monitoring

**⚠️ IMPORTANT LIMITATIONS:**
- **Will MISS small text changes** (e.g., "Sale ends Monday" → "Sale ends Tuesday")
- Only detects major visual changes (layout, large regions, color shifts)
- Works by reducing image to ~8x8 pixels and comparing overall structure
- Small changes (<5% of image) are invisible to pHash

**Good for detecting:**
- Layout/design changes
- Major content additions/removals
- Color scheme changes
- Page structure changes

**Bad for detecting:**
- Text edits (few letters changed)
- Price changes in small text
- Date/timestamp updates
- Small icon changes

```python
from skimage.feature import perceptual_hash
# Generate hash of image (reduces to 8x8 structure)
hash1 = perceptual_hash(image1)
hash2 = perceptual_hash(image2)
# Compare hashes (Hamming distance)
similarity = (hash1 == hash2).sum() / hash1.size
```

**Implementation Idea**: Use pHash only as negative filter:
- pHash identical → Definitely unchanged, skip SSIM ✓
- pHash different → Run SSIM (might be false positive, need accurate check)
- **Never** skip SSIM based on "pHash similar" - could miss important changes!

**Alternative: MD5 is better for our use case**
- Current MD5 check: Detects ANY change (including 1 pixel)
- pHash advantage: Would handle JPEG recompression, minor rendering differences
- But we care about those differences! So MD5 is actually more appropriate.

---

### 2. 📍 Change Region Detection

**What**: Identify WHICH regions changed, not just "something changed"
**Use Case**: Show users exactly what changed on the page
**Value**: Actionable insights - "Price changed in top-right" vs "Something changed somewhere"

```python
from skimage import segmentation, measure
from skimage.filters import threshold_otsu

# Get binary mask of changed regions from SSIM map
threshold = threshold_otsu(diff_map)
changed_regions = diff_map < threshold

# Find connected regions
labels = measure.label(changed_regions)
regions = measure.regionprops(labels)

# For each changed region, get bounding box
for region in regions:
    minr, minc, maxr, maxc = region.bbox
    # Draw rectangle on diff image
```

**Implementation Idea**: Add bounding boxes to diff visualization showing changed regions with size metrics

---

### 3. 🔥 Structural Similarity Heatmap

**What**: Per-pixel similarity map showing WHERE differences are
**Use Case**: Visual heatmap overlay - blue=same, red=different
**Value**: Intuitive visualization of change distribution

```python
from skimage.metrics import structural_similarity as ssim
import matplotlib.pyplot as plt

# Calculate SSIM with full output (we already do this!)
ssim_score, diff_map = ssim(img1, img2, full=True, ...)

# Convert to heatmap
heatmap = plt.cm.RdYlBu(diff_map)  # Red=different, Blue=same
```

**Implementation Idea**: Add heatmap view as alternative to red-highlight diff

---

### 4. 🏗️ Edge/Structure Detection

**What**: Compare page structure/layout vs content changes
**Use Case**: Detect layout changes separately from text updates
**Value**: "Alert on redesigns" vs "Ignore content updates"

```python
from skimage import filters, feature

# Extract edges/structure from both images
edges1 = filters.sobel(img1)
edges2 = filters.sobel(img2)

# Compare structural similarity of edges only
structure_ssim = ssim(edges1, edges2, ...)
content_ssim = ssim(img1, img2, ...)

# Separate alerts for structure vs content changes
```

**Implementation Idea**: Add "Structure-only" mode that compares layouts, ignoring text/content changes

---

### 5. 🎨 Color Histogram Comparison

**What**: Fast color distribution analysis
**Use Case**: Detect theme/branding changes, site redesigns
**Value**: "Color scheme changed" alert

```python
from skimage import exposure

# Compare color histograms
hist1 = exposure.histogram(img1)
hist2 = exposure.histogram(img2)

# Calculate histogram similarity
histogram_diff = np.sum(np.abs(hist1 - hist2))
```

**Implementation Idea**: Add "Color similarity" metric alongside SSIM score

---

### 6. 🎯 Feature Matching

**What**: Detect specific visual elements (logos, buttons, icons)
**Use Case**: "Alert if logo disappears" or "Track button position"
**Value**: Semantic change detection

```python
from skimage.feature import ORB, match_descriptors

# Detect features (corners, blobs, etc.)
detector = ORB()
keypoints1 = detector.detect_and_extract(img1)
keypoints2 = detector.detect_and_extract(img2)

# Match features between images
matches = match_descriptors(keypoints1, keypoints2)

# Check if specific features disappeared
```

**Implementation Idea**: Let users define "watch zones" for specific elements

---

### 7. 📐 Region Properties & Metrics

**What**: Measure changed region sizes, positions, shapes
**Use Case**: Quantify "how much changed"
**Value**: "Alert only if >10% of page changed" rules

```python
from skimage import measure

# Get properties of changed regions
regions = measure.regionprops(labeled_changes)

for region in regions:
    area = region.area
    centroid = region.centroid
    bbox = region.bbox

    # Calculate percentage of image changed
    percent_changed = (area / total_pixels) * 100
```

**Implementation Idea**: Add threshold options:
- "Alert if >X% of image changed"
- "Ignore changes smaller than X pixels"

---

### 8. 🔲 Region Masking / Exclusion Zones

**What**: Exclude specific regions from comparison
**Use Case**: Ignore ads, timestamps, dynamic content
**Value**: Reduce false positives from expected changes

```python
# User defines mask regions (top banner, sidebar ads, etc.)
mask = np.ones_like(img1)
mask[0:100, :] = 0  # Ignore top 100 pixels (ads)
mask[:, -200:] = 0  # Ignore right 200 pixels (sidebar)

# Apply mask to SSIM calculation
masked_ssim = ssim(img1, img2, mask=mask, ...)
```

**Implementation Idea**: Add UI for drawing exclusion zones on reference screenshot

---

### 9. 🔄 Image Alignment

**What**: Handle slight position shifts, scrolling, zoom changes
**Use Case**: Compare screenshots that aren't pixel-perfect aligned
**Value**: Robust to viewport changes, scrolling

```python
from skimage.registration import phase_cross_correlation

# Detect shift between images
shift, error, diffphase = phase_cross_correlation(img1, img2)

# Align images before comparison
from scipy.ndimage import shift as nd_shift
img2_aligned = nd_shift(img2, shift)

# Now compare aligned images
```

**Implementation Idea**: Auto-align screenshots before SSIM to handle scroll/zoom

---

### 10. 🔍 Local Binary Patterns (Texture Analysis)

**What**: Texture-based comparison
**Use Case**: Focus on content regions, ignore ad texture changes
**Value**: Distinguish between content and decorative elements

```python
from skimage.feature import local_binary_pattern

# Extract texture features
lbp1 = local_binary_pattern(img1, P=8, R=1)
lbp2 = local_binary_pattern(img2, P=8, R=1)

# Compare texture patterns
texture_diff = ssim(lbp1, lbp2, ...)
```

**Implementation Idea**: "Content-aware" mode that focuses on text/content areas

---

## Priority Features for Implementation

Based on user value and implementation complexity:

### High Priority
1. **Change Region Detection** - Show WHERE changes occurred with bounding boxes
2. **Region Masking** - Let users exclude zones (ads, timestamps, dynamic content)
3. **Region Size Thresholds** - "Alert only if >X% changed"

### Medium Priority
4. **Heatmap Visualization** - Alternative diff view (better than red highlights)
5. **Color Histogram** - Quick color scheme change detection
6. **Image Alignment** - Handle scroll/zoom differences

### Low Priority (Advanced)
7. **Structure-only Mode** - Layout change detection vs content
8. **Feature Matching** - Semantic element tracking ("did logo disappear?")
9. **Texture Analysis** - Content-aware comparison
10. **Perceptual Hash** - Fast pre-check (but MD5 is already fast and more accurate)

### Not Recommended
- **Perceptual Hash as primary check** - Will miss small text changes that users care about
- Current MD5 + SSIM approach is better for monitoring use cases

## Implementation Considerations

- **Performance**: Some features (pHash) are faster, others (feature matching) slower than SSIM
- **Memory**: Keep cleanup patterns for GC (close PIL images, del arrays)
- **UI Complexity**: Balance power features with ease of use
- **False Positives**: More sensitivity = more alerts, need good defaults

## Future Ideas

- **OCR Integration**: Extract and compare text from screenshots
- **Object Detection**: Detect when specific objects appear/disappear
- **Machine Learning**: Learn what changes matter to the user
- **Anomaly Detection**: Detect unusual changes vs typical patterns

---

## Technical Notes

### Current Memory Management
- Explicit `.close()` on PIL Images
- `del` on numpy arrays after use
- BytesIO `.close()` after encoding
- Critical for long-running processes

### SSIM Parameters
```python
ssim_score = ssim(
    img1, img2,
    channel_axis=-1,  # RGB images (last dimension is color)
    data_range=255,   # 8-bit images
    full=True         # Return diff map for visualization
)
```

### Diff Image Generation
- Currently: JPEG quality=75 for smaller file sizes
- Red highlight: 50% blend with original image
- Could add configurable highlight colors or intensity
