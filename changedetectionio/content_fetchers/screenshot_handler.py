# Pages with a vertical height longer than this will use the 'stitch together' method.

# - Many GPUs have a max texture size of 16384x16384px (or lower on older devices).
# - If a page is taller than ~8000–10000px, it risks exceeding GPU memory limits.
# - This is especially important on headless Chromium, where Playwright may fail to allocate a massive full-page buffer.

from loguru import logger

from changedetectionio.content_fetchers import SCREENSHOT_MAX_HEIGHT_DEFAULT, SCREENSHOT_DEFAULT_QUALITY


def stitch_images_worker(pipe_conn, chunks_bytes, original_page_height, capture_height):
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

        # Draw caption on top (overlaid, not extending canvas)
        draw = ImageDraw.Draw(stitched)

        if original_page_height > capture_height:
            caption_text = f"WARNING: Screenshot was {original_page_height}px but trimmed to {capture_height}px because it was too long"
            padding = 10
            font_size = 35
            font_color = (255, 0, 0)
            background_color = (255, 255, 255)


            # Try to load a proper font
            try:
                font = ImageFont.truetype("arial.ttf", font_size)
            except IOError:
                font = ImageFont.load_default()

            bbox = draw.textbbox((0, 0), caption_text, font=font)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]

            # Draw white rectangle background behind text
            rect_top = 0
            rect_bottom = text_height + 2 * padding
            draw.rectangle([(0, rect_top), (max_width, rect_bottom)], fill=background_color)

            # Draw text centered horizontally, 10px padding from top of the rectangle
            text_x = (max_width - text_width) // 2
            text_y = padding
            draw.text((text_x, text_y), caption_text, font=font, fill=font_color)

        # Encode and send image
        output = io.BytesIO()
        stitched.save(output, format="JPEG", quality=int(os.getenv("SCREENSHOT_QUALITY", SCREENSHOT_DEFAULT_QUALITY)))
        pipe_conn.send_bytes(output.getvalue())

        stitched.close()
    except Exception as e:
        pipe_conn.send(f"error:{e}")
    finally:
        pipe_conn.close()


