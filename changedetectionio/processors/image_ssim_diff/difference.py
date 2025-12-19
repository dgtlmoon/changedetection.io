"""
Screenshot diff visualization for fast image comparison processor.

Generates side-by-side comparison with red-highlighted differences using
OpenCV for fast rendering (10-100x faster than SSIM).
"""

import os
import json
import io
import time
from loguru import logger
from . import DEFAULT_COMPARISON_THRESHOLD_OPENCV

# Maximum dimensions for diff visualization (can be overridden via environment variable)
# Large screenshots don't need full resolution for visual inspection
MAX_DIFF_HEIGHT = int(os.getenv('MAX_DIFF_HEIGHT', '8000'))
MAX_DIFF_WIDTH = int(os.getenv('MAX_DIFF_WIDTH', '900'))


def _resize_for_diff(img, max_height=MAX_DIFF_HEIGHT, max_width=MAX_DIFF_WIDTH):
    from PIL import Image

    """
    Downscale image if too large for faster diff visualization.

    Users don't need pixel-perfect diffs at 20000px resolution.
    Downscaling to 2000px is 100x faster and still shows all visible changes.

    Args:
        img: PIL Image
        max_height: Maximum height in pixels
        max_width: Maximum width in pixels

    Returns:
        PIL Image (resized if needed)
    """
    if img.height > max_height or img.width > max_width:
        # Calculate scaling factor to fit within max dimensions
        height_ratio = max_height / img.height if img.height > max_height else 1.0
        width_ratio = max_width / img.width if img.width > max_width else 1.0
        ratio = min(height_ratio, width_ratio)

        new_size = (int(img.width * ratio), int(img.height * ratio))
        logger.debug(f"Downscaling diff visualization: {img.size} -> {new_size} ({ratio*100:.1f}% scale)")
        return img.resize(new_size, Image.Resampling.LANCZOS)

    return img


def calculate_change_percentage_opencv(img_bytes_from, img_bytes_to, threshold=30):
    """
    Calculate only the change percentage using OpenCV (lightweight version).

    This is optimized to calculate only the percentage without keeping the diff mask,
    reducing memory usage when we only need the percentage for display.

    Args:
        img_bytes_from: Previous screenshot (bytes)
        img_bytes_to: Current screenshot (bytes)
        threshold: Pixel difference threshold (0-255)

    Returns:
        float: change_percentage
    """
    from PIL import Image
    import numpy as np
    import cv2

    buf_from = io.BytesIO(img_bytes_from)
    buf_to = io.BytesIO(img_bytes_to)
    img_from = Image.open(buf_from)
    img_to = Image.open(buf_to)

    # Ensure images are the same size
    if img_from.size != img_to.size:
        img_from = img_from.resize(img_to.size, Image.Resampling.LANCZOS)

    # Downscale for faster calculation
    img_from = _resize_for_diff(img_from)
    img_to = _resize_for_diff(img_to)

    # Convert to numpy arrays
    arr_from = np.array(img_from)
    arr_to = np.array(img_to)

    # Convert to grayscale
    if len(arr_from.shape) == 3:
        gray_from = cv2.cvtColor(arr_from, cv2.COLOR_RGB2GRAY)
        gray_to = cv2.cvtColor(arr_to, cv2.COLOR_RGB2GRAY)
    else:
        gray_from = arr_from
        gray_to = arr_to

    # Optional Gaussian blur to reduce noise
    blur_sigma = float(os.getenv("OPENCV_BLUR_SIGMA", "0.8"))
    if blur_sigma > 0:
        gray_from = cv2.GaussianBlur(gray_from, (0, 0), blur_sigma)
        gray_to = cv2.GaussianBlur(gray_to, (0, 0), blur_sigma)

    # Calculate absolute difference
    diff = cv2.absdiff(gray_from, gray_to)

    # Apply threshold to create binary mask
    _, diff_mask = cv2.threshold(diff, threshold, 255, cv2.THRESH_BINARY)

    # Calculate change percentage
    changed_pixels = np.count_nonzero(diff_mask)
    total_pixels = diff_mask.size
    change_percentage = (changed_pixels / total_pixels) * 100

    # Aggressive memory cleanup - delete everything before returning
    img_from.close()
    img_to.close()
    buf_from.close()
    buf_to.close()
    del arr_from, arr_to, gray_from, gray_to, diff, diff_mask

    return float(change_percentage)


def calculate_diff_opencv(img_bytes_from, img_bytes_to, threshold=30):
    """
    Calculate image difference using OpenCV cv2.absdiff.

    This is the fastest method for diff visualization.

    Args:
        img_bytes_from: Previous screenshot (bytes)
        img_bytes_to: Current screenshot (bytes)
        threshold: Pixel difference threshold (0-255)

    Returns:
        tuple: (change_percentage, diff_mask) where diff_mask is a 2D numpy binary mask
    """
    # Load images from BytesIO buffers
    from PIL import Image
    import numpy as np
    import cv2

    buf_from = io.BytesIO(img_bytes_from)
    buf_to = io.BytesIO(img_bytes_to)
    img_from = Image.open(buf_from)
    img_to = Image.open(buf_to)

    # Ensure images are the same size
    if img_from.size != img_to.size:
        img_from = img_from.resize(img_to.size, Image.Resampling.LANCZOS)

    # Downscale large images for faster diff visualization
    # A 20000px tall screenshot doesn't need full resolution for visual inspection
    img_from = _resize_for_diff(img_from)
    img_to = _resize_for_diff(img_to)

    # Convert to numpy arrays
    arr_from = np.array(img_from)
    arr_to = np.array(img_to)

    # Convert to grayscale
    if len(arr_from.shape) == 3:
        gray_from = cv2.cvtColor(arr_from, cv2.COLOR_RGB2GRAY)
        gray_to = cv2.cvtColor(arr_to, cv2.COLOR_RGB2GRAY)
    else:
        gray_from = arr_from
        gray_to = arr_to

    # Optional Gaussian blur to reduce noise
    blur_sigma = float(os.getenv("OPENCV_BLUR_SIGMA", "0.8"))
    if blur_sigma > 0:
        gray_from = cv2.GaussianBlur(gray_from, (0, 0), blur_sigma)
        gray_to = cv2.GaussianBlur(gray_to, (0, 0), blur_sigma)

    # Calculate absolute difference
    diff = cv2.absdiff(gray_from, gray_to)

    # Apply threshold to create binary mask
    _, diff_mask = cv2.threshold(diff, threshold, 255, cv2.THRESH_BINARY)

    # Calculate change percentage
    changed_pixels = np.count_nonzero(diff_mask)
    total_pixels = diff_mask.size
    change_percentage = (changed_pixels / total_pixels) * 100

    # Explicit memory cleanup - close images and buffers, delete large arrays
    img_from.close()
    img_to.close()
    buf_from.close()
    buf_to.close()
    del arr_from, arr_to, gray_from, gray_to, diff

    return float(change_percentage), diff_mask


def generate_diff_image_opencv(img_bytes_to, diff_mask):
    """
    Generate a difference image with red highlights using OpenCV.

    This is the fastest method for generating diff visualization.

    Args:
        img_bytes_to: Current screenshot (bytes)
        diff_mask: Binary mask of changed pixels (2D numpy array)

    Returns:
        bytes: PNG image with red highlights on changed pixels
    """
    # Load current image as base from BytesIO buffer
    import numpy as np
    from PIL import Image
    import cv2

    buf_to = io.BytesIO(img_bytes_to)
    img_to = Image.open(buf_to)

    # Downscale for faster diff visualization
    img_to = _resize_for_diff(img_to)

    # Convert to RGB
    if img_to.mode != 'RGB':
        img_to = img_to.convert('RGB')

    result_array = np.array(img_to)

    # Ensure mask is same size as image
    if diff_mask.shape != result_array.shape[:2]:
        diff_mask = cv2.resize(diff_mask, (result_array.shape[1], result_array.shape[0]))

    # Create boolean mask
    changed_mask = diff_mask > 0

    # Apply red highlight where mask is True (50% blend)
    result_array[changed_mask] = (
        result_array[changed_mask] * 0.5 + np.array([255, 0, 0]) * 0.5
    ).astype(np.uint8)

    # Convert back to PIL Image
    diff_img = Image.fromarray(result_array.astype(np.uint8))

    # Save to bytes as JPEG (smaller and faster than PNG for diff visualization)
    buf = io.BytesIO()
    diff_img.save(buf, format='JPEG', quality=85, optimize=True)
    diff_bytes = buf.getvalue()

    # Explicit memory cleanup - close files and buffers, delete large objects
    buf.close()
    buf_to.close()
    diff_img.close()
    img_to.close()
    del result_array, changed_mask, diff_mask

    return diff_bytes


def get_asset(asset_name, watch, datastore, request):
    """
    Get processor-specific binary assets for streaming.

    This function supports serving images as separate HTTP responses instead
    of embedding them as base64 in the HTML template, solving memory issues
    with large screenshots.

    Supported assets:
    - 'before': The previous/from screenshot
    - 'after': The current/to screenshot
    - 'rendered_diff': The generated diff visualization with red highlights

    Args:
        asset_name: Name of the asset to retrieve ('before', 'after', 'rendered_diff')
        watch: Watch object
        datastore: Datastore object
        request: Flask request (for from_version/to_version query params)

    Returns:
        tuple: (binary_data, content_type, cache_control_header) or None if not found
    """
    # Get version parameters from query string (same as render() does)
    versions = list(watch.history.keys())

    if len(versions) < 2:
        return None

    from_version = request.args.get('from_version', versions[-2] if len(versions) >= 2 else versions[0])
    to_version = request.args.get('to_version', versions[-1])

    # Validate versions exist
    if from_version not in versions:
        from_version = versions[-2] if len(versions) >= 2 else versions[0]
    if to_version not in versions:
        to_version = versions[-1]

    try:
        if asset_name == 'before':
            # Return the 'from' screenshot
            img_bytes = watch.get_history_snapshot(timestamp=from_version)

            # Optionally draw bounding box if configured
            img_bytes = _apply_bounding_box_if_configured(img_bytes, watch, datastore)

            return (img_bytes, 'image/png', 'public, max-age=3600')

        elif asset_name == 'after':
            # Return the 'to' screenshot
            img_bytes = watch.get_history_snapshot(timestamp=to_version)

            # Optionally draw bounding box if configured
            img_bytes = _apply_bounding_box_if_configured(img_bytes, watch, datastore)

            return (img_bytes, 'image/png', 'public, max-age=3600')

        elif asset_name == 'rendered_diff':
            # Generate the diff visualization on-demand using OpenCV
            img_bytes_from = watch.get_history_snapshot(timestamp=from_version)
            img_bytes_to = watch.get_history_snapshot(timestamp=to_version)

            # Get threshold
            threshold = watch.get('comparison_threshold')
            if not threshold or threshold == '':
                threshold = datastore.data['settings']['application'].get('comparison_threshold', DEFAULT_COMPARISON_THRESHOLD_OPENCV)

            try:
                threshold = float(threshold)
            except (ValueError, TypeError):
                threshold = 30.0

            # Generate diff using OpenCV
            _, diff_mask = calculate_diff_opencv(img_bytes_from, img_bytes_to, threshold)
            diff_image_bytes = generate_diff_image_opencv(img_bytes_to, diff_mask)
            del diff_mask

            # Clean up source images
            del img_bytes_from, img_bytes_to

            # Optionally draw bounding box on diff image if configured
            diff_image_bytes = _apply_bounding_box_to_diff(diff_image_bytes, watch, datastore)

            return (diff_image_bytes, 'image/jpeg', 'public, max-age=300')

        else:
            # Unknown asset
            return None

    except Exception as e:
        logger.error(f"Failed to get asset '{asset_name}': {e}")
        return None


def _apply_bounding_box_if_configured(img_bytes, watch, datastore):
    """
    Apply blue bounding box to image if configured in processor settings.

    Args:
        img_bytes: Image bytes (PNG)
        watch: Watch object
        datastore: Datastore object

    Returns:
        Image bytes (possibly with bounding box drawn)
    """
    try:
        from changedetectionio import processors
        processor_instance = processors.difference_detection_processor(datastore, watch.get('uuid'))
        processor_name = watch.get('processor', 'default')
        config_filename = f'{processor_name}.json'
        processor_config = processor_instance.get_extra_watch_config(config_filename)
        bounding_box = processor_config.get('bounding_box') if processor_config else None

        if bounding_box:
            parts = [int(p.strip()) for p in bounding_box.split(',')]
            if len(parts) == 4:
                from PIL import Image, ImageDraw

                img_pil = Image.open(io.BytesIO(img_bytes))
                draw = ImageDraw.Draw(img_pil)
                x, y, width, height = parts

                # Draw blue rectangle (3px border)
                for offset in range(3):
                    draw.rectangle(
                        [x + offset, y + offset, x + width - offset, y + height - offset],
                        outline='blue'
                    )

                buf = io.BytesIO()
                img_pil.save(buf, format='PNG')
                img_bytes = buf.getvalue()
                img_pil.close()
                buf.close()
    except Exception as e:
        logger.warning(f"Failed to draw bounding box: {e}")

    return img_bytes


def _apply_bounding_box_to_diff(diff_bytes, watch, datastore):
    """
    Apply blue bounding box to diff image if configured, accounting for scaling.

    Args:
        diff_bytes: Diff image bytes (JPEG)
        watch: Watch object
        datastore: Datastore object

    Returns:
        Image bytes (possibly with bounding box drawn)
    """
    try:
        from changedetectionio import processors
        processor_instance = processors.difference_detection_processor(datastore, watch.get('uuid'))
        processor_name = watch.get('processor', 'default')
        config_filename = f'{processor_name}.json'
        processor_config = processor_instance.get_extra_watch_config(config_filename)
        bounding_box = processor_config.get('bounding_box') if processor_config else None

        if bounding_box:
            parts = [int(p.strip()) for p in bounding_box.split(',')]
            if len(parts) == 4:
                from PIL import Image, ImageDraw

                # Load original "to" image to get original dimensions
                versions = list(watch.history.keys())
                to_version = versions[-1]
                img_to_bytes = watch.get_history_snapshot(timestamp=to_version)
                img_to_pil = Image.open(io.BytesIO(img_to_bytes))
                original_width = img_to_pil.width
                original_height = img_to_pil.height
                img_to_pil.close()

                # Load diff image
                img_diff_pil = Image.open(io.BytesIO(diff_bytes))

                # Calculate scaling factor (diff images are resized)
                scale_x = img_diff_pil.width / original_width if original_width > 0 else 1
                scale_y = img_diff_pil.height / original_height if original_height > 0 else 1

                draw = ImageDraw.Draw(img_diff_pil)
                x, y, width, height = parts
                x_scaled = int(x * scale_x)
                y_scaled = int(y * scale_y)
                width_scaled = int(width * scale_x)
                height_scaled = int(height * scale_y)

                # Draw blue rectangle (3px border)
                for offset in range(3):
                    draw.rectangle(
                        [x_scaled + offset, y_scaled + offset,
                         x_scaled + width_scaled - offset, y_scaled + height_scaled - offset],
                        outline='blue'
                    )

                buf = io.BytesIO()
                img_diff_pil.save(buf, format='JPEG', quality=85)
                diff_bytes = buf.getvalue()
                img_diff_pil.close()
                buf.close()
    except Exception as e:
        logger.warning(f"Failed to draw bounding box on diff: {e}")

    return diff_bytes


def render(watch, datastore, request, url_for, render_template, flash, redirect):
    """
    Render the screenshot comparison diff page.

    Args:
        watch: Watch object
        datastore: Datastore object
        request: Flask request
        url_for: Flask url_for function
        render_template: Flask render_template function
        flash: Flask flash function
        redirect: Flask redirect function

    Returns:
        Rendered template or redirect
    """
    # Get version parameters (from_version, to_version)
    versions = list(watch.history.keys())

    if len(versions) < 2:
        flash("Not enough history to compare. Need at least 2 snapshots.", "error")
        return redirect(url_for('watchlist.index'))

    # Default: compare latest two versions
    from_version = request.args.get('from_version', versions[-2] if len(versions) >= 2 else versions[0])
    to_version = request.args.get('to_version', versions[-1])

    # Validate versions exist
    if from_version not in versions:
        from_version = versions[-2] if len(versions) >= 2 else versions[0]
    if to_version not in versions:
        to_version = versions[-1]

    # Get threshold (per-watch > global > env default)
    threshold = watch.get('comparison_threshold')
    if not threshold or threshold == '':
        threshold = datastore.data['settings']['application'].get('comparison_threshold', DEFAULT_COMPARISON_THRESHOLD_OPENCV)

    # Convert threshold to appropriate type
    try:
        threshold = float(threshold)
    except (ValueError, TypeError):
        logger.warning(f"Invalid threshold value '{threshold}', using default")
        threshold = 30.0

    # Load screenshots from history
    try:
        img_bytes_from = watch.get_history_snapshot(timestamp=from_version)
        img_bytes_to = watch.get_history_snapshot(timestamp=to_version)

        # Convert to bytes if needed (should already be bytes for screenshots)
        if isinstance(img_bytes_from, str):
            img_bytes_from = img_bytes_from.encode('utf-8')
        if isinstance(img_bytes_to, str):
            img_bytes_to = img_bytes_to.encode('utf-8')

    except Exception as e:
        logger.error(f"Failed to load screenshots: {e}")
        flash(f"Failed to load screenshots: {e}", "error")
        return redirect(url_for('watchlist.index'))

    # Calculate only change_percentage for display (lightweight version using OpenCV)
    # Full diff image generation happens on-demand in get_asset() when browser requests it
    # This significantly reduces memory usage by avoiding large intermediate arrays
    now = time.time()
    try:
        change_percentage = calculate_change_percentage_opencv(img_bytes_from, img_bytes_to, threshold)
        method_display = f"OpenCV (threshold: {threshold:.0f})"

    except Exception as e:
        logger.error(f"Failed to calculate change percentage: {e}")
        flash(f"Failed to calculate diff: {e}", "error")
        return redirect(url_for('watchlist.index'))
    finally:
        logger.debug(f"Done OpenCV percentage calculation in {time.time() - now:.2f}s")

    # Clean up image byte objects - no longer needed since we serve via get_asset()
    # This significantly reduces memory usage by not keeping large images in memory
    del img_bytes_from
    del img_bytes_to

    # Load historical data if available (for charts/visualization)
    comparison_data = {}
    comparison_config_path = os.path.join(watch.watch_data_dir, "visual_comparison_data.json")
    if os.path.isfile(comparison_config_path):
        try:
            with open(comparison_config_path, 'r') as f:
                comparison_data = json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load comparison history data: {e}")

    # Render custom template
    # Template path is namespaced to avoid conflicts with other processors
    # Images are now served via separate /processor-asset/ endpoints instead of base64
    return render_template(
        'image_ssim_diff/diff.html',
        watch=watch,
        uuid=watch.get('uuid'),
        change_percentage=change_percentage,
        comparison_data=comparison_data,  # Full history for charts/visualization
        threshold=threshold,
        comparison_method=method_display,
        versions=versions,
        from_version=from_version,
        to_version=to_version,
        percentage_different=change_percentage
    )
