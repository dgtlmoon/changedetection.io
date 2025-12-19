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

# Check if pyvips is available
try:
    from .libvips_handler import LibvipsImageDiffHandler
    import pyvips

    # CRITICAL: Set aggressive memory limits for LibVIPS to prevent memory leaks
    pyvips.cache_set_max(0)  # Disable operation cache
    pyvips.cache_set_max_mem(0)  # Disable memory cache
    pyvips.cache_set_max_files(0)  # Disable file cache
    logger.info("LibVIPS cache disabled for memory leak prevention")

    HANDLER_AVAILABLE = True
except ImportError as e:
    HANDLER_AVAILABLE = False
    IMPORT_ERROR = str(e)
    logger.error(f"Failed to import LibvipsImageDiffHandler: {e}")

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
    # Check if handler is available
    if not HANDLER_AVAILABLE:
        logger.error(f"Cannot get asset '{asset_name}': {IMPORT_ERROR}")
        return None

    # Initialize handler
    handler = LibvipsImageDiffHandler()

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
            # Return the 'from' screenshot
            img_bytes = watch.get_history_snapshot(timestamp=from_version)

            # Optionally draw bounding box if configured
            img_bytes = _apply_bounding_box_if_configured(img_bytes, watch, datastore, handler)

            return (img_bytes, 'image/png', 'public, max-age=3600')

        elif asset_name == 'after':
            # Return the 'to' screenshot
            img_bytes = watch.get_history_snapshot(timestamp=to_version)

            # Optionally draw bounding box if configured
            img_bytes = _apply_bounding_box_if_configured(img_bytes, watch, datastore, handler)

            return (img_bytes, 'image/png', 'public, max-age=3600')

        elif asset_name == 'rendered_diff':
            # Generate the diff visualization on-demand
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

            try:
                # Load images
                img_from = handler.load_from_bytes(img_bytes_from)
                img_to = handler.load_from_bytes(img_bytes_to)

                # Ensure same size
                w1, h1 = handler.get_dimensions(img_from)
                w2, h2 = handler.get_dimensions(img_to)
                if (w1, h1) != (w2, h2):
                    img_from = handler.resize(img_from, w2, h2)

                # Downscale for faster diff visualization
                img_from = handler.resize(img_from, MAX_DIFF_WIDTH, MAX_DIFF_HEIGHT)
                img_to = handler.resize(img_to, MAX_DIFF_WIDTH, MAX_DIFF_HEIGHT)

                # Convert to grayscale
                gray_from = handler.to_grayscale(img_from)
                gray_to = handler.to_grayscale(img_to)

                # Release original color images
                del img_from

                # Optional blur
                gray_from = handler.gaussian_blur(gray_from, blur_sigma)
                gray_to = handler.gaussian_blur(gray_to, blur_sigma)

                # Calculate difference
                diff = handler.absolute_difference(gray_from, gray_to)

                # Release grayscale images
                del gray_from, gray_to

                # Threshold to get mask
                _, diff_mask = handler.threshold(diff, int(threshold))

                # Release diff image
                del diff

                # Generate diff image with red overlay
                diff_image_bytes = handler.apply_red_overlay(img_to, diff_mask)

                # Release mask and original img_to
                del diff_mask, img_to

                # Optionally draw bounding box on diff image if configured
                diff_image_bytes = _apply_bounding_box_to_diff(diff_image_bytes, watch, datastore, handler)

                return (diff_image_bytes, 'image/jpeg', 'public, max-age=300')

            finally:
                # Force Python garbage collection
                import gc
                gc.collect()

                logger.debug(f"Memory cleanup: gc collected")

        else:
            # Unknown asset
            return None

    except Exception as e:
        logger.error(f"Failed to get asset '{asset_name}': {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None


def _apply_bounding_box_if_configured(img_bytes, watch, datastore, handler):
    """
    Apply blue bounding box to image if configured in processor settings.

    Args:
        img_bytes: Image bytes (PNG)
        watch: Watch object
        datastore: Datastore object
        handler: ImageDiffHandler instance

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
                # Load image
                img = handler.load_from_bytes(img_bytes)

                # TODO: Add draw_rectangle method to handler
                # For now, return original bytes
                # This functionality can be added to the handler interface later
                logger.debug("Bounding box drawing not yet implemented in handler")
                return img_bytes

    except Exception as e:
        logger.warning(f"Failed to draw bounding box: {e}")

    return img_bytes


def _apply_bounding_box_to_diff(diff_bytes, watch, datastore, handler):
    """
    Apply blue bounding box to diff image if configured, accounting for scaling.

    Args:
        diff_bytes: Diff image bytes (JPEG)
        watch: Watch object
        datastore: Datastore object
        handler: ImageDiffHandler instance

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
            # TODO: Implement scaled bounding box drawing in handler
            logger.debug("Bounding box drawing on diff not yet implemented in handler")
            return diff_bytes

    except Exception as e:
        logger.warning(f"Failed to draw bounding box on diff: {e}")

    return diff_bytes


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
    # Check if handler is available
    if not HANDLER_AVAILABLE:
        flash(f"Screenshot comparison is not available: {IMPORT_ERROR}", "error")
        return redirect(url_for('watchlist.index'))

    # Initialize handler
    handler = LibvipsImageDiffHandler()

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

    # Calculate change percentage using handler
    now = time.time()
    try:
        # Load images
        img_from = handler.load_from_bytes(img_bytes_from)
        img_to = handler.load_from_bytes(img_bytes_to)

        # Ensure same size
        w1, h1 = handler.get_dimensions(img_from)
        w2, h2 = handler.get_dimensions(img_to)
        if (w1, h1) != (w2, h2):
            img_from = handler.resize(img_from, w2, h2)

        # Downscale for faster calculation
        img_from = handler.resize(img_from, MAX_DIFF_WIDTH, MAX_DIFF_HEIGHT)
        img_to = handler.resize(img_to, MAX_DIFF_WIDTH, MAX_DIFF_HEIGHT)

        # Convert to grayscale
        gray_from = handler.to_grayscale(img_from)
        gray_to = handler.to_grayscale(img_to)

        # Release color images
        del img_from, img_to

        # Optional blur
        gray_from = handler.gaussian_blur(gray_from, blur_sigma)
        gray_to = handler.gaussian_blur(gray_to, blur_sigma)

        # Calculate difference
        diff = handler.absolute_difference(gray_from, gray_to)

        # Release grayscale images
        del gray_from, gray_to

        # Apply threshold and get change percentage
        change_percentage, _ = handler.threshold(diff, int(threshold))

        # Release diff image
        del diff

        method_display = f"LibVIPS (threshold: {threshold:.0f})"

    except Exception as e:
        logger.error(f"Failed to calculate change percentage: {e}")
        import traceback
        logger.error(traceback.format_exc())
        flash(f"Failed to calculate diff: {e}", "error")
        return redirect(url_for('watchlist.index'))
    finally:
        # Force Python garbage collection
        import gc
        gc.collect()
        logger.debug(f"Done change percentage calculation in {time.time() - now:.2f}s")

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
