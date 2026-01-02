"""
Preview rendering for SSIM screenshot processor.

Renders images properly in the browser instead of showing raw bytes.
"""

from flask_babel import gettext
from loguru import logger


def get_asset(asset_name, watch, datastore, request):
    """
    Get processor-specific binary assets for preview streaming.

    This function supports serving images as separate HTTP responses instead
    of embedding them as base64 in the HTML template, solving memory issues
    with large screenshots.

    Supported assets:
    - 'screenshot': The screenshot for the specified version

    Args:
        asset_name: Name of the asset to retrieve ('screenshot')
        watch: Watch object
        datastore: Datastore object
        request: Flask request (for version query param)

    Returns:
        tuple: (binary_data, content_type, cache_control_header) or None if not found
    """
    if asset_name != 'screenshot':
        return None

    versions = list(watch.history.keys())
    if len(versions) == 0:
        return None

    # Get the version from query string (default: latest)
    preferred_version = request.args.get('version')
    timestamp = versions[-1]
    if preferred_version and preferred_version in versions:
        timestamp = preferred_version

    try:
        screenshot_bytes = watch.get_history_snapshot(timestamp=timestamp)

        # Verify we got bytes (should always be bytes for image files)
        if not isinstance(screenshot_bytes, bytes):
            logger.error(f"Expected bytes but got {type(screenshot_bytes)} for screenshot at {timestamp}")
            return None

        # Detect image format using puremagic (same as Watch.py)
        try:
            import puremagic
            detections = puremagic.magic_string(screenshot_bytes[:2048])
            if detections:
                mime_type = detections[0].mime_type
                logger.trace(f"Detected MIME type: {mime_type}")
            else:
                mime_type = 'image/png'  # Default fallback
        except Exception as e:
            logger.warning(f"puremagic detection failed: {e}, using 'image/png' fallback")
            mime_type = 'image/png'

        return (screenshot_bytes, mime_type, 'public, max-age=10')

    except Exception as e:
        logger.error(f"Failed to load screenshot for preview asset: {e}")
        return None


def render(watch, datastore, request, url_for, render_template, flash, redirect):
    """
    Render the preview page for screenshot watches.

    Args:
        watch: Watch object
        datastore: Datastore object
        request: Flask request
        url_for: Flask url_for function
        render_template: Flask render_template function
        flash: Flask flash function
        redirect: Flask redirect function

    Returns:
        Rendered template or redirect
    """
    versions = list(watch.history.keys())

    if len(versions) == 0:
        flash(gettext("Preview unavailable - No snapshots captured yet"), "error")
        return redirect(url_for('watchlist.index'))

    # Get the version to display (default: latest)
    preferred_version = request.args.get('version')
    timestamp = versions[-1]
    if preferred_version and preferred_version in versions:
        timestamp = preferred_version

    # Render custom template for image preview
    # Screenshot is now served via separate /processor-asset/ endpoint instead of base64
    # This significantly reduces memory usage by not embedding large images in HTML
    return render_template(
        'image_ssim_diff/preview.html',
        watch=watch,
        uuid=watch.get('uuid'),
        versions=versions,
        timestamp=timestamp,
        current_diff_url=watch['url']
    )
