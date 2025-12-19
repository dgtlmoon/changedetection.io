"""
Screenshot diff visualization for fast image comparison processor.

All image operations now use ImageDiffHandler abstraction for clean separation
of concerns and easy backend swapping (LibVIPS, OpenCV, PIL, etc.).
"""

import os
import json
import time
from loguru import logger
from . import DEFAULT_COMPARISON_THRESHOLD_OPENCV

# All image operations now use OpenCV via isolated_opencv subprocess handler
# No direct handler imports needed - subprocess isolation handles everything

# Maximum dimensions for diff visualization (can be overridden via environment variable)
# Large screenshots don't need full resolution for visual inspection
# Reduced defaults to minimize memory usage - 2000px height is plenty for diff viewing
MAX_DIFF_HEIGHT = int(os.getenv('MAX_DIFF_HEIGHT', '8000'))
MAX_DIFF_WIDTH = int(os.getenv('MAX_DIFF_WIDTH', '900'))


def get_asset(asset_name, watch, datastore, request):
    """
    Get processor-specific binary assets for streaming.

    Uses ImageDiffHandler for all image operations - no more multiprocessing needed
    as LibVIPS handles threading/memory internally.

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
    # Get version parameters from query string
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
            # Return the 'from' screenshot with bounding box if configured
            img_bytes = watch.get_history_snapshot(timestamp=from_version)
            img_bytes = _draw_bounding_box_if_configured(img_bytes, watch, datastore)
            return (img_bytes, 'image/png', 'public, max-age=3600')

        elif asset_name == 'after':
            # Return the 'to' screenshot with bounding box if configured
            img_bytes = watch.get_history_snapshot(timestamp=to_version)
            img_bytes = _draw_bounding_box_if_configured(img_bytes, watch, datastore)
            return (img_bytes, 'image/png', 'public, max-age=3600')

        elif asset_name == 'rendered_diff':
            # Generate diff in isolated subprocess to prevent memory leaks
            # Subprocess provides complete memory isolation
            from .image_handler import isolated_opencv as process_screenshot_handler

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

            # Get blur sigma
            blur_sigma = float(os.getenv("OPENCV_BLUR_SIGMA", "0.8"))

            # Generate diff in isolated subprocess
            diff_image_bytes = process_screenshot_handler.generate_diff_isolated(
                img_bytes_from,
                img_bytes_to,
                int(threshold),
                blur_sigma,
                MAX_DIFF_WIDTH,
                MAX_DIFF_HEIGHT
            )

            if diff_image_bytes:
                # Note: Bounding box drawing on diff not yet implemented
                return (diff_image_bytes, 'image/jpeg', 'public, max-age=300')
            else:
                logger.error("Failed to generate diff in subprocess")
                return None

        else:
            # Unknown asset
            return None

    except Exception as e:
        logger.error(f"Failed to get asset '{asset_name}': {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None


def _draw_bounding_box_if_configured(img_bytes, watch, datastore):
    """
    Draw blue bounding box on image if configured in processor settings.

    Args:
        img_bytes: Image bytes (PNG)
        watch: Watch object
        datastore: Datastore object

    Returns:
        Image bytes (possibly with bounding box drawn)
    """
    try:
        # Get bounding box configuration from processor JSON
        from changedetectionio import processors
        processor_instance = processors.difference_detection_processor(datastore, watch.get('uuid'))
        processor_name = watch.get('processor', 'default')
        config_filename = f'{processor_name}.json'
        processor_config = processor_instance.get_extra_watch_config(config_filename)
        bounding_box = processor_config.get('bounding_box') if processor_config else None

        if not bounding_box:
            return img_bytes

        # Parse bounding box: "x,y,width,height"
        parts = [int(p.strip()) for p in bounding_box.split(',')]
        if len(parts) != 4:
            logger.warning(f"Invalid bounding box format: {bounding_box}")
            return img_bytes

        x, y, width, height = parts

        # Use OpenCV to draw rectangle (no subprocess needed for simple drawing)
        import cv2
        import numpy as np

        # Decode image
        img_array = cv2.imdecode(np.frombuffer(img_bytes, np.uint8), cv2.IMREAD_COLOR)
        if img_array is None:
            logger.warning("Failed to decode image for bounding box drawing")
            return img_bytes

        # Draw blue rectangle (BGR format: blue=255, green=0, red=0)
        # Use thickness=3 for visibility
        cv2.rectangle(img_array, (x, y), (x + width, y + height), (255, 0, 0), 3)

        # Encode back to PNG
        _, encoded = cv2.imencode('.png', img_array)
        return encoded.tobytes()

    except Exception as e:
        logger.warning(f"Failed to draw bounding box: {e}")
        import traceback
        logger.debug(traceback.format_exc())
        return img_bytes


def render(watch, datastore, request, url_for, render_template, flash, redirect):
    """
    Render the screenshot comparison diff page.

    Uses ImageDiffHandler for all image operations.

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

    # Get blur sigma
    blur_sigma = float(os.getenv("OPENCV_BLUR_SIGMA", "0.8"))

    # Load screenshots from history
    try:
        img_bytes_from = watch.get_history_snapshot(timestamp=from_version)
        img_bytes_to = watch.get_history_snapshot(timestamp=to_version)

    except Exception as e:
        logger.error(f"Failed to load screenshots: {e}")
        flash(f"Failed to load screenshots: {e}", "error")
        return redirect(url_for('watchlist.index'))

    # Calculate change percentage using isolated subprocess to prevent memory leaks
    now = time.time()
    try:
        from .image_handler import isolated_opencv as process_screenshot_handler

        change_percentage = process_screenshot_handler.calculate_change_percentage_isolated(
            img_bytes_from,
            img_bytes_to,
            int(threshold),
            blur_sigma,
            MAX_DIFF_WIDTH,
            MAX_DIFF_HEIGHT
        )

        method_display = f"{process_screenshot_handler.IMPLEMENTATION_NAME} (threshold: {threshold:.0f})"
        logger.debug(f"Done change percentage calculation in {time.time() - now:.2f}s")

    except Exception as e:
        logger.error(f"Failed to calculate change percentage: {e}")
        import traceback
        logger.error(traceback.format_exc())
        flash(f"Failed to calculate diff: {e}", "error")
        return redirect(url_for('watchlist.index'))

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
