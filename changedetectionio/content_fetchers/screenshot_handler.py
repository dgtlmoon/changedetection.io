# Pages with a vertical height longer than this will use the 'stitch together' method.

# - Many GPUs have a max texture size of 16384x16384px (or lower on older devices).
# - If a page is taller than ~8000–10000px, it risks exceeding GPU memory limits.
# - This is especially important on headless Chromium, where Playwright may fail to allocate a massive full-page buffer.

from loguru import logger

from changedetectionio.content_fetchers import SCREENSHOT_MAX_HEIGHT_DEFAULT, SCREENSHOT_DEFAULT_QUALITY

def stitch_images_worker_raw_bytes(pipe_conn, original_page_height, capture_height):
    """
    Stitch image chunks together in a separate process.

    Uses spawn multiprocessing to isolate PIL's C-level memory allocation.
    When the subprocess exits, the OS reclaims ALL memory including C-level allocations
    that Python's GC cannot release. This prevents the ~50MB per stitch from accumulating
    in the main process.

    Trade-off: Adds 35MB resource_tracker subprocess, but prevents 500MB+ memory leak
    in main process (much better at scale: 35GB vs 500GB for 1000 instances).

    Args:
        pipe_conn: Pipe connection to receive data and send result
        original_page_height: Original page height in pixels
        capture_height: Maximum capture height
    """
    import os
    import io
    import struct
    from PIL import Image, ImageDraw, ImageFont

    try:
        # Receive chunk count as 4-byte integer (no pickle!)
        count_bytes = pipe_conn.recv_bytes()
        chunk_count = struct.unpack('I', count_bytes)[0]

        # Receive each chunk as raw bytes (no pickle!)
        chunks_bytes = []
        for _ in range(chunk_count):
            chunks_bytes.append(pipe_conn.recv_bytes())

        # Load images from byte chunks
        images = [Image.open(io.BytesIO(b)) for b in chunks_bytes]
        del chunks_bytes

        total_height = sum(im.height for im in images)
        max_width = max(im.width for im in images)

        # Create stitched image
        stitched = Image.new('RGB', (max_width, total_height))
        y_offset = 0
        for im in images:
            stitched.paste(im, (0, y_offset))
            y_offset += im.height
            im.close()
        del images

        # Draw caption only if page was trimmed
        if original_page_height > capture_height:
            draw = ImageDraw.Draw(stitched)
            caption_text = f"WARNING: Screenshot was {original_page_height}px but trimmed to {capture_height}px because it was too long"
            padding = 10
            try:
                font = ImageFont.truetype("arial.ttf", 35)
            except IOError:
                font = ImageFont.load_default()

            bbox = draw.textbbox((0, 0), caption_text, font=font)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]
            draw.rectangle([(0, 0), (max_width, text_height + 2 * padding)], fill=(255, 255, 255))
            text_x = (max_width - text_width) // 2
            draw.text((text_x, padding), caption_text, font=font, fill=(255, 0, 0))

        # Encode and send
        output = io.BytesIO()
        stitched.save(output, format="JPEG", quality=int(os.getenv("SCREENSHOT_QUALITY", SCREENSHOT_DEFAULT_QUALITY)), optimize=True)
        result_bytes = output.getvalue()

        stitched.close()
        del stitched
        output.close()
        del output

        pipe_conn.send_bytes(result_bytes)
        del result_bytes

    except Exception as e:
        logger.error(f"Error in stitch_images_worker_raw_bytes: {e}")
        error_msg = f"error:{e}".encode('utf-8')
        pipe_conn.send_bytes(error_msg)
    finally:
        pipe_conn.close()
