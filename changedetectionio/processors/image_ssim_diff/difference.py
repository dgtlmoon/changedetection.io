"""
Screenshot diff visualization for fast image comparison processor.

All image operations now use ImageDiffHandler abstraction for clean separation
of concerns and easy backend swapping (LibVIPS, OpenCV, PIL, etc.).
"""

import os
import json
import time
from loguru import logger

from changedetectionio.processors.image_ssim_diff import SCREENSHOT_COMPARISON_THRESHOLD_OPTIONS_DEFAULT, PROCESSOR_CONFIG_NAME, \
    OPENCV_BLUR_SIGMA

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
            mime_type = _detect_mime_type(img_bytes)
            return (img_bytes, mime_type, 'public, max-age=3600')

        elif asset_name == 'after':
            # Return the 'to' screenshot with bounding box if configured
            img_bytes = watch.get_history_snapshot(timestamp=to_version)
            img_bytes = _draw_bounding_box_if_configured(img_bytes, watch, datastore)
            mime_type = _detect_mime_type(img_bytes)
            return (img_bytes, mime_type, 'public, max-age=3600')

        elif asset_name == 'rendered_diff':
            # Generate diff in isolated subprocess to prevent memory leaks
            # Subprocess provides complete memory isolation
            from .image_handler import isolated_opencv as process_screenshot_handler

            img_bytes_from = watch.get_history_snapshot(timestamp=from_version)
            img_bytes_to = watch.get_history_snapshot(timestamp=to_version)

            # Get pixel difference threshold sensitivity (per-watch > global)
            # This controls how different a pixel must be (0-255 scale) to count as "changed"
            from changedetectionio import processors
            processor_instance = processors.difference_detection_processor(datastore, watch.get('uuid'))
            processor_config = processor_instance.get_extra_watch_config(PROCESSOR_CONFIG_NAME)

            pixel_difference_threshold_sensitivity = processor_config.get('pixel_difference_threshold_sensitivity')
            if not pixel_difference_threshold_sensitivity:
                pixel_difference_threshold_sensitivity = datastore.data['settings']['application'].get(
                    'pixel_difference_threshold_sensitivity', SCREENSHOT_COMPARISON_THRESHOLD_OPTIONS_DEFAULT)
            try:
                pixel_difference_threshold_sensitivity = int(pixel_difference_threshold_sensitivity)
            except (ValueError, TypeError):
                logger.warning(
                    f"Invalid pixel_difference_threshold_sensitivity value '{pixel_difference_threshold_sensitivity}', using default")
                pixel_difference_threshold_sensitivity = SCREENSHOT_COMPARISON_THRESHOLD_OPTIONS_DEFAULT

            logger.debug(f"Pixel difference threshold sensitivity is {pixel_difference_threshold_sensitivity}")


            # Generate diff in isolated subprocess (async-safe)
            import asyncio
            import threading

            # Async-safe wrapper: runs coroutine in new thread with its own event loop
            def run_async_in_thread():
                return asyncio.run(
                    process_screenshot_handler.generate_diff_isolated(
                        img_bytes_from,
                        img_bytes_to,
                        pixel_difference_threshold=int(pixel_difference_threshold_sensitivity),
                        blur_sigma=OPENCV_BLUR_SIGMA,
                        max_width=MAX_DIFF_WIDTH,
                        max_height=MAX_DIFF_HEIGHT
                    )
                )

            # Run in thread to avoid blocking event loop if called from async context
            result_container = [None]
            exception_container = [None]

            def thread_target():
                try:
                    result_container[0] = run_async_in_thread()
                except Exception as e:
                    exception_container[0] = e

            thread = threading.Thread(target=thread_target)
            thread.start()
            thread.join(timeout=60)

            if exception_container[0]:
                raise exception_container[0]

            diff_image_bytes = result_container[0]

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


def _detect_mime_type(img_bytes):
    """
    Detect MIME type using puremagic (same as Watch.py).

    Args:
        img_bytes: Image bytes

    Returns:
        str: MIME type (e.g., 'image/png', 'image/jpeg')
    """
    try:
        import puremagic
        detections = puremagic.magic_string(img_bytes[:2048])
        if detections:
            mime_type = detections[0].mime_type
            logger.trace(f"Detected MIME type: {mime_type}")
            return mime_type
        else:
            logger.trace("No MIME type detected, using 'image/png' fallback")
            return 'image/png'
    except Exception as e:
        logger.warning(f"puremagic detection failed: {e}, using 'image/png' fallback")
        return 'image/png'


def _draw_bounding_box_if_configured(img_bytes, watch, datastore):
    """
    Draw blue bounding box on image if configured in processor settings.
    Uses isolated subprocess to prevent memory leaks from large images.

    Supports two modes:
    - "Select by element": Use include_filter to find xpath element bbox
    - "Draw area": Use manually drawn bounding_box from config

    Args:
        img_bytes: Image bytes (PNG)
        watch: Watch object
        datastore: Datastore object

    Returns:
        Image bytes (possibly with bounding box drawn)
    """
    try:
        # Get processor configuration
        from changedetectionio import processors
        processor_instance = processors.difference_detection_processor(datastore, watch.get('uuid'))
        processor_name = watch.get('processor', 'default')
        config_filename = f'{processor_name}.json'
        processor_config = processor_instance.get_extra_watch_config(config_filename)

        if not processor_config:
            return img_bytes

        selection_mode = processor_config.get('selection_mode', 'draw')
        x, y, width, height = None, None, None, None

        # Mode 1: Select by element (use include_filter + xpath_data)
        if selection_mode == 'element':
            include_filters = watch.get('include_filters', [])

            if include_filters and len(include_filters) > 0:
                first_filter = include_filters[0].strip()

                # Get xpath_data from watch history
                history_keys = list(watch.history.keys())
                if history_keys:
                    latest_snapshot = watch.get_history_snapshot(timestamp=history_keys[-1])
                    xpath_data_path = watch.get_xpath_data_filepath(timestamp=history_keys[-1])

                    try:
                        import gzip
                        with gzip.open(xpath_data_path, 'rt') as f:
                            xpath_data = json.load(f)

                        # Find matching element
                        for element in xpath_data.get('size_pos', []):
                            if element.get('xpath') == first_filter and element.get('highlight_as_custom_filter'):
                                x = element.get('left', 0)
                                y = element.get('top', 0)
                                width = element.get('width', 0)
                                height = element.get('height', 0)
                                logger.debug(f"Found element bbox for filter '{first_filter}': x={x}, y={y}, w={width}, h={height}")
                                break
                    except Exception as e:
                        logger.warning(f"Failed to load xpath_data for element selection: {e}")

        # Mode 2: Draw area (use manually configured bbox)
        else:
            bounding_box = processor_config.get('bounding_box')
            if bounding_box:
                # Parse bounding box: "x,y,width,height"
                parts = [int(p.strip()) for p in bounding_box.split(',')]
                if len(parts) == 4:
                    x, y, width, height = parts
                else:
                    logger.warning(f"Invalid bounding box format: {bounding_box}")

        # If no bbox found, return original image
        if x is None or y is None or width is None or height is None:
            return img_bytes

        # Use isolated subprocess to prevent memory leaks from large images
        from .image_handler import isolated_opencv
        import asyncio
        import threading

        # Async-safe wrapper: runs coroutine in new thread with its own event loop
        # This prevents blocking when called from async context (update worker)
        def run_async_in_thread():
            return asyncio.run(
                isolated_opencv.draw_bounding_box_isolated(
                    img_bytes, x, y, width, height,
                    color=(255, 0, 0),  # Blue in BGR format
                    thickness=3
                )
            )

        # Always run in thread to avoid blocking event loop if called from async context
        result_container = [None]
        exception_container = [None]

        def thread_target():
            try:
                result_container[0] = run_async_in_thread()
            except Exception as e:
                exception_container[0] = e

        thread = threading.Thread(target=thread_target)
        thread.start()
        thread.join(timeout=15)

        if exception_container[0]:
            raise exception_container[0]

        result = result_container[0]

        # Return result or original if subprocess failed
        return result if result else img_bytes

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

    # Get pixel difference threshold sensitivity (per-watch > global > env default)
    pixel_difference_threshold_sensitivity = watch.get('pixel_difference_threshold_sensitivity')
    if not pixel_difference_threshold_sensitivity or pixel_difference_threshold_sensitivity == '':
        pixel_difference_threshold_sensitivity = datastore.data['settings']['application'].get('pixel_difference_threshold_sensitivity', SCREENSHOT_COMPARISON_THRESHOLD_OPTIONS_DEFAULT)

    # Convert to appropriate type
    try:
        pixel_difference_threshold_sensitivity = float(pixel_difference_threshold_sensitivity)
    except (ValueError, TypeError):
        logger.warning(f"Invalid pixel_difference_threshold_sensitivity value '{pixel_difference_threshold_sensitivity}', using default")
        pixel_difference_threshold_sensitivity = 30.0

    # Get blur sigma
    blur_sigma = OPENCV_BLUR_SIGMA

    # Load screenshots from history
    try:
        img_bytes_from = watch.get_history_snapshot(timestamp=from_version)
        img_bytes_to = watch.get_history_snapshot(timestamp=to_version)

    except Exception as e:
        logger.error(f"Failed to load screenshots: {e}")
        flash(f"Failed to load screenshots: {e}", "error")
        return redirect(url_for('watchlist.index'))

    # Calculate change percentage using isolated subprocess to prevent memory leaks (async-safe)
    now = time.time()
    try:
        from .image_handler import isolated_opencv as process_screenshot_handler
        import asyncio
        import threading

        # Async-safe wrapper: runs coroutine in new thread with its own event loop
        def run_async_in_thread():
            return asyncio.run(
                process_screenshot_handler.calculate_change_percentage_isolated(
                    img_bytes_from,
                    img_bytes_to,
                    pixel_difference_threshold=int(pixel_difference_threshold_sensitivity),
                    blur_sigma=blur_sigma,
                    max_width=MAX_DIFF_WIDTH,
                    max_height=MAX_DIFF_HEIGHT
                )
            )

        # Run in thread to avoid blocking event loop if called from async context
        result_container = [None]
        exception_container = [None]

        def thread_target():
            try:
                result_container[0] = run_async_in_thread()
            except Exception as e:
                exception_container[0] = e

        thread = threading.Thread(target=thread_target)
        thread.start()
        thread.join(timeout=60)

        if exception_container[0]:
            raise exception_container[0]

        change_percentage = result_container[0]

        method_display = f"{process_screenshot_handler.IMPLEMENTATION_NAME} (pixel_diff_threshold: {pixel_difference_threshold_sensitivity:.0f})"
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
        change_percentage=change_percentage,
        comparison_data=comparison_data,  # Full history for charts/visualization
        comparison_method=method_display,
        current_diff_url=watch['url'],
        from_version=from_version,
        percentage_different=change_percentage,
        threshold=pixel_difference_threshold_sensitivity,
        to_version=to_version,
        uuid=watch.get('uuid'),
        versions=versions,
        watch=watch,
    )
