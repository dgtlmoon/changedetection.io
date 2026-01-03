# Pages with a vertical height longer than this will use the 'stitch together' method.

# - Many GPUs have a max texture size of 16384x16384px (or lower on older devices).
# - If a page is taller than ~8000–10000px, it risks exceeding GPU memory limits.
# - This is especially important on headless Chromium, where Playwright may fail to allocate a massive full-page buffer.

from loguru import logger

from changedetectionio.content_fetchers import SCREENSHOT_MAX_HEIGHT_DEFAULT, SCREENSHOT_DEFAULT_QUALITY

# Cache font to avoid loading on every stitch
_cached_font = None

def _get_caption_font():
    """Get or create cached font for caption text."""
    global _cached_font
    if _cached_font is None:
        from PIL import ImageFont
        try:
            _cached_font = ImageFont.truetype("arial.ttf", 35)
        except IOError:
            _cached_font = ImageFont.load_default()
    return _cached_font


def stitch_images_inline(chunks_bytes, original_page_height, capture_height):
    """
    Stitch image chunks together inline (no multiprocessing).
    Optimized for small number of chunks (2-3) to avoid process creation overhead.

    Args:
        chunks_bytes: List of JPEG image bytes
        original_page_height: Original page height in pixels
        capture_height: Maximum capture height

    Returns:
        bytes: Stitched JPEG image
    """
    import os
    import io
    from PIL import Image, ImageDraw

    # Load images from byte chunks
    images = [Image.open(io.BytesIO(b)) for b in chunks_bytes]
    total_height = sum(im.height for im in images)
    max_width = max(im.width for im in images)

    # Create stitched image
    stitched = Image.new('RGB', (max_width, total_height))
    y_offset = 0
    for im in images:
        stitched.paste(im, (0, y_offset))
        y_offset += im.height
        im.close()  # Close immediately after pasting

    # Draw caption only if page was trimmed
    if original_page_height > capture_height:
        draw = ImageDraw.Draw(stitched)
        caption_text = f"WARNING: Screenshot was {original_page_height}px but trimmed to {capture_height}px because it was too long"
        padding = 10
        font = _get_caption_font()

        bbox = draw.textbbox((0, 0), caption_text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]

        # Draw white background rectangle
        draw.rectangle([(0, 0), (max_width, text_height + 2 * padding)], fill=(255, 255, 255))

        # Draw text centered
        text_x = (max_width - text_width) // 2
        draw.text((text_x, padding), caption_text, font=font, fill=(255, 0, 0))

    # Encode to JPEG
    output = io.BytesIO()
    stitched.save(output, format="JPEG", quality=int(os.getenv("SCREENSHOT_QUALITY", SCREENSHOT_DEFAULT_QUALITY)), optimize=True)
    result = output.getvalue()

    # Cleanup
    stitched.close()

    return result


def stitch_images_worker(pipe_conn, chunks_bytes, original_page_height, capture_height):
    """
    Stitch image chunks together in a separate process.
    Used for large number of chunks (4+) to avoid blocking the main event loop.
    """
    import os
    import io
    from PIL import Image, ImageDraw, ImageFont

    try:
        # Load images from byte chunks
        images = [Image.open(io.BytesIO(b)) for b in chunks_bytes]
        total_height = sum(im.height for im in images)
        max_width = max(im.width for im in images)

        # Create stitched image
        stitched = Image.new('RGB', (max_width, total_height))
        y_offset = 0
        for im in images:
            stitched.paste(im, (0, y_offset))
            y_offset += im.height
            im.close()  # Close immediately after pasting

        # Draw caption only if page was trimmed
        if original_page_height > capture_height:
            draw = ImageDraw.Draw(stitched)
            caption_text = f"WARNING: Screenshot was {original_page_height}px but trimmed to {capture_height}px because it was too long"
            padding = 10

            # Try to load font
            try:
                font = ImageFont.truetype("arial.ttf", 35)
            except IOError:
                font = ImageFont.load_default()

            bbox = draw.textbbox((0, 0), caption_text, font=font)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]

            # Draw white background rectangle
            draw.rectangle([(0, 0), (max_width, text_height + 2 * padding)], fill=(255, 255, 255))

            # Draw text centered
            text_x = (max_width - text_width) // 2
            draw.text((text_x, padding), caption_text, font=font, fill=(255, 0, 0))

        # Encode and send image with optimization
        output = io.BytesIO()
        stitched.save(output, format="JPEG", quality=int(os.getenv("SCREENSHOT_QUALITY", SCREENSHOT_DEFAULT_QUALITY)), optimize=True)
        pipe_conn.send_bytes(output.getvalue())

        stitched.close()
    except Exception as e:
        pipe_conn.send(f"error:{e}")
    finally:
        pipe_conn.close()


