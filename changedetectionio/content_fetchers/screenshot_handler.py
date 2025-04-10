# Pages with a vertical height longer than this will use the 'stitch together' method.

# - Many GPUs have a max texture size of 16384x16384px (or lower on older devices).
# - If a page is taller than ~8000–10000px, it risks exceeding GPU memory limits.
# - This is especially important on headless Chromium, where Playwright may fail to allocate a massive full-page buffer.

from loguru import logger

from changedetectionio.content_fetchers import SCREENSHOT_MAX_HEIGHT_DEFAULT

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
        stitched.save(output, format="JPEG", quality=int(os.getenv("SCREENSHOT_QUALITY", 30)))
        pipe_conn.send_bytes(output.getvalue())

        stitched.close()
    except Exception as e:
        pipe_conn.send(f"error:{e}")
    finally:
        pipe_conn.close()

def capture_full_page(page):
    import os
    import time
    from multiprocessing import Process, Pipe

    # Maximum total height for the final image (When in stitch mode).
    # We limit this to 16000px due to the huge amount of RAM that was being used
    # Example: 16000 × 1400 × 3 = 67,200,000 bytes ≈ 64.1 MB (not including buffers in PIL etc)
    MAX_TOTAL_HEIGHT = int(os.getenv("SCREENSHOT_MAX_HEIGHT", SCREENSHOT_MAX_HEIGHT_DEFAULT))

    # The size at which we will switch to stitching method, when below this (and
    # MAX_TOTAL_HEIGHT which can be set by a user) we will use the default
    # screenshot method.
    SCREENSHOT_SIZE_STITCH_THRESHOLD = 8000

    # Save the original viewport size
    original_viewport = page.viewport_size
    start = time.time()

    viewport_width = original_viewport["width"]
    viewport_height = original_viewport["height"]

    page_height = page.evaluate("document.documentElement.scrollHeight")

    ############################################################
    #### SCREENSHOT FITS INTO ONE SNAPSHOT (SMALLER PAGES) #####
    ############################################################

    # Optimization to avoid unnecessary stitching if we can avoid it
    # Use the default screenshot method for smaller pages to take advantage
    # of GPU and native playwright screenshot optimizations
    # - No PIL needed here, no danger of memory leaks, no sub process required
    if (page_height < SCREENSHOT_SIZE_STITCH_THRESHOLD and page_height < MAX_TOTAL_HEIGHT ):
        logger.debug("Using default screenshot method")
        page.request_gc()
        screenshot = page.screenshot(
            type="jpeg",
            quality=int(os.getenv("SCREENSHOT_QUALITY", 30)),
            full_page=True,
        )
        page.request_gc()
        logger.debug(f"Screenshot captured in {time.time() - start:.2f}s")
        return screenshot



    ###################################################################################
    #### CASE FOR LARGE SCREENSHOTS THAT NEED TO BE TRIMMED DUE TO MEMORY ISSUES  #####
    ###################################################################################
    # - PIL can easily allocate memory and not release it cleanly
    # - Fetching screenshot from playwright seems  OK
    # Image.new is leaky even with .close()
    # So lets prepare all the data chunks and farm it out to a subprocess for clean memory handling

    logger.debug(
        "Using stitching method for large screenshot because page height exceeds threshold"
    )

    # Limit the total capture height
    capture_height = min(page_height, MAX_TOTAL_HEIGHT)

    # Calculate number of chunks needed using ORIGINAL viewport height
    num_chunks = (capture_height + viewport_height - 1) // viewport_height
    screenshot_chunks = []

    # Track cumulative paste position
    y_offset = 0
    for _ in range(num_chunks):

        page.request_gc()
        page.evaluate(f"window.scrollTo(0, {y_offset})")
        page.request_gc()
        h = min(viewport_height, capture_height - y_offset)
        screenshot_chunks.append(page.screenshot(
                type="jpeg",
                clip={
                    "x": 0,
                    "y": 0,
                    "width": viewport_width,
                    "height": h,
                },
                quality=int(os.getenv("SCREENSHOT_QUALITY", 30)),
            ))

        y_offset += h # maybe better to inspect the image here?
        page.request_gc()

    # PIL can leak memory in various situations, assign the work to a subprocess for totally clean handling

    parent_conn, child_conn = Pipe()
    p = Process(target=stitch_images_worker, args=(child_conn, screenshot_chunks, page_height, capture_height))
    p.start()
    result = parent_conn.recv_bytes()
    p.join()

    screenshot_chunks = None
    logger.debug(f"Screenshot - Page height: {page_height} Capture height: {capture_height} - Stitched together in {time.time() - start:.2f}s")

    return result

