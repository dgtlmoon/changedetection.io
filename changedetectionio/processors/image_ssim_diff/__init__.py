"""
Visual/screenshot change detection using fast image comparison algorithms.

This processor compares screenshots using OpenCV (cv2.absdiff) or pixelmatch algorithms,
which are 10-100x faster than SSIM while still detecting meaningful visual changes
and handling antialiasing differences.
"""

import os

processor_description = "Visual/Screenshot change detection (Fast)"
processor_name = "image_ssim_diff"

# Default comparison settings
DEFAULT_COMPARISON_METHOD = os.getenv('COMPARISON_METHOD', 'opencv')
DEFAULT_COMPARISON_THRESHOLD_OPENCV = float(os.getenv('COMPARISON_THRESHOLD_OPENCV', '30'))
DEFAULT_COMPARISON_THRESHOLD_PIXELMATCH = float(os.getenv('COMPARISON_THRESHOLD_PIXELMATCH', '10'))
