# Fast Screenshot Comparison Processor

Visual/screenshot change detection using ultra-fast image comparison algorithms.

## Overview

This processor uses **OpenCV** by default for screenshot comparison, providing **50-100x faster** performance compared to the previous SSIM implementation while still detecting meaningful visual changes.

## Current Features

- **Ultra-fast OpenCV comparison**: cv2.absdiff with Gaussian blur for noise reduction
- **MD5 pre-check**: Fast identical image detection before expensive comparison
- **Configurable sensitivity**: Threshold-based change detection
- **Three-panel diff view**: Previous | Current | Difference (with red highlights)
- **Direct image support**: Works with browser screenshots AND direct image URLs
- **Visual selector support**: Compare specific page regions using CSS/XPath selectors
- **Download images**: Download any of the three comparison images directly from the diff view

## Performance

- **OpenCV (default)**: 50-100x faster than SSIM
- **Large screenshots**: Automatic downscaling for diff visualization (configurable via `MAX_DIFF_HEIGHT`/`MAX_DIFF_WIDTH`)
- **Memory efficient**: Explicit cleanup of large objects for long-running processes
- **JPEG diff images**: Smaller file sizes, faster rendering

## How It Works

1. **Fetch**: Screenshot captured via browser OR direct image URL fetched
2. **MD5 Check**: Quick hash comparison - if identical, skip comparison
3. **Region Selection** (optional): Crop to specific page region if visual selector is configured
4. **OpenCV Comparison**: Fast pixel-level difference detection with Gaussian blur
5. **Change Detection**: Percentage of changed pixels above threshold = change detected
6. **Visualization**: Generate diff image with red-highlighted changed regions

## Architecture

### Default Method: OpenCV

The processor uses OpenCV's `cv2.absdiff()` for ultra-fast pixel-level comparison:

```python
# Convert to grayscale
gray_from = cv2.cvtColor(image_from, cv2.COLOR_RGB2GRAY)
gray_to = cv2.cvtColor(image_to, cv2.COLOR_RGB2GRAY)

# Apply Gaussian blur (reduces noise, controlled by OPENCV_BLUR_SIGMA env var)
gray_from = cv2.GaussianBlur(gray_from, (0, 0), sigma=0.8)
gray_to = cv2.GaussianBlur(gray_to, (0, 0), sigma=0.8)

# Calculate absolute difference
diff = cv2.absdiff(gray_from, gray_to)

# Apply threshold (default: 30)
_, thresh = cv2.threshold(diff, threshold, 255, cv2.THRESH_BINARY)

# Count changed pixels
change_percentage = (changed_pixels / total_pixels) * 100
```

### Optional: Pixelmatch

For users who need better anti-aliasing detection (especially for text-heavy screenshots), **pixelmatch** can be optionally installed:

```bash
pip install pybind11-pixelmatch>=0.1.3
```

**Note**: Pixelmatch uses a C++17 implementation via pybind11 and may have build issues on some platforms (particularly Alpine/musl systems with symbolic link security restrictions). The application will automatically fall back to OpenCV if pixelmatch is not available.

To use pixelmatch instead of OpenCV, set the environment variable:
```bash
COMPARISON_METHOD=pixelmatch
```

#### When to use pixelmatch:
- Screenshots with lots of text and anti-aliasing
- Need to ignore minor font rendering differences between browser versions
- 10-20x faster than SSIM (but slower than OpenCV)

#### When to stick with OpenCV (default):
- General webpage monitoring
- Maximum performance (50-100x faster than SSIM)
- Simple pixel-level change detection
- Avoid build dependencies (Alpine/musl systems)

## Configuration

### Environment Variables

```bash
# Comparison method (opencv or pixelmatch)
COMPARISON_METHOD=opencv  # Default

# OpenCV threshold (0-255, lower = more sensitive)
COMPARISON_THRESHOLD_OPENCV=30  # Default

# Pixelmatch threshold (0-100, mapped to 0-1 scale)
COMPARISON_THRESHOLD_PIXELMATCH=10  # Default

# Gaussian blur sigma for OpenCV (0 = no blur, higher = more blur)
OPENCV_BLUR_SIGMA=0.8  # Default

# Minimum change percentage to trigger detection
OPENCV_MIN_CHANGE_PERCENT=0.1  # Default (0.1%)
PIXELMATCH_MIN_CHANGE_PERCENT=0.1  # Default

# Diff visualization image size limits (pixels)
MAX_DIFF_HEIGHT=8000  # Default
MAX_DIFF_WIDTH=900  # Default
```

### Per-Watch Configuration

- **Comparison Threshold**: Can be configured per-watch in the edit form
  - Very low sensitivity (10) - Only major changes
  - Low sensitivity (20) - Significant changes
  - Medium sensitivity (30) - Moderate changes (default)
  - High sensitivity (50) - Small changes
  - Very high sensitivity (75) - Any visible change

### Visual Selector (Region Comparison)

Use the "Include filters" field with CSS selectors or XPath to compare only specific page regions:

```
.content-area
//div[@id='main']
```

The processor will automatically crop both screenshots to the bounding box of the first matched element.

## Dependencies

### Required
- `opencv-python-headless>=4.8.0.76` - Fast image comparison
- `Pillow (PIL)` - Image loading and manipulation
- `numpy` - Array operations

### Optional
- `pybind11-pixelmatch>=0.1.3` - Alternative comparison method with anti-aliasing detection

## Change Detection Interpretation

- **0%** = Identical images (or below minimum change threshold)
- **0.1-1%** = Minor differences (anti-aliasing, slight rendering differences)
- **1-5%** = Noticeable changes (text updates, small content changes)
- **5-20%** = Significant changes (layout shifts, content additions)
- **>20%** = Major differences (page redesign, large content changes)

## Technical Notes

### Memory Management
```python
# Explicit cleanup for long-running processes
img.close()  # Close PIL Images
buffer.close()  # Close BytesIO buffers
del large_array  # Mark numpy arrays for GC
```

### Diff Image Generation
- Format: JPEG (quality=85, optimized)
- Highlight: Red overlay (50% blend with original)
- Auto-downscaling: Large screenshots downscaled for faster rendering
- Base64 embedded: For direct template rendering

### OpenCV Blur Parameters
The Gaussian blur reduces sensitivity to:
- Font rendering differences
- Anti-aliasing variations
- JPEG compression artifacts
- Minor pixel shifts (1-2 pixels)

Increase `OPENCV_BLUR_SIGMA` to make comparison more tolerant of these differences.

## Comparison: OpenCV vs Pixelmatch vs SSIM

| Feature | OpenCV | Pixelmatch | SSIM (old) |
|---------|--------|------------|------------|
| **Speed** | 50-100x faster | 10-20x faster | Baseline |
| **Anti-aliasing** | Via blur | Built-in detection | Built-in |
| **Text sensitivity** | High | Medium (AA-aware) | Medium |
| **Dependencies** | opencv-python-headless | pybind11-pixelmatch + C++ compiler | scikit-image |
| **Alpine/musl support** | ✅ Yes | ⚠️ Build issues | ✅ Yes |
| **Memory usage** | Low | Low | High |
| **Best for** | General use, max speed | Text-heavy screenshots | Deprecated |

## Migration from SSIM

If you're upgrading from the old SSIM-based processor:

1. **Thresholds are different**: SSIM used 0-1 scale (higher = more similar), OpenCV uses 0-255 pixel difference (lower = more similar)
2. **Default threshold**: Start with 30 for OpenCV, adjust based on your needs
3. **Performance**: Expect dramatically faster comparisons, especially for large screenshots
4. **Accuracy**: OpenCV is more sensitive to pixel-level changes; increase `OPENCV_BLUR_SIGMA` if you're getting false positives

## Future Enhancements

Potential features for future consideration:

- **Change region detection**: Highlight specific areas that changed with bounding boxes
- **Perceptual hashing**: Pre-screening filter for even faster checks
- **Ignore regions**: Exclude specific page areas (ads, timestamps) from comparison
- **Text extraction**: OCR-based text comparison for semantic changes
- **Adaptive thresholds**: Different sensitivity for different page regions

## Resources

- [OpenCV Documentation](https://docs.opencv.org/)
- [pybind11-pixelmatch GitHub](https://github.com/whtsky/pybind11-pixelmatch)
- [Pixelmatch (original JS library)](https://github.com/mapbox/pixelmatch)
