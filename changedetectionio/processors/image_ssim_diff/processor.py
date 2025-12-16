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
from changedetectionio.processors import difference_detection_processor
from changedetectionio.processors.exceptions import ProcessorException
from . import DEFAULT_COMPARISON_METHOD, DEFAULT_COMPARISON_THRESHOLD_OPENCV, DEFAULT_COMPARISON_THRESHOLD_PIXELMATCH

name = 'Visual/Screenshot change detection (Fast)'
description = 'Compares screenshots using fast algorithms (OpenCV or pixelmatch), 10-100x faster than SSIM'


class perform_site_check(difference_detection_processor):
    """Fast screenshot comparison processor."""

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
        import numpy as np

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

        # Check if visual selector (include_filters) is set for region-based comparison
        include_filters = watch.get('include_filters', [])
        crop_region = None

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

        # Crop the current image if region was found
        if crop_region:
            try:
                current_img = current_img.crop(crop_region)

                # Update self.screenshot to the cropped version for history storage
                crop_buffer = io.BytesIO()
                current_img.save(crop_buffer, format='PNG')
                self.screenshot = crop_buffer.getvalue()

                logger.debug(f"Cropped screenshot to {current_img.size} (region: {crop_region})")
            except Exception as e:
                logger.error(f"Failed to crop screenshot: {e}")
                crop_region = None  # Disable cropping on error

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

            # Crop previous image to the same region if visual selector is enabled
            if crop_region:
                try:
                    previous_img = previous_img.crop(crop_region)
                    logger.debug(f"Cropped previous screenshot to {previous_img.size}")
                except Exception as e:
                    logger.warning(f"Failed to crop previous screenshot: {e}")

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

            logger.trace(f"Processed in {time.time() - now:.3f}s")
            return False, update_obj, self.screenshot

        # Perform comparison based on selected method
        try:
            # Ensure images are the same size
            if current_img.size != previous_img.size:
                logger.info(f"Resizing images to match: {previous_img.size} -> {current_img.size}")
                previous_img = previous_img.resize(current_img.size, Image.Resampling.LANCZOS)

            if comparison_method == 'pixelmatch':
                changed_detected, change_score = self._compare_pixelmatch(
                    previous_img, current_img, threshold
                )
                logger.info(f"Pixelmatch: {change_score:.2f}% pixels different, threshold: {threshold*100:.0f}%")
            else:  # opencv (default)
                changed_detected, change_score = self._compare_opencv(
                    previous_img, current_img, threshold
                )
                logger.info(f"OpenCV: {change_score:.2f}% pixels changed, threshold: {threshold:.0f}")

            # Explicitly close PIL images to free memory immediately
            current_img.close()
            previous_img.close()
            del current_img
            del previous_img
            del previous_screenshot_bytes  # Release the large bytes object

        except Exception as e:
            logger.error(f"Failed to compare screenshots: {e}")
            # Ensure cleanup even on error
            for obj in ['current_img', 'previous_img']:
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
        del arr_from, arr_to
        del gray_from, gray_to
        del diff, thresh

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

        # Convert to RGB if not already
        if img_from.mode != 'RGB':
            img_from = img_from.convert('RGB')
        if img_to.mode != 'RGB':
            img_to = img_to.convert('RGB')

        # Convert to numpy arrays (pixelmatch expects RGBA format)
        arr_from = np.array(img_from)
        arr_to = np.array(img_to)

        # Add alpha channel (pixelmatch expects RGBA)
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

        # Explicit memory cleanup - mark large arrays for garbage collection
        del arr_from, arr_to
        del diff_array
        if 'alpha' in locals():
            del alpha

        return changed_detected, change_percentage
