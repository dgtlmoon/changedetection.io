"""
Optional hook called when processor settings are saved in edit page.

This hook analyzes the selected region to determine if template matching
should be enabled for tracking content movement.

Template matching is controlled via ENABLE_TEMPLATE_TRACKING env var (default: False).
"""

import io
import os
from loguru import logger
from changedetectionio import strtobool
from . import CROPPED_IMAGE_TEMPLATE_FILENAME

# Template matching controlled via environment variable (default: disabled)
# Set ENABLE_TEMPLATE_TRACKING=True to enable
TEMPLATE_MATCHING_ENABLED = strtobool(os.getenv('ENABLE_TEMPLATE_TRACKING', 'False'))
IMPORT_ERROR = "Template matching disabled (set ENABLE_TEMPLATE_TRACKING=True to enable)"


def on_config_save(watch, processor_config, datastore):
    """
    Called after processor config is saved in edit page.

    Analyzes the bounding box region to determine if it has enough
    visual features (texture/edges) to enable template matching for
    tracking content movement when page layout shifts.

    Args:
        watch: Watch object
        processor_config: Dict of processor-specific config
        datastore: Datastore object

    Returns:
        dict: Updated processor_config with auto_track_region setting
    """
    # Check if template matching is globally enabled via ENV var
    if not TEMPLATE_MATCHING_ENABLED:
        logger.debug("Template tracking disabled via ENABLE_TEMPLATE_TRACKING env var")
        processor_config['auto_track_region'] = False
        return processor_config

    bounding_box = processor_config.get('bounding_box')

    if not bounding_box:
        # No bounding box, disable tracking
        processor_config['auto_track_region'] = False
        logger.debug("No bounding box set, disabled auto-tracking")
        return processor_config

    try:
        # Get the latest screenshot from watch history
        history_keys = list(watch.history.keys())
        if len(history_keys) == 0:
            logger.warning("No screenshot history available yet, cannot analyze for tracking")
            processor_config['auto_track_region'] = False
            return processor_config

        # Get latest screenshot
        latest_timestamp = history_keys[-1]
        screenshot_bytes = watch.get_history_snapshot(timestamp=latest_timestamp)

        if not screenshot_bytes:
            logger.warning("Could not load screenshot for analysis")
            processor_config['auto_track_region'] = False
            return processor_config

        # Parse bounding box
        parts = [int(p.strip()) for p in bounding_box.split(',')]
        if len(parts) != 4:
            logger.warning("Invalid bounding box format")
            processor_config['auto_track_region'] = False
            return processor_config

        x, y, width, height = parts

        # Analyze the region for features/texture
        has_enough_features = analyze_region_features(screenshot_bytes, x, y, width, height)

        if has_enough_features:
            logger.info(f"Region has sufficient features for tracking - enabling auto_track_region")
            processor_config['auto_track_region'] = True

            # Save the template as cropped.jpg in watch data directory
            save_template_to_file(watch, screenshot_bytes, x, y, width, height)

        else:
            logger.info(f"Region lacks distinctive features - disabling auto_track_region")
            processor_config['auto_track_region'] = False

            # Remove old template file if exists
            template_path = os.path.join(watch.watch_data_dir, CROPPED_IMAGE_TEMPLATE_FILENAME)
            if os.path.exists(template_path):
                os.remove(template_path)
                logger.debug(f"Removed old template file: {template_path}")

        return processor_config

    except Exception as e:
        logger.error(f"Error analyzing region for tracking: {e}")
        processor_config['auto_track_region'] = False
        return processor_config


def analyze_region_features(screenshot_bytes, x, y, width, height):
    """
    Analyze if a region has enough visual features for template matching.

    Uses OpenCV to detect corners/edges. If the region has distinctive
    features, template matching can reliably track it when it moves.

    Args:
        screenshot_bytes: Full screenshot as bytes
        x, y, width, height: Bounding box coordinates

    Returns:
        bool: True if region has enough features, False otherwise
    """
    # Template matching disabled - would need OpenCV implementation for region analysis
    if not TEMPLATE_MATCHING_ENABLED:
        logger.warning(f"Cannot analyze region features: {IMPORT_ERROR}")
        return False

    # Note: Original implementation used LibVIPS handler to crop region, then OpenCV
    # for feature detection (goodFeaturesToTrack, Canny edge detection, variance).
    # If re-implementing, use OpenCV directly for both cropping and analysis.
    # Feature detection would use: cv2.goodFeaturesToTrack, cv2.Canny, np.var
    return False


def save_template_to_file(watch, screenshot_bytes, x, y, width, height):
    """
    Extract the template region and save as cropped_image_template.png in watch data directory.

    This is a convenience wrapper around handler.save_template() that handles
    watch directory setup and path construction.

    Args:
        watch: Watch object
        screenshot_bytes: Full screenshot as bytes
        x, y, width, height: Bounding box coordinates
    """
    # Template matching disabled - would need OpenCV implementation for template saving
    if not TEMPLATE_MATCHING_ENABLED:
        logger.warning(f"Cannot save template: {IMPORT_ERROR}")
        return

    # Note: Original implementation used LibVIPS handler to crop and save region.
    # If re-implementing, use OpenCV (cv2.imdecode, crop with array slicing, cv2.imwrite).
    return
