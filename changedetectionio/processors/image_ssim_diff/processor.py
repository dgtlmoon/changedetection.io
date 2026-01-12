"""
Core fast screenshot comparison processor.

Uses OpenCV with subprocess isolation for high-performance, low-memory
image processing. All operations run in isolated subprocesses for complete
memory cleanup and stability.
"""

import hashlib
import time
from loguru import logger
from changedetectionio.processors.exceptions import ProcessorException
from . import SCREENSHOT_COMPARISON_THRESHOLD_OPTIONS_DEFAULT, PROCESSOR_CONFIG_NAME, OPENCV_BLUR_SIGMA
from ..base import difference_detection_processor, SCREENSHOT_FORMAT_PNG

# All image operations now use OpenCV via isolated_opencv subprocess handler
# Template matching temporarily disabled pending OpenCV implementation

# Translation marker for extraction
def _(x): return x
name = _('Visual / Image screenshot change detection')
description = _('Compares screenshots using fast OpenCV algorithm, 10-100x faster than SSIM')
del _
processor_weight = 2
list_badge_text = "Visual"

class perform_site_check(difference_detection_processor):
    """Fast screenshot comparison processor using OpenCV."""

    # Override to use PNG format for better image comparison (JPEG compression creates noise)
    screenshot_format = SCREENSHOT_FORMAT_PNG

    def run_changedetection(self, watch):
        """
        Perform screenshot comparison using OpenCV subprocess handler.

        Returns:
            tuple: (changed_detected, update_obj, screenshot_bytes)
        """
        now = time.time()
        # Get the current screenshot
        if not self.fetcher.screenshot:
            raise ProcessorException(
                message="No screenshot available. Ensure the watch is configured to use a real browser.",
                url=watch.get('url')
            )
        self.screenshot = self.fetcher.screenshot
        self.xpath_data = self.fetcher.xpath_data

        # Quick MD5 check - skip expensive comparison if images are identical
        from changedetectionio.content_fetchers.exceptions import checksumFromPreviousCheckWasTheSame
        current_md5 = hashlib.md5(self.screenshot).hexdigest()
        previous_md5 = watch.get('previous_md5')
        if previous_md5 and current_md5 == previous_md5:
            logger.debug(f"UUID: {watch.get('uuid')} - Screenshot MD5 unchanged ({current_md5}), skipping comparison")
            raise checksumFromPreviousCheckWasTheSame()
        else:
            logger.debug(f"UUID: {watch.get('uuid')} - Screenshot MD5 changed")



        # Check if bounding box is set (for drawn area mode)
        # Read from processor-specific config JSON file (named after processor)
        crop_region = None

        processor_config = self.get_extra_watch_config(PROCESSOR_CONFIG_NAME)
        bounding_box = processor_config.get('bounding_box') if processor_config else None


        # Get pixel difference threshold sensitivity (per-watch > global)
        # This controls how different a pixel must be (0-255 scale) to count as "changed"
        pixel_difference_threshold_sensitivity = processor_config.get('pixel_difference_threshold_sensitivity')
        if not pixel_difference_threshold_sensitivity:
            pixel_difference_threshold_sensitivity = self.datastore.data['settings']['application'].get('pixel_difference_threshold_sensitivity', SCREENSHOT_COMPARISON_THRESHOLD_OPTIONS_DEFAULT)
        try:
            pixel_difference_threshold_sensitivity = int(pixel_difference_threshold_sensitivity)
        except (ValueError, TypeError):
            logger.warning(f"Invalid pixel_difference_threshold_sensitivity value '{pixel_difference_threshold_sensitivity}', using default")
            pixel_difference_threshold_sensitivity = SCREENSHOT_COMPARISON_THRESHOLD_OPTIONS_DEFAULT


        # Get minimum change percentage (per-watch > global > env var default)
        # This controls what percentage of pixels must change to trigger a detection
        min_change_percentage = processor_config.get('min_change_percentage')
        if not min_change_percentage:
            min_change_percentage = self.datastore.data['settings']['application'].get('min_change_percentage', 1)
        try:
            min_change_percentage = int(min_change_percentage)
        except (ValueError, TypeError):
            logger.warning(f"Invalid min_change_percentage value '{min_change_percentage}', using default 0.1")
            min_change_percentage = 1

        # Template matching for tracking content movement
        template_matching_enabled = processor_config.get('auto_track_region', False) #@@todo disabled for now

        if bounding_box:
            try:
                # Parse bounding box: "x,y,width,height"
                parts = [int(p.strip()) for p in bounding_box.split(',')]
                if len(parts) == 4:
                    x, y, width, height = parts
                    # Crop uses (left, top, right, bottom)
                    crop_region = (max(0, x), max(0, y), x + width, y + height)
                    logger.info(f"UUID: {watch.get('uuid')} - Bounding box enabled: cropping to region {crop_region} (x={x}, y={y}, w={width}, h={height})")
                else:
                    logger.warning(f"UUID: {watch.get('uuid')} - Invalid bounding box format: {bounding_box} (expected 4 values)")
            except Exception as e:
                logger.warning(f"UUID: {watch.get('uuid')} - Failed to parse bounding box '{bounding_box}': {e}")

        # If no bounding box, check if visual selector (include_filters) is set for region-based comparison
        if not crop_region:
            include_filters = watch.get('include_filters', [])

            if include_filters and len(include_filters) > 0:
                # Get the first filter to use for cropping
                first_filter = include_filters[0].strip()

                if first_filter and self.xpath_data:
                    try:
                        import json
                        # xpath_data is JSON string from browser
                        xpath_data_obj = json.loads(self.xpath_data) if isinstance(self.xpath_data, str) else self.xpath_data

                        # Find the bounding box for the first filter
                        for element in xpath_data_obj.get('size_pos', []):
                            # Match the filter with the element's xpath
                            if element.get('xpath') == first_filter and element.get('highlight_as_custom_filter'):
                                # Found the element - extract crop coordinates
                                left = element.get('left', 0)
                                top = element.get('top', 0)
                                width = element.get('width', 0)
                                height = element.get('height', 0)

                                # Crop uses (left, top, right, bottom)
                                crop_region = (max(0, left), max(0, top), left + width, top + height)

                                logger.info(f"UUID: {watch.get('uuid')} - Visual selector enabled: cropping to region {crop_region} for filter: {first_filter}")
                                break

                    except Exception as e:
                        logger.warning(f"UUID: {watch.get('uuid')} - Failed to parse xpath_data for visual selector: {e}")

        # Store original crop region for template matching
        original_crop_region = crop_region

        # Check if this is the first check (no previous history)
        history_keys = list(watch.history.keys())
        if len(history_keys) == 0:
            # First check - save baseline, no comparison
            logger.info(f"UUID: {watch.get('uuid')} - First check for watch {watch.get('uuid')} - saving baseline screenshot")

            # LibVIPS uses automatic reference counting - no explicit cleanup needed
            update_obj = {
                'previous_md5': hashlib.md5(self.screenshot).hexdigest(),
                'last_error': False
            }
            logger.trace(f"Processed in {time.time() - now:.3f}s")
            return False, update_obj, self.screenshot

        # Get previous screenshot bytes from history
        previous_timestamp = history_keys[-1]
        previous_screenshot_bytes = watch.get_history_snapshot(timestamp=previous_timestamp)

        # Screenshots are stored as PNG, so this should be bytes
        if isinstance(previous_screenshot_bytes, str):
            # If it's a string (shouldn't be for screenshots, but handle it)
            previous_screenshot_bytes = previous_screenshot_bytes.encode('utf-8')

        # Template matching is temporarily disabled pending OpenCV implementation
        # crop_region calculated above will be used as-is

        # Perform comparison in isolated subprocess to prevent memory leaks
        try:
            from .image_handler import isolated_opencv as process_screenshot_handler

# stuff in watch doesnt need to be there
            logger.debug(f"UUID: {watch.get('uuid')} - Starting isolated subprocess comparison (crop_region={crop_region})")

            # Compare using isolated subprocess with OpenCV (async-safe to avoid blocking event loop)
            # Pass raw bytes and crop region - subprocess handles all image operations
            import asyncio
            import threading

            # Async-safe wrapper: runs coroutine in new thread with its own event loop
            # This prevents blocking the async update worker's event loop
            def run_async_in_thread():
                return asyncio.run(
                    process_screenshot_handler.compare_images_isolated(
                        img_bytes_from=previous_screenshot_bytes,
                        img_bytes_to=self.screenshot,
                        pixel_difference_threshold=pixel_difference_threshold_sensitivity,
                        blur_sigma=OPENCV_BLUR_SIGMA,
                        crop_region=crop_region  # Pass crop region for isolated cropping
                    )
                )

            # Run in thread to avoid blocking event loop when called from async update worker
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

            # Subprocess returns only the change score - we decide if it's a "change"
            change_score = result_container[0]
            if change_score is None:
                raise RuntimeError("Image comparison subprocess returned no result")

            changed_detected = change_score > min_change_percentage
            logger.info(f"UUID: {watch.get('uuid')} -  {process_screenshot_handler.IMPLEMENTATION_NAME}: {change_score:.2f}% pixels changed, pixel_diff_threshold_sensitivity: {pixel_difference_threshold_sensitivity:.0f} score={change_score:.2f}%, min_change_threshold={min_change_percentage}%")

        except Exception as e:
            logger.error(f"UUID: {watch.get('uuid')} - Failed to compare screenshots: {e}")
            logger.trace(f"UUID: {watch.get('uuid')} - Processed in {time.time() - now:.3f}s")

            raise ProcessorException(
                message=f"UUID: {watch.get('uuid')} - Screenshot comparison failed: {e}",
                url=watch.get('url')
            )

        # Return results
        update_obj = {
            'previous_md5': hashlib.md5(self.screenshot).hexdigest(),
            'last_error': False
        }

        if changed_detected:
            logger.info(f"UUID: {watch.get('uuid')} - Change detected using OpenCV! Score: {change_score:.2f}")
        else:
            logger.debug(f"UUID: {watch.get('uuid')} - No significant change using OpenCV. Score: {change_score:.2f}")
        logger.trace(f"UUID: {watch.get('uuid')} - Processed in {time.time() - now:.3f}s")

        return changed_detected, update_obj, self.screenshot

