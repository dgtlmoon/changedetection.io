"""
Visual/screenshot change detection using fast image comparison algorithms.

This processor compares screenshots using OpenCV (cv2.absdiff),
which is 10-100x faster than SSIM while still detecting meaningful visual changes.
"""

import os

processor_description = "Visual/Screenshot change detection (Fast)"
processor_name = "image_ssim_diff"
processor_weight = 2  # Lower weight = appears at top, heavier weight = appears lower (bottom)


# Subprocess timeout settings
# Maximum time to wait for subprocess operations (seconds)
POLL_TIMEOUT_ABSOLUTE = int(os.getenv('OPENCV_SUBPROCESS_TIMEOUT', '20'))

# Template tracking filename
CROPPED_IMAGE_TEMPLATE_FILENAME = 'cropped_image_template.png'

SCREENSHOT_COMPARISON_THRESHOLD_OPTIONS = [
    ('0.75', 'Low sensitivity (only major changes)'),
    ('0.85', 'Medium sensitivity (moderate changes)'),
    ('0.96', 'High sensitivity (small changes)'),
    ('0.999', 'Very high sensitivity (any change)')
]
SCREENSHOT_COMPARISON_THRESHOLD_OPTIONS_DEFAULT=0.999
