"""
Favicon utilities for changedetection.io
Handles favicon MIME type detection with caching
"""

from functools import lru_cache


@lru_cache(maxsize=1000)
def get_favicon_mime_type(filepath):
    """
    Detect MIME type of favicon by reading file content using puremagic.
    Results are cached to avoid repeatedly reading the same files.

    Args:
        filepath: Full path to the favicon file

    Returns:
        MIME type string (e.g., 'image/png')
    """
    mime = None

    try:
        import puremagic
        with open(filepath, 'rb') as f:
            content_bytes = f.read(200)  # Read first 200 bytes

        detections = puremagic.magic_string(content_bytes)
        if detections:
            mime = detections[0].mime_type
    except Exception:
        pass

    # Fallback to mimetypes if puremagic fails
    if not mime:
        import mimetypes
        mime, _ = mimetypes.guess_type(filepath)

    # Final fallback based on extension
    if not mime:
        mime = 'image/x-icon' if filepath.endswith('.ico') else 'image/png'

    return mime
