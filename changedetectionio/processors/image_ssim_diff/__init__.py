"""
Visual/screenshot change detection using fast image comparison algorithms.

This processor compares screenshots using OpenCV (cv2.absdiff),
which is 10-100x faster than SSIM while still detecting meaningful visual changes.
"""

import os

processor_description = "Visual/Screenshot change detection (Fast)"
processor_name = "image_ssim_diff"
processor_weight = 2  # Lower weight = appears at top, heavier weight = appears lower (bottom)

# Default comparison settings
DEFAULT_COMPARISON_THRESHOLD_OPENCV = float(os.getenv('COMPARISON_THRESHOLD_OPENCV', '30'))

# Subprocess timeout settings
# Maximum time to wait for subprocess operations (seconds)
POLL_TIMEOUT_ABSOLUTE = int(os.getenv('OPENCV_SUBPROCESS_TIMEOUT', '20'))

# Template tracking filename
CROPPED_IMAGE_TEMPLATE_FILENAME = 'cropped_image_template.png'
