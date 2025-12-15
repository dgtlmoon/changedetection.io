"""
Preview rendering for SSIM screenshot processor.

Renders images properly in the browser instead of showing raw bytes.
"""

import base64
from loguru import logger


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
        flash("Preview unavailable - No snapshots captured yet", "error")
        return redirect(url_for('watchlist.index'))

    # Get the version to display (default: latest)
    preferred_version = request.args.get('version')
    timestamp = versions[-1]
    if preferred_version and preferred_version in versions:
        timestamp = preferred_version

    # Load screenshot from history
    try:
        screenshot_bytes = watch.get_history_snapshot(timestamp=timestamp)

        # Convert to bytes if needed (should already be bytes for screenshots)
        if isinstance(screenshot_bytes, str):
            screenshot_bytes = screenshot_bytes.encode('utf-8')

        # Detect image format
        if screenshot_bytes[:8] == b'\x89PNG\r\n\x1a\n':
            mime_type = 'image/png'
        elif screenshot_bytes[:3] == b'\xff\xd8\xff':
            mime_type = 'image/jpeg'
        elif screenshot_bytes[:6] in (b'GIF87a', b'GIF89a'):
            mime_type = 'image/gif'
        elif screenshot_bytes[:4] == b'RIFF' and screenshot_bytes[8:12] == b'WEBP':
            mime_type = 'image/webp'
        else:
            mime_type = 'image/png'  # Default fallback

        # Convert to base64 for embedding in HTML
        img_b64 = base64.b64encode(screenshot_bytes).decode('utf-8')

    except Exception as e:
        logger.error(f"Failed to load screenshot: {e}")
        flash(f"Failed to load screenshot: {e}", "error")
        return redirect(url_for('watchlist.index'))

    # Render custom template for image preview
    # Template path is namespaced to avoid conflicts with other processors
    return render_template(
        'image_ssim_diff/preview.html',
        watch=watch,
        uuid=watch.get('uuid'),
        img_b64=img_b64,
        mime_type=mime_type,
        versions=versions,
        timestamp=timestamp,
        current_diff_url=watch['url']
    )
