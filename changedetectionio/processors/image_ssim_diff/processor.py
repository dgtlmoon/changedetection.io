"""
Core SSIM-based screenshot comparison processor.

This processor uses the Structural Similarity Index (SSIM) to detect visual changes
in screenshots while being robust to antialiasing and minor rendering differences.
"""

import hashlib
import time
from loguru import logger
from changedetectionio.processors import difference_detection_processor
from changedetectionio.processors.exceptions import ProcessorException

name = 'Visual/Screenshot change detection (SSIM)'
description = 'Compares screenshots using SSIM algorithm, robust to antialiasing and rendering differences'


class perform_site_check(difference_detection_processor):
    """SSIM-based screenshot comparison processor."""

    def run_changedetection(self, watch):
        """
        Perform screenshot comparison using SSIM.

        Returns:
            tuple: (changed_detected, update_obj, screenshot_bytes)
        """
        from PIL import Image
        import io
        import numpy as np
        from skimage.metrics import structural_similarity as ssim

        # Get the current screenshot
        if not self.fetcher.screenshot:
            raise ProcessorException(
                message="No screenshot available. Ensure the watch is configured to use a real browser.",
                url=watch.get('url')
            )
        self.screenshot = self.fetcher.screenshot

        # Quick MD5 check - skip expensive SSIM if images are identical
        from changedetectionio.content_fetchers.exceptions import checksumFromPreviousCheckWasTheSame
        current_md5 = hashlib.md5(self.screenshot).hexdigest()
        previous_md5 = watch.get('previous_md5')
        if previous_md5 and current_md5 == previous_md5:
            logger.debug(f"Screenshot MD5 unchanged ({current_md5}), skipping SSIM calculation")
            raise checksumFromPreviousCheckWasTheSame()

        # Get threshold (per-watch or global)
        threshold = watch.get('ssim_threshold')
        if not threshold or threshold == '':
            threshold = self.datastore.data['settings']['application'].get('ssim_threshold', '0.96')

        # Convert string to float
        try:
            threshold = float(threshold)
        except (ValueError, TypeError):
            logger.warning(f"Invalid SSIM threshold value '{threshold}', using default 0.96")
            threshold = 0.96

        # Convert current screenshot to PIL Image
        try:
            current_img = Image.open(io.BytesIO(self.screenshot))
        except Exception as e:
            raise ProcessorException(
                message=f"Failed to load current screenshot: {e}",
                url=watch.get('url')
            )

        # Check if this is the first check (no previous history)
        history_keys = list(watch.history.keys())
        if len(history_keys) == 0:
            # First check - save baseline, no comparison
            logger.info(f"First check for watch {watch.get('uuid')} - saving baseline screenshot")

            # Close the PIL image before returning
            current_img.close()
            del current_img

            update_obj = {
                'previous_md5': hashlib.md5(self.screenshot).hexdigest(),
                'last_error': False
            }

            return False, update_obj, self.screenshot

        # Get previous screenshot from history
        try:
            previous_timestamp = history_keys[-1]
            previous_screenshot_bytes = watch.get_history_snapshot(timestamp=previous_timestamp)

            # Screenshots are stored as PNG, so this should be bytes
            if isinstance(previous_screenshot_bytes, str):
                # If it's a string (shouldn't be for screenshots, but handle it)
                previous_screenshot_bytes = previous_screenshot_bytes.encode('utf-8')

            previous_img = Image.open(io.BytesIO(previous_screenshot_bytes))
        except Exception as e:
            logger.warning(f"Failed to load previous screenshot for comparison: {e}")
            # Clean up current image before returning
            if 'current_img' in locals():
                current_img.close()
                del current_img

            # If we can't load previous, treat as first check
            update_obj = {
                'previous_md5': hashlib.md5(self.screenshot).hexdigest(),
                'last_error': False
            }

            return False, update_obj, self.screenshot

        # Convert images to numpy arrays for SSIM calculation
        try:
            # Ensure images are the same size
            if current_img.size != previous_img.size:
                logger.info(f"Resizing images to match: {previous_img.size} -> {current_img.size}")
                previous_img = previous_img.resize(current_img.size, Image.Resampling.LANCZOS)

            # Convert to RGB if needed (handle RGBA, grayscale, etc.)
            if current_img.mode != 'RGB':
                current_img = current_img.convert('RGB')
            if previous_img.mode != 'RGB':
                previous_img = previous_img.convert('RGB')

            # Convert to numpy arrays
            current_array = np.array(current_img)
            previous_array = np.array(previous_img)

            # Calculate SSIM
            # multichannel=True for RGB images (deprecated in favor of channel_axis)
            # Use channel_axis=-1 for color images (last dimension is color channels)
            ssim_score = ssim(
                previous_array,
                current_array,
                channel_axis=-1,
                data_range=255
            )

            logger.info(f"SSIM score: {ssim_score:.4f}, threshold: {threshold}")

            # Explicitly close PIL images and delete arrays to free memory immediately
            current_img.close()
            previous_img.close()
            del current_array
            del previous_array
            del previous_screenshot_bytes  # Release the large bytes object

        except Exception as e:
            logger.error(f"Failed to calculate SSIM: {e}")
            # Ensure cleanup even on error - try to clean up any objects that were created
            # (silently ignore if they don't exist)
            for obj in ['current_img', 'previous_img']:
                try:
                    locals()[obj].close()
                except (KeyError, NameError, AttributeError):
                    pass
            raise ProcessorException(
                message=f"SSIM calculation failed: {e}",
                url=watch.get('url')
            )

        # Determine if change detected (lower SSIM = more different)
        changed_detected = ssim_score < threshold

        # Return results
        update_obj = {
            'previous_md5': hashlib.md5(self.screenshot).hexdigest(),
            'last_error': False
        }

        if changed_detected:
            logger.info(f"Change detected! SSIM score {ssim_score:.4f} < threshold {threshold}")
        else:
            logger.debug(f"No significant change. SSIM score {ssim_score:.4f} >= threshold {threshold}")

        return changed_detected, update_obj, self.screenshot
