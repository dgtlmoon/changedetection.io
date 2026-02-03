"""
Visual/screenshot change detection using fast image comparison algorithms.

This processor compares screenshots using OpenCV (cv2.absdiff),
which is 10-100x faster than SSIM while still detecting meaningful visual changes.
"""

import os
from pathlib import Path

processor_description = "Visual/Screenshot change detection (Fast)"
processor_name = "image_ssim_diff"
processor_weight = 2  # Lower weight = appears at top, heavier weight = appears lower (bottom)

# Processor capabilities
supports_visual_selector = True
supports_browser_steps = True
supports_text_filters_and_triggers = True
supports_request_type = True

PROCESSOR_CONFIG_NAME = f"{Path(__file__).parent.name}.json"

# Subprocess timeout settings
# Maximum time to wait for subprocess operations (seconds)
POLL_TIMEOUT_ABSOLUTE = int(os.getenv('OPENCV_SUBPROCESS_TIMEOUT', '20'))

# Template tracking filename
CROPPED_IMAGE_TEMPLATE_FILENAME = 'cropped_image_template.png'

SCREENSHOT_COMPARISON_THRESHOLD_OPTIONS = [
    ('200', 'Low sensitivity (only major changes)'),
    ('80', 'Medium sensitivity (moderate changes - recommended)'),
    ('20', 'High sensitivity (small changes)'),
    ('0', 'Very high sensitivity (any change)')
]

SCREENSHOT_COMPARISON_THRESHOLD_OPTIONS_DEFAULT=0.999
OPENCV_BLUR_SIGMA=float(os.getenv("OPENCV_BLUR_SIGMA", "3.0"))
