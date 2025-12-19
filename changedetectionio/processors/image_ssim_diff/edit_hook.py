"""
Optional hook called when processor settings are saved in edit page.

This hook analyzes the selected region to determine if template matching
should be enabled for tracking content movement.

Now uses LibVIPS handler for all image operations.
"""

import io
import os
from loguru import logger
from changedetectionio import strtobool
from . import CROPPED_IMAGE_TEMPLATE_FILENAME

# Check if pyvips is available
try:
    from .libvips_handler import LibvipsImageDiffHandler
    HANDLER_AVAILABLE = True
except ImportError as e:
    HANDLER_AVAILABLE = False
    IMPORT_ERROR = str(e)
    logger.warning(f"LibvipsImageDiffHandler not available: {e}")


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
    template_matching_enabled = strtobool(os.getenv('ENABLE_TEMPLATE_TRACKING', 'True'))

    if not template_matching_enabled:
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
    if not HANDLER_AVAILABLE:
        logger.warning(f"Cannot analyze region features: {IMPORT_ERROR}")
        return False

    try:
        import cv2
        import numpy as np

        # Use handler to load and crop image
        handler = LibvipsImageDiffHandler()
        img = handler.load_from_bytes(screenshot_bytes)

        # Crop to region
        left, top = x, y
        right, bottom = x + width, y + height
        region = handler.crop(img, left, top, right, bottom)

        # Convert to numpy array for OpenCV feature detection
        # LibVIPS can write to memory buffer which we convert to numpy
        region_array = np.ndarray(
            buffer=region.write_to_memory(),
            dtype=np.uint8,
            shape=[region.height, region.width, region.bands]
        )

        # Convert to grayscale
        if len(region_array.shape) == 3:
            gray = cv2.cvtColor(region_array, cv2.COLOR_RGB2GRAY)
        else:
            gray = region_array

        # Detect features using multiple methods for robust detection

        # 1. Corner detection (good for UI elements, buttons, text)
        corners = cv2.goodFeaturesToTrack(gray, maxCorners=100, qualityLevel=0.01, minDistance=10)
        corner_count = len(corners) if corners is not None else 0

        # 2. Edge detection (good for boundaries, shapes)
        edges = cv2.Canny(gray, 50, 150)
        edge_density = np.count_nonzero(edges) / edges.size

        # 3. Texture variance (good for textured regions)
        variance = np.var(gray)

        # Decision thresholds (tuned for typical web content)
        has_corners = corner_count >= 20  # At least 20 distinctive corners
        has_edges = edge_density >= 0.05  # At least 5% edge pixels
        has_texture = variance >= 100  # Some variance in pixel values

        logger.debug(f"Region analysis: corners={corner_count}, edge_density={edge_density:.2%}, "
                    f"variance={variance:.1f}")

        # Need at least 2 out of 3 indicators
        feature_score = sum([has_corners, has_edges, has_texture])

        if feature_score >= 2:
            logger.info(f"✓ Region has enough features for tracking (score: {feature_score}/3)")
            return True
        else:
            logger.info(f"✗ Region lacks features for tracking (score: {feature_score}/3)")
            return False

    except ImportError:
        logger.error("OpenCV not available, cannot analyze region features")
        return False
    except Exception as e:
        logger.error(f"Error in feature analysis: {e}")
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
    if not HANDLER_AVAILABLE:
        logger.warning(f"Cannot save template: {IMPORT_ERROR}")
        return

    try:
        # Ensure watch data directory exists
        watch.ensure_data_dir_exists()

        # Construct paths
        template_path = os.path.join(watch.watch_data_dir, CROPPED_IMAGE_TEMPLATE_FILENAME)
        bbox = (x, y, x + width, y + height)

        # Use handler to load image and save template (handler does crop + save)
        handler = LibvipsImageDiffHandler()
        img = handler.load_from_bytes(screenshot_bytes)
        handler.save_template(img, bbox, template_path)
        # Note: handler.save_template() already logs success/failure

    except Exception as e:
        logger.error(f"Error saving template: {e}")
