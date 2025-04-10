# Pages with a vertical height longer than this will use the 'stitch together' method.

# - Many GPUs have a max texture size of 16384x16384px (or lower on older devices).
# - If a page is taller than ~8000–10000px, it risks exceeding GPU memory limits.
# - This is especially important on headless Chromium, where Playwright may fail to allocate a massive full-page buffer.

from loguru import logger

def capture_full_page(page):
    import io
    import os
    import time
    from PIL import Image, ImageDraw, ImageFont

    # Maximum total height for the final image (When in stitch mode).
    # We limit this to 16000px due to the huge amount of RAM that was being used
    # Example: 16000 × 1400 × 3 = 67,200,000 bytes ≈ 64.1 MB (not including buffers in PIL etc)
    MAX_TOTAL_HEIGHT = int(os.getenv("SCREENSHOT_MAX_HEIGHT", 16000))

    # The size at which we will switch to stitching method, when below this (and
    # MAX_TOTAL_HEIGHT which can be set by a user) we will use the default
    # screenshot method.
    SCREENSHOT_SIZE_STITCH_THRESHOLD = 8000

    WARNING_TEXT_HEIGHT = 20  # Height of the warning text overlay

    # Save the original viewport size
    original_viewport = page.viewport_size
    start = time.time()

    stitched_image = None

    try:
        viewport_width = original_viewport["width"]
        viewport_height = original_viewport["height"]

        page_height = page.evaluate("document.documentElement.scrollHeight")

        # Optimization to avoid unnecessary stitching if we can avoid it
        # Use the default screenshot method for smaller pages to take advantage
        # of GPU and native playwright screenshot optimizations
        if (
            page_height < SCREENSHOT_SIZE_STITCH_THRESHOLD
            and page_height < MAX_TOTAL_HEIGHT
        ):
            logger.debug("Using default screenshot method")
            screenshot = page.screenshot(
                type="jpeg",
                quality=int(os.getenv("SCREENSHOT_QUALITY", 30)),
                full_page=True,
            )
            logger.debug(f"Screenshot captured in {time.time() - start:.2f}s")
            return screenshot

        logger.debug(
            "Using stitching method for large screenshot because page height exceeds threshold"
        )

        # Limit the total capture height
        capture_height = min(page_height, MAX_TOTAL_HEIGHT)

        # Calculate number of chunks needed using ORIGINAL viewport height
        num_chunks = (capture_height + viewport_height - 1) // viewport_height

        # Create the final image upfront to avoid holding all chunks in memory
        stitched_image = Image.new("RGB", (viewport_width, capture_height))

        # Track cumulative paste position
        y_offset = 0

        for _ in range(num_chunks):
            # Scroll to position (no viewport resizing)
            page.evaluate(f"window.scrollTo(0, {y_offset})")

            # Capture only the visible area using clip
            with io.BytesIO(
                page.screenshot(
                    type="jpeg",
                    clip={
                        "x": 0,
                        "y": 0,
                        "width": viewport_width,
                        "height": min(viewport_height, capture_height - y_offset),
                    },
                    quality=int(os.getenv("SCREENSHOT_QUALITY", 30)),
                )
            ) as buf:
                with Image.open(buf) as img:
                    img.load()
                    stitched_image.paste(img, (0, y_offset))
                    y_offset += img.height

        page.request_gc()
        logger.debug(f"Screenshot stitched together in {time.time() - start:.2f}s")

        # Overlay warning text if the screenshot was trimmed
        if capture_height < page_height:
            draw = ImageDraw.Draw(stitched_image)
            warning_text = f"WARNING: Screenshot was {page_height}px but trimmed to {MAX_TOTAL_HEIGHT}px because it was too long"

            # Load font (default system font if Arial is unavailable)
            try:
                font = ImageFont.truetype(
                    "arial.ttf", WARNING_TEXT_HEIGHT
                )  # Arial (Windows/Mac)
            except IOError:
                font = ImageFont.load_default()  # Default font if Arial not found

            # Get text bounding box (correct method for newer Pillow versions)
            text_bbox = draw.textbbox((0, 0), warning_text, font=font)
            text_width = text_bbox[2] - text_bbox[0]  # Calculate text width
            text_height = text_bbox[3] - text_bbox[1]  # Calculate text height

            # Define background rectangle (top of the image)
            draw.rectangle(
                [(0, 0), (viewport_width, WARNING_TEXT_HEIGHT)], fill="white"
            )

            # Center text horizontally within the warning area
            text_x = (viewport_width - text_width) // 2
            text_y = (WARNING_TEXT_HEIGHT - text_height) // 2

            # Draw the warning text in red
            draw.text((text_x, text_y), warning_text, fill="red", font=font)

        # Save final image
        with io.BytesIO() as output:
            stitched_image.save(
                output, format="JPEG", quality=int(os.getenv("SCREENSHOT_QUALITY", 30))
            )
            screenshot = output.getvalue()

    finally:
        # Restore the original viewport size
        page.set_viewport_size(original_viewport)
        page.request_gc()
        if stitched_image is not None:
            stitched_image.close()
    stitched_image = None
    return screenshot
