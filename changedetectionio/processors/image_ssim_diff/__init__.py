"""
Visual/screenshot change detection using SSIM (Structural Similarity Index).

This processor compares screenshots using the SSIM algorithm, which is superior to
simple pixel comparison for detecting meaningful visual changes while ignoring
antialiasing, minor rendering differences, and other insignificant pixel variations.
"""

processor_description = "Visual/screenshot change detection using SSIM (Structural Similarity Index)"
processor_name = "image_ssim_diff"
