"""
Core fast screenshot comparison processor.

This processor uses OpenCV or pixelmatch algorithms to detect visual changes
in screenshots. Both methods are dramatically faster than SSIM (10-100x speedup)
while still being effective at detecting meaningful changes.
"""

import hashlib
import os
import time
from loguru import logger
from changedetectionio import strtobool
from changedetectionio.processors import difference_detection_processor, SCREENSHOT_FORMAT_PNG
from changedetectionio.processors.exceptions import ProcessorException
from . import DEFAULT_COMPARISON_METHOD, DEFAULT_COMPARISON_THRESHOLD_OPENCV, DEFAULT_COMPARISON_THRESHOLD_PIXELMATCH, CROPPED_IMAGE_TEMPLATE_FILENAME
from .util import find_region_with_template_matching_isolated, regenerate_template_isolated, crop_image_isolated

name = 'Visual / Image screenshot change detection'
description = 'Compares screenshots using fast algorithms (OpenCV or pixelmatch), 10-100x faster than SSIM'
processor_weight = 2
list_badge_text = "Visual"

class perform_site_check(difference_detection_processor):
    """Fast screenshot comparison processor."""

    # Override to use PNG format for better image comparison (JPEG compression creates noise)
    #screenshot_format = SCREENSHOT_FORMAT_PNG

    def run_changedetection(self, watch):
        """
        Perform screenshot comparison using OpenCV or pixelmatch.

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
            logger.debug(f"Screenshot MD5 unchanged ({current_md5}), skipping comparison")
            raise checksumFromPreviousCheckWasTheSame()

        from PIL import Image
        import io

        # Use hardcoded comparison method (can be overridden via COMPARISON_METHOD env var)
        comparison_method = DEFAULT_COMPARISON_METHOD

        # Get threshold (per-watch > global > env default)
        threshold = watch.get('comparison_threshold')
        if not threshold or threshold == '':
            default_threshold = (
                DEFAULT_COMPARISON_THRESHOLD_OPENCV if comparison_method == 'opencv'
                else DEFAULT_COMPARISON_THRESHOLD_PIXELMATCH
            )
            threshold = self.datastore.data['settings']['application'].get('comparison_threshold', default_threshold)

        # Convert string to appropriate type
        try:
            threshold = float(threshold)
            # For pixelmatch, convert from 0-100 scale to 0-1 scale
            if comparison_method == 'pixelmatch':
                threshold = threshold / 100.0
        except (ValueError, TypeError):
            logger.warning(f"Invalid threshold value '{threshold}', using default")
            threshold = 30.0 if comparison_method == 'opencv' else 0.1

        # Convert current screenshot to PIL Image
        try:
            current_img = Image.open(io.BytesIO(self.screenshot))
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

                    # PIL crop uses (left, top, right, bottom)
                    crop_region = (
                        max(0, x),
                        max(0, y),
                        min(current_img.width, x + width),
                        min(current_img.height, y + height)
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

                                # PIL crop uses (left, top, right, bottom)
                                crop_region = (
                                    max(0, left),
                                    max(0, top),
                                    min(current_img.width, left + width),
                                    min(current_img.height, top + height)
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
                # Use subprocess isolation to crop image - ensures complete memory independence
                import io
                current_img_bytes = io.BytesIO()
                current_img.save(current_img_bytes, format='PNG')
                current_img_bytes_data = current_img_bytes.getvalue()

                cropped_bytes = crop_image_isolated(current_img_bytes_data, crop_region)
                if cropped_bytes:
                    cropped_current_img = Image.open(io.BytesIO(cropped_bytes))
                    cropped_current_img.load()
                    logger.debug(f"Cropped screenshot to {cropped_current_img.size} (region: {crop_region}) via subprocess")
                else:
                    logger.error("Subprocess crop failed")
                    crop_region = None
            except Exception as e:
                logger.error(f"Failed to crop screenshot: {e}")
                crop_region = None  # Disable cropping on error

        # Check if this is the first check (no previous history)
        history_keys = list(watch.history.keys())
        if len(history_keys) == 0:
            # First check - save baseline, no comparison
            logger.info(f"First check for watch {watch.get('uuid')} - saving baseline screenshot")

            # Close the PIL images before returning
            import gc
            current_img.close()
            del current_img
            if cropped_current_img:
                cropped_current_img.close()
                del cropped_current_img
            gc.collect()

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

            previous_img = Image.open(io.BytesIO(previous_screenshot_bytes))

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
                        # Use subprocess isolation for template regeneration
                        import io
                        prev_img_bytes = io.BytesIO()
                        previous_img.save(prev_img_bytes, format='PNG')
                        regenerate_template_isolated(
                            prev_img_bytes.getvalue(), original_crop_region, template_path
                        )

                    logger.debug("Template matching enabled - searching for region movement")
                    # Use subprocess isolation for template matching (most memory-intensive operation)
                    import io
                    curr_img_bytes = io.BytesIO()
                    current_img.save(curr_img_bytes, format='PNG')
                    with open(template_path, 'rb') as f:
                        template_bytes = f.read()
                    new_crop_region = find_region_with_template_matching_isolated(
                        curr_img_bytes.getvalue(), template_bytes, original_crop_region, search_tolerance=0.2
                    )

                    if new_crop_region:
                        old_region = original_crop_region
                        crop_region = new_crop_region
                        logger.info(f"Template matching: Region moved from {old_region} to {new_crop_region}")

                        # Update cropped image with new region using subprocess isolation
                        if cropped_current_img:
                            cropped_current_img.close()
                            del cropped_current_img
                        # Already have curr_img_bytes from template matching above
                        cropped_bytes = crop_image_isolated(curr_img_bytes.getvalue(), crop_region)
                        if cropped_bytes:
                            cropped_current_img = Image.open(io.BytesIO(cropped_bytes))
                            cropped_current_img.load()
                        else:
                            logger.error("Subprocess crop failed after template matching")
                    else:
                        logger.warning("Template matching: Could not find region, using original position")

                except Exception as e:
                    logger.warning(f"Template matching error (continuing with original position): {e}")

            # Crop previous image to the same region if cropping is enabled
            cropped_previous_img = None
            if crop_region:
                try:
                    # Crop and force independent buffer to break reference to parent image
                    cropped_previous_img = previous_img.crop(crop_region).copy()
                    cropped_previous_img.load()  # Force load into memory
                    logger.debug(f"Cropped previous screenshot to {cropped_previous_img.size}")
                except Exception as e:
                    logger.warning(f"Failed to crop previous screenshot: {e}")

            # Force garbage collection after cropping to free old image buffers
            import gc
            gc.collect()

        except Exception as e:
            logger.warning(f"Failed to load previous screenshot for comparison: {e}")
            # Clean up current images before returning
            import gc
            if 'current_img' in locals():
                current_img.close()
                del current_img
            if 'cropped_current_img' in locals() and cropped_current_img:
                cropped_current_img.close()
                del cropped_current_img
            gc.collect()

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
            if img_for_comparison_curr.size != img_for_comparison_prev.size:
                logger.info(f"Resizing images to match: {img_for_comparison_prev.size} -> {img_for_comparison_curr.size}")
                resized_img = img_for_comparison_prev.resize(img_for_comparison_curr.size, Image.Resampling.LANCZOS)
                # If we resized a cropped version, close the old cropped image before replacing
                if cropped_previous_img and img_for_comparison_prev is cropped_previous_img:
                    cropped_previous_img.close()
                    cropped_previous_img = resized_img
                img_for_comparison_prev = resized_img

            if comparison_method == 'pixelmatch':
                changed_detected, change_score = self._compare_pixelmatch(
                    img_for_comparison_prev, img_for_comparison_curr, threshold
                )
                logger.info(f"Pixelmatch: {change_score:.2f}% pixels different, threshold: {threshold*100:.0f}%")
            else:  # opencv (default)
                changed_detected, change_score = self._compare_opencv(
                    img_for_comparison_prev, img_for_comparison_curr, threshold
                )
                logger.info(f"OpenCV: {change_score:.2f}% pixels changed, threshold: {threshold:.0f}")

            # Explicitly close PIL images to free memory immediately
            import gc
            current_img.close()
            previous_img.close()
            del current_img
            del previous_img
            if cropped_current_img:
                cropped_current_img.close()
                del cropped_current_img
            if cropped_previous_img:
                cropped_previous_img.close()
                del cropped_previous_img
            del previous_screenshot_bytes  # Release the large bytes object

            # Force garbage collection to immediately release memory
            gc.collect()

        except Exception as e:
            logger.error(f"Failed to compare screenshots: {e}")
            # Ensure cleanup even on error
            for obj in ['current_img', 'previous_img', 'cropped_current_img', 'cropped_previous_img']:
                try:
                    locals()[obj].close()
                except (KeyError, NameError, AttributeError):
                    pass
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
            logger.info(f"Change detected using {comparison_method}! Score: {change_score:.2f}")
        else:
            logger.debug(f"No significant change using {comparison_method}. Score: {change_score:.2f}")
        logger.trace(f"Processed in {time.time() - now:.3f}s")

        return changed_detected, update_obj, self.screenshot

    def _compare_opencv(self, img_from, img_to, threshold):
        """
        Compare images using OpenCV cv2.absdiff method.

        This is the fastest method (50-100x faster than SSIM) and works well
        for detecting pixel-level changes with optional Gaussian blur to reduce
        sensitivity to minor rendering differences.

        Args:
            img_from: Previous PIL Image
            img_to: Current PIL Image
            threshold: Pixel difference threshold (0-255)

        Returns:
            tuple: (changed_detected, change_percentage)
        """
        import cv2
        import numpy as np
        import gc

        # Convert PIL images to numpy arrays
        arr_from = np.array(img_from)
        arr_to = np.array(img_to)

        # Convert to grayscale for faster comparison
        if len(arr_from.shape) == 3:
            gray_from = cv2.cvtColor(arr_from, cv2.COLOR_RGB2GRAY)
            gray_to = cv2.cvtColor(arr_to, cv2.COLOR_RGB2GRAY)
        else:
            gray_from = arr_from
            gray_to = arr_to

        # Release original arrays if we converted them
        if gray_from is not arr_from:
            del arr_from
            arr_from = None
        if gray_to is not arr_to:
            del arr_to
            arr_to = None

        # Optional: Apply Gaussian blur to reduce sensitivity to minor rendering differences
        # Controlled by environment variable, default sigma=0.8
        blur_sigma = float(os.getenv("OPENCV_BLUR_SIGMA", "0.8"))
        if blur_sigma > 0:
            gray_from = cv2.GaussianBlur(gray_from, (0, 0), blur_sigma)
            gray_to = cv2.GaussianBlur(gray_to, (0, 0), blur_sigma)

        # Calculate absolute difference
        diff = cv2.absdiff(gray_from, gray_to)

        # Apply threshold to create binary mask
        _, thresh = cv2.threshold(diff, threshold, 255, cv2.THRESH_BINARY)

        # Count changed pixels
        changed_pixels = np.count_nonzero(thresh)
        total_pixels = thresh.size
        change_percentage = (changed_pixels / total_pixels) * 100

        # Determine if change detected (if more than 0.1% of pixels changed)
        # This prevents triggering on single-pixel noise
        min_change_percentage = float(os.getenv("OPENCV_MIN_CHANGE_PERCENT", "0.1"))
        changed_detected = change_percentage > min_change_percentage

        # Explicit memory cleanup - mark large arrays for garbage collection
        if arr_from is not None:
            del arr_from
        if arr_to is not None:
            del arr_to
        del gray_from, gray_to
        del diff, thresh
        gc.collect()

        return changed_detected, change_percentage

    def _compare_pixelmatch(self, img_from, img_to, threshold):
        """
        Compare images using pixelmatch (C++17 implementation via pybind11).

        This method is 10-20x faster than SSIM and is specifically designed for
        screenshot comparison with anti-aliasing detection. It's particularly good
        at ignoring minor rendering differences while catching real changes.

        Args:
            img_from: Previous PIL Image
            img_to: Current PIL Image
            threshold: Color difference threshold (0-1, where 0 is most sensitive)

        Returns:
            tuple: (changed_detected, change_percentage)
        """
        try:
            from pybind11_pixelmatch import pixelmatch, Options
        except ImportError:
            logger.error("pybind11-pixelmatch not installed, falling back to OpenCV")
            return self._compare_opencv(img_from, img_to, threshold * 255)

        import numpy as np
        import gc

        # Track converted images so we can close them
        converted_img_from = None
        converted_img_to = None

        # Convert to RGB if not already
        if img_from.mode != 'RGB':
            converted_img_from = img_from.convert('RGB')
            img_from = converted_img_from
        if img_to.mode != 'RGB':
            converted_img_to = img_to.convert('RGB')
            img_to = converted_img_to

        # Convert to numpy arrays (pixelmatch expects RGBA format)
        arr_from = np.array(img_from)
        arr_to = np.array(img_to)

        # Add alpha channel (pixelmatch expects RGBA)
        alpha = None
        if arr_from.shape[2] == 3:
            alpha = np.ones((arr_from.shape[0], arr_from.shape[1], 1), dtype=np.uint8) * 255
            arr_from = np.concatenate([arr_from, alpha], axis=2)
            arr_to = np.concatenate([arr_to, alpha], axis=2)

        # Create diff output array (RGBA)
        diff_array = np.zeros_like(arr_from)

        # Configure pixelmatch options
        opts = Options()
        opts.threshold = threshold
        opts.includeAA = True  # Ignore anti-aliasing differences
        opts.alpha = 0.1       # Opacity of diff overlay

        # Run pixelmatch (returns number of mismatched pixels)
        width, height = img_from.size
        num_diff_pixels = pixelmatch(
            arr_from,
            arr_to,
            output=diff_array,
            options=opts
        )

        # Calculate change percentage
        total_pixels = width * height
        change_percentage = (num_diff_pixels / total_pixels) * 100

        # Determine if change detected (if more than 0.1% of pixels changed)
        min_change_percentage = float(os.getenv("PIXELMATCH_MIN_CHANGE_PERCENT", "0.1"))
        changed_detected = change_percentage > min_change_percentage

        # Explicit memory cleanup - close converted images and delete arrays
        if converted_img_from is not None:
            converted_img_from.close()
        if converted_img_to is not None:
            converted_img_to.close()
        del arr_from, arr_to
        del diff_array
        if alpha is not None:
            del alpha
        gc.collect()

        return changed_detected, change_percentage
