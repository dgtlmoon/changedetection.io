"""
Screenshot diff visualization for SSIM processor.

Generates side-by-side comparison with red-highlighted differences.
"""

import os
import json
import base64
import io
from loguru import logger
from PIL import Image
import numpy as np
from skimage.metrics import structural_similarity as ssim


def calculate_ssim_with_map(img_bytes_from, img_bytes_to):
    """
    Calculate SSIM and generate a difference map.

    Args:
        img_bytes_from: Previous screenshot (bytes)
        img_bytes_to: Current screenshot (bytes)

    Returns:
        tuple: (ssim_score, diff_map) where diff_map is a 2D numpy array
    """
    # Load images
    img_from = Image.open(io.BytesIO(img_bytes_from))
    img_to = Image.open(io.BytesIO(img_bytes_to))

    # Ensure images are the same size
    if img_from.size != img_to.size:
        img_from = img_from.resize(img_to.size, Image.Resampling.LANCZOS)

    # Convert to RGB
    if img_from.mode != 'RGB':
        img_from = img_from.convert('RGB')
    if img_to.mode != 'RGB':
        img_to = img_to.convert('RGB')

    # Convert to numpy arrays
    arr_from = np.array(img_from)
    arr_to = np.array(img_to)

    # Calculate SSIM with full output to get the diff map
    ssim_score, diff_map = ssim(
        arr_from,
        arr_to,
        channel_axis=-1,
        data_range=255,
        full=True
    )

    # Clean up images and arrays to free memory
    img_from.close()
    img_to.close()
    del arr_from
    del arr_to

    return float(ssim_score), diff_map


def generate_diff_image(img_bytes_from, img_bytes_to, diff_map, threshold=0.95):
    """
    Generate a difference image highlighting changed regions in red.

    Args:
        img_bytes_from: Previous screenshot (bytes)
        img_bytes_to: Current screenshot (bytes)
        diff_map: Per-pixel SSIM similarity map (2D or 3D numpy array, 0-1)
        threshold: SSIM threshold for highlighting changes

    Returns:
        bytes: PNG image with red highlights on changed pixels
    """
    # Load current image as base
    img_to = Image.open(io.BytesIO(img_bytes_to))

    if img_to.mode != 'RGB':
        img_to = img_to.convert('RGB')

    result_array = np.array(img_to)

    # If diff_map is 3D (one value per color channel), average to get 2D
    if len(diff_map.shape) == 3:
        diff_map = np.mean(diff_map, axis=2)

    # Create a mask for changed pixels (SSIM < threshold)
    # Resize diff_map to match image dimensions if needed
    if diff_map.shape != result_array.shape[:2]:
        from skimage.transform import resize
        diff_map = resize(diff_map, result_array.shape[:2], order=1, preserve_range=True)

    changed_mask = diff_map < threshold

    # Overlay semi-transparent red on changed pixels
    # Blend the original pixel with red (50% opacity)
    result_array[changed_mask] = (
        result_array[changed_mask] * 0.5 + np.array([255, 0, 0]) * 0.5
    ).astype(np.uint8)

    # Convert back to PIL Image
    diff_img = Image.fromarray(result_array.astype(np.uint8))

    # Save to bytes as JPEG with moderate quality to reduce file size
    buf = io.BytesIO()
    diff_img.save(buf, format='JPEG', quality=75, optimize=True)
    diff_bytes = buf.getvalue()

    # Clean up to free memory
    diff_img.close()
    img_to.close()
    del result_array
    del diff_map
    buf.close()

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

    # Load SSIM score data from JSON config
    ssim_config_path = os.path.join(watch.watch_data_dir, "visual_ssim_score.json")
    ssim_data = {}
    if os.path.isfile(ssim_config_path):
        try:
            with open(ssim_config_path, 'r') as f:
                ssim_data = json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load SSIM data: {e}")

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

    # Calculate SSIM and generate difference map
    try:
        ssim_score, diff_map = calculate_ssim_with_map(img_bytes_from, img_bytes_to)
    except Exception as e:
        logger.error(f"Failed to calculate SSIM: {e}")
        flash(f"Failed to calculate SSIM: {e}", "error")
        return redirect(url_for('watchlist.index'))

    # Get threshold (per-watch or global)
    threshold = watch.get('ssim_threshold')
    if not threshold or threshold == '':
        threshold = datastore.data['settings']['application'].get('ssim_threshold', '0.96')

    # Convert string to float
    try:
        threshold = float(threshold)
    except (ValueError, TypeError):
        logger.warning(f"Invalid SSIM threshold value '{threshold}', using default 0.96")
        threshold = 0.96

    # Generate difference image with red highlights
    try:
        diff_image_bytes = generate_diff_image(img_bytes_from, img_bytes_to, diff_map, threshold)
        # Clean up diff_map after use
        del diff_map
    except Exception as e:
        logger.error(f"Failed to generate diff image: {e}")
        flash(f"Failed to generate diff image: {e}", "error")
        return redirect(url_for('watchlist.index'))

    # Convert images to base64 for embedding in template
    img_from_b64 = base64.b64encode(img_bytes_from).decode('utf-8')
    img_to_b64 = base64.b64encode(img_bytes_to).decode('utf-8')
    diff_image_b64 = base64.b64encode(diff_image_bytes).decode('utf-8')

    # Clean up large byte objects after base64 encoding
    del img_bytes_from
    del img_bytes_to
    del diff_image_bytes

    # Render custom template
    # Template path is namespaced to avoid conflicts with other processors
    return render_template(
        'image_ssim_diff/diff.html',
        watch=watch,
        uuid=watch.get('uuid'),
        img_from_b64=img_from_b64,
        img_to_b64=img_to_b64,
        diff_image_b64=diff_image_b64,
        ssim_score=ssim_score,
        ssim_data=ssim_data,  # Full history for charts/visualization
        threshold=threshold,
        versions=versions,
        from_version=from_version,
        to_version=to_version,
        percentage_different=(1 - ssim_score) * 100
    )
