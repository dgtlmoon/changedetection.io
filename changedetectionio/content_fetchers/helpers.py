
# Pages with a vertical height longer than this will use the 'stitch together' method.

# - Many GPUs have a max texture size of 16384x16384px (or lower on older devices).
# - If a page is taller than ~8000–10000px, it risks exceeding GPU memory limits.
# - This is especially important on headless Chromium, where Playwright may fail to allocate a massive full-page buffer.


# The size at which we will switch to stitching method
SCREENSHOT_SIZE_STITCH_THRESHOLD=8000

from loguru import logger

def capture_stitched_together_full_page(page):
    import io
    import os
    import time
    import gc
    from PIL import Image, ImageDraw, ImageFont

    MAX_TOTAL_HEIGHT = SCREENSHOT_SIZE_STITCH_THRESHOLD*4  # Maximum total height for the final image (When in stitch mode)
    MAX_CHUNK_HEIGHT = 2000  # Height per screenshot chunk
    WARNING_TEXT_HEIGHT = 20  # Height of the warning text overlay

    # Save the original viewport size
    original_viewport = page.viewport_size
    now = time.time()

    try:
        viewport = page.viewport_size
        page_height = page.evaluate("document.documentElement.scrollHeight")

        # Limit the total capture height
        capture_height = min(page_height, MAX_TOTAL_HEIGHT)

        # Create the final image upfront to avoid holding all chunks in memory
        stitched_image = Image.new('RGB', (viewport["width"], capture_height))

        for offset in range(0, capture_height, MAX_CHUNK_HEIGHT):
            # Ensure we do not exceed the total height limit
            chunk_height = min(MAX_CHUNK_HEIGHT, capture_height - offset)

            # Adjust viewport size for this chunk
            page.set_viewport_size({"width": viewport["width"], "height": chunk_height})

            # Scroll to the correct position
            page.evaluate(f"window.scrollTo(0, {offset})")

            # Capture and process immediately
            with io.BytesIO(page.screenshot(type='jpeg', quality=int(os.getenv("SCREENSHOT_QUALITY", 30)))) as buf:
                with Image.open(buf) as img:
                    img.load()
                    stitched_image.paste(img, (0, offset))
                    img.close()

            # Explicit cleanup
            del buf
            gc.collect()
            # Prevents Playwright from accumulating graphics buffers for different viewport sizes.
            page.set_viewport_size(original_viewport)

        logger.debug(f"Screenshot stitched together in {time.time()-now:.2f}s")

        # Overlay warning text if the screenshot was trimmed
        if page_height > MAX_TOTAL_HEIGHT:
            draw = ImageDraw.Draw(stitched_image)
            warning_text = f"WARNING: Screenshot was {page_height}px but trimmed to {MAX_TOTAL_HEIGHT}px because it was too long"

            # Load font (default system font if Arial is unavailable)
            try:
                font = ImageFont.truetype("arial.ttf", WARNING_TEXT_HEIGHT)  # Arial (Windows/Mac)
            except IOError:
                font = ImageFont.load_default()  # Default font if Arial not found

            # Get text bounding box (correct method for newer Pillow versions)
            text_bbox = draw.textbbox((0, 0), warning_text, font=font)
            text_width = text_bbox[2] - text_bbox[0]  # Calculate text width
            text_height = text_bbox[3] - text_bbox[1]  # Calculate text height

            # Define background rectangle (top of the image)
            draw.rectangle([(0, 0), (viewport["width"], WARNING_TEXT_HEIGHT)], fill="white")

            # Center text horizontally within the warning area
            text_x = (viewport["width"] - text_width) // 2
            text_y = (WARNING_TEXT_HEIGHT - text_height) // 2

            # Draw the warning text in red
            draw.text((text_x, text_y), warning_text, fill="red", font=font)

        # Save final image
        with io.BytesIO() as output:
            stitched_image.save(output, format="JPEG", quality=int(os.getenv("SCREENSHOT_QUALITY", 30)))
            screenshot = output.getvalue()

    finally:
        # Restore the original viewport size
        page.set_viewport_size(original_viewport)
        if 'stitched_image' in locals():
            stitched_image.close()

    return screenshot
