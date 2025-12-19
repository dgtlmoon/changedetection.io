"""
Core fast screenshot comparison processor.

Fully refactored to use LibVIPS via ImageDiffHandler abstraction for
high-performance, low-memory image processing with automatic threading.
All PIL and multiprocessing code has been removed.
"""

import hashlib
import os
import time
from loguru import logger
from changedetectionio import strtobool
from changedetectionio.processors import difference_detection_processor, SCREENSHOT_FORMAT_PNG
from changedetectionio.processors.exceptions import ProcessorException
from . import DEFAULT_COMPARISON_THRESHOLD_OPENCV, CROPPED_IMAGE_TEMPLATE_FILENAME

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

name = 'Visual / Image screenshot change detection'
description = 'Compares screenshots using fast OpenCV algorithm, 10-100x faster than SSIM'
processor_weight = 2
list_badge_text = "Visual"

class perform_site_check(difference_detection_processor):
    """Fast screenshot comparison processor using OpenCV."""

    # Override to use PNG format for better image comparison (JPEG compression creates noise)
    #screenshot_format = SCREENSHOT_FORMAT_PNG

    def run_changedetection(self, watch):
        """
        Perform screenshot comparison using LibVIPS handler.

        Returns:
            tuple: (changed_detected, update_obj, screenshot_bytes)
        """
        # Check if handler is available
        if not HANDLER_AVAILABLE:
            raise ProcessorException(
                message=f"Screenshot comparison is not available: {IMPORT_ERROR}",
                url=watch.get('url')
            )

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
            logger.debug(f"Screenshot MD5 unchanged ({current_md5}), skipping comparison")
            raise checksumFromPreviousCheckWasTheSame()

        # Initialize image handler
        handler = LibvipsImageDiffHandler()

        # Get threshold (per-watch > global > env default)
        threshold = watch.get('comparison_threshold')
        if not threshold or threshold == '':
            threshold = self.datastore.data['settings']['application'].get('comparison_threshold', DEFAULT_COMPARISON_THRESHOLD_OPENCV)

        # Convert string to appropriate type
        try:
            threshold = float(threshold)
        except (ValueError, TypeError):
            logger.warning(f"Invalid threshold value '{threshold}', using default")
            threshold = 30.0

        # Load current screenshot using handler
        try:
            current_img = handler.load_from_bytes(self.screenshot)
        except Exception as e:
            raise ProcessorException(
                message=f"Failed to load current screenshot: {e}",
                url=watch.get('url')
            )

        # Check if bounding box is set (for drawn area mode)
        # Read from processor-specific config JSON file (named after processor)
        crop_region = None
        # Automatically use the processor name from watch config as filename
        processor_name = watch.get('processor', 'default')
        config_filename = f'{processor_name}.json'
        processor_config = self.get_extra_watch_config(config_filename) if self.get_extra_watch_config(config_filename) else {}
        bounding_box = processor_config.get('bounding_box') if processor_config else None

        # Template matching for tracking content movement
        template_matching_enabled = processor_config.get('auto_track_region', False)

        if bounding_box:
            try:
                # Parse bounding box: "x,y,width,height"
                parts = [int(p.strip()) for p in bounding_box.split(',')]
                if len(parts) == 4:
                    x, y, width, height = parts

                    # Get image dimensions via handler
                    img_width, img_height = handler.get_dimensions(current_img)

                    # Crop uses (left, top, right, bottom)
                    crop_region = (
                        max(0, x),
                        max(0, y),
                        min(img_width, x + width),
                        min(img_height, y + height)
                    )

                    logger.info(f"Bounding box enabled: cropping to region {crop_region} (x={x}, y={y}, w={width}, h={height})")
                else:
                    logger.warning(f"Invalid bounding box format: {bounding_box} (expected 4 values)")
            except Exception as e:
                logger.warning(f"Failed to parse bounding box '{bounding_box}': {e}")

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

                                # Get image dimensions via handler
                                img_width, img_height = handler.get_dimensions(current_img)

                                # Crop uses (left, top, right, bottom)
                                crop_region = (
                                    max(0, left),
                                    max(0, top),
                                    min(img_width, left + width),
                                    min(img_height, top + height)
                                )

                                logger.info(f"Visual selector enabled: cropping to region {crop_region} for filter: {first_filter}")
                                break

                    except Exception as e:
                        logger.warning(f"Failed to parse xpath_data for visual selector: {e}")

        # Crop the current image if region was found (for comparison only, keep full screenshot for history)
        cropped_current_img = None
        original_crop_region = crop_region  # Store original for template matching

        if crop_region:
            try:
                # Crop using handler
                left, top, right, bottom = crop_region
                cropped_current_img = handler.crop(current_img, left, top, right, bottom)
                w, h = handler.get_dimensions(cropped_current_img)
                logger.debug(f"Cropped screenshot to {w}x{h} (region: {crop_region})")
            except Exception as e:
                logger.error(f"Failed to crop screenshot: {e}")
                crop_region = None  # Disable cropping on error

        # Check if this is the first check (no previous history)
        history_keys = list(watch.history.keys())
        if len(history_keys) == 0:
            # First check - save baseline, no comparison
            logger.info(f"First check for watch {watch.get('uuid')} - saving baseline screenshot")

            # LibVIPS uses automatic reference counting - no explicit cleanup needed
            update_obj = {
                'previous_md5': hashlib.md5(self.screenshot).hexdigest(),
                'last_error': False
            }
            logger.trace(f"Processed in {time.time() - now:.3f}s")
            return False, update_obj, self.screenshot

        # Get previous screenshot from history
        try:
            previous_timestamp = history_keys[-1]
            previous_screenshot_bytes = watch.get_history_snapshot(timestamp=previous_timestamp)

            # Screenshots are stored as PNG, so this should be bytes
            if isinstance(previous_screenshot_bytes, str):
                # If it's a string (shouldn't be for screenshots, but handle it)
                previous_screenshot_bytes = previous_screenshot_bytes.encode('utf-8')

            # Load previous image using handler
            previous_img = handler.load_from_bytes(previous_screenshot_bytes)

            # Template matching: If enabled, search for content that may have moved
            # Check if feature is globally enabled via ENV var
            feature_enabled = strtobool(os.getenv('ENABLE_TEMPLATE_TRACKING', 'True'))
            # Check if auto-tracking is enabled for this specific watch (determined by feature analysis)
            auto_track_enabled = template_matching_enabled

            if feature_enabled and auto_track_enabled and original_crop_region:
                try:
                    # Check if template exists, if not regenerate from previous snapshot
                    template_path = os.path.join(watch.watch_data_dir, CROPPED_IMAGE_TEMPLATE_FILENAME)
                    if not os.path.isfile(template_path):
                        logger.info("Template file missing, regenerating from previous snapshot")
                        # Use handler to save template
                        handler.save_template(previous_img, original_crop_region, template_path)

                    logger.debug("Template matching enabled - searching for region movement")
                    # Load template and perform matching using handler
                    template_img = handler.load_from_bytes(open(template_path, 'rb').read())
                    new_crop_region = handler.find_template(
                        current_img, template_img, original_crop_region, search_tolerance=0.2
                    )

                    if new_crop_region:
                        old_region = original_crop_region
                        crop_region = new_crop_region
                        logger.info(f"Template matching: Region moved from {old_region} to {new_crop_region}")

                        # Update cropped image with new region
                        left, top, right, bottom = crop_region
                        cropped_current_img = handler.crop(current_img, left, top, right, bottom)
                    else:
                        logger.warning("Template matching: Could not find region, using original position")

                except Exception as e:
                    logger.warning(f"Template matching error (continuing with original position): {e}")

            # Crop previous image to the same region if cropping is enabled
            cropped_previous_img = None
            if crop_region:
                try:
                    # Crop using handler
                    left, top, right, bottom = crop_region
                    cropped_previous_img = handler.crop(previous_img, left, top, right, bottom)
                    w, h = handler.get_dimensions(cropped_previous_img)
                    logger.debug(f"Cropped previous screenshot to {w}x{h}")
                except Exception as e:
                    logger.warning(f"Failed to crop previous screenshot: {e}")

        except Exception as e:
            logger.warning(f"Failed to load previous screenshot for comparison: {e}")

            # LibVIPS uses automatic reference counting - no explicit cleanup needed
            # If we can't load previous, treat as first check
            update_obj = {
                'previous_md5': hashlib.md5(self.screenshot).hexdigest(),
                'last_error': False
            }

            logger.trace(f"Processed in {time.time() - now:.3f}s")
            return False, update_obj, self.screenshot

        # Perform comparison based on selected method
        try:
            # Use cropped versions if available, otherwise use full images
            img_for_comparison_prev = cropped_previous_img if cropped_previous_img else previous_img
            img_for_comparison_curr = cropped_current_img if cropped_current_img else current_img

            # Ensure images are the same size
            w_curr, h_curr = handler.get_dimensions(img_for_comparison_curr)
            w_prev, h_prev = handler.get_dimensions(img_for_comparison_prev)

            if (w_curr, h_curr) != (w_prev, h_prev):
                logger.info(f"Resizing images to match: {w_prev}x{h_prev} -> {w_curr}x{h_curr}")
                img_for_comparison_prev = handler.resize(img_for_comparison_prev, w_curr, h_curr)
                # Update reference if we resized the cropped version
                if cropped_previous_img and img_for_comparison_prev is cropped_previous_img:
                    cropped_previous_img = img_for_comparison_prev

            # Use handler for fast screenshot comparison
            changed_detected, change_score = self._compare_handler(
                handler, img_for_comparison_prev, img_for_comparison_curr, threshold
            )
            logger.info(f"LibVIPS: {change_score:.2f}% pixels changed, threshold: {threshold:.0f}")

            # LibVIPS uses automatic reference counting - no explicit cleanup needed

        except Exception as e:
            logger.error(f"Failed to compare screenshots: {e}")
            logger.trace(f"Processed in {time.time() - now:.3f}s")

            raise ProcessorException(
                message=f"Screenshot comparison failed: {e}",
                url=watch.get('url')
            )

        # Return results
        update_obj = {
            'previous_md5': hashlib.md5(self.screenshot).hexdigest(),
            'last_error': False
        }

        if changed_detected:
            logger.info(f"Change detected using OpenCV! Score: {change_score:.2f}")
        else:
            logger.debug(f"No significant change using OpenCV. Score: {change_score:.2f}")
        logger.trace(f"Processed in {time.time() - now:.3f}s")

        return changed_detected, update_obj, self.screenshot

    def _compare_handler(self, handler, img_from, img_to, threshold):
        """
        Compare images using ImageDiffHandler (LibVIPS).

        Uses LibVIPS streaming architecture for high-performance, low-memory
        comparison with automatic threading.

        Args:
            handler: ImageDiffHandler instance
            img_from: Previous handler image
            img_to: Current handler image
            threshold: Pixel difference threshold (0-255)

        Returns:
            tuple: (changed_detected, change_percentage)
        """
        try:
            # Convert to grayscale for faster comparison
            gray_from = handler.to_grayscale(img_from)
            gray_to = handler.to_grayscale(img_to)

            # Optional: Apply Gaussian blur to reduce sensitivity to minor rendering differences
            # Controlled by environment variable, default sigma=0.8
            blur_sigma = float(os.getenv("OPENCV_BLUR_SIGMA", "0.8"))
            if blur_sigma > 0:
                gray_from = handler.gaussian_blur(gray_from, blur_sigma)
                gray_to = handler.gaussian_blur(gray_to, blur_sigma)

            # Calculate absolute difference
            diff = handler.absolute_difference(gray_from, gray_to)

            # Release grayscale images
            del gray_from, gray_to

            # Apply threshold and get change percentage
            change_percentage, _ = handler.threshold(diff, int(threshold))

            # Release diff image
            del diff

            # Determine if change detected (if more than 0.1% of pixels changed)
            # This prevents triggering on single-pixel noise
            min_change_percentage = float(os.getenv("OPENCV_MIN_CHANGE_PERCENT", "0.1"))
            changed_detected = change_percentage > min_change_percentage

            return changed_detected, change_percentage

        finally:
            # Force Python garbage collection
            try:
                import gc
                gc.collect()
            except:
                pass

