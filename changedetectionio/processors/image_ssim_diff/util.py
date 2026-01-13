"""
DEPRECATED: All multiprocessing functions have been removed.

The image_ssim_diff processor now uses LibVIPS via ImageDiffHandler abstraction,
which provides superior performance and memory efficiency through streaming
architecture and automatic threading.

All image operations are now handled by:
- imagehandler.py: Abstract base class defining the interface
- libvips_handler.py: LibVIPS implementation with streaming and threading

Historical note: This file previously contained multiprocessing workers for:
- Template matching (find_region_with_template_matching_isolated)
- Template regeneration (regenerate_template_isolated)
- Image cropping (crop_image_isolated, crop_pil_image_isolated)

These have been replaced by handler methods which are:
- Faster (no subprocess overhead)
- More memory efficient (LibVIPS streaming)
- Cleaner (no multiprocessing deadlocks)
- Better tested (no logger/forking issues)
"""
