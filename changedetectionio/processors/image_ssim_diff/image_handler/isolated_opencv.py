"""
OpenCV-based subprocess isolation for image comparison.

OpenCV is much more stable in multiprocessing contexts than LibVIPS.
No threading issues, no fork problems, picklable functions.
"""

import multiprocessing
import numpy as np
from .. import POLL_TIMEOUT_ABSOLUTE

# Public implementation name for logging
IMPLEMENTATION_NAME = "OpenCV"


def _worker_compare(conn, img_bytes_from, img_bytes_to, threshold, blur_sigma, min_change_percentage, crop_region):
    """
    Worker function for image comparison (must be top-level for pickling with spawn).

    Args:
        conn: Pipe connection for sending results
        img_bytes_from: Previous screenshot bytes
        img_bytes_to: Current screenshot bytes
        threshold: Pixel difference threshold
        blur_sigma: Gaussian blur sigma
        min_change_percentage: Minimum percentage to trigger change
        crop_region: Optional (left, top, right, bottom) crop coordinates
    """
    import time
    try:
        import cv2

        # CRITICAL: Disable OpenCV threading to prevent thread explosion
        # With multiprocessing, each subprocess would otherwise spawn threads equal to CPU cores
        # This causes excessive thread counts and memory overhead
        # Research: https://medium.com/@rachittayal7/a-note-on-opencv-threads-performance-in-prod-d10180716fba
        cv2.setNumThreads(1)

        print(f"[{time.time():.3f}] [Worker] Compare worker starting (threads=1 for memory optimization)", flush=True)

        # Decode images from bytes
        print(f"[{time.time():.3f}] [Worker] Loading images (from={len(img_bytes_from)} bytes, to={len(img_bytes_to)} bytes)", flush=True)
        img_from = cv2.imdecode(np.frombuffer(img_bytes_from, np.uint8), cv2.IMREAD_COLOR)
        img_to = cv2.imdecode(np.frombuffer(img_bytes_to, np.uint8), cv2.IMREAD_COLOR)
        print(f"[{time.time():.3f}] [Worker] Images loaded: from={img_from.shape}, to={img_to.shape}", flush=True)

        # Crop if region specified
        if crop_region:
            print(f"[{time.time():.3f}] [Worker] Cropping to region {crop_region}", flush=True)
            left, top, right, bottom = crop_region
            img_from = img_from[top:bottom, left:right]
            img_to = img_to[top:bottom, left:right]
            print(f"[{time.time():.3f}] [Worker] Cropped: from={img_from.shape}, to={img_to.shape}", flush=True)

        # Resize if dimensions don't match
        if img_from.shape != img_to.shape:
            print(f"[{time.time():.3f}] [Worker] Resizing to match dimensions", flush=True)
            img_from = cv2.resize(img_from, (img_to.shape[1], img_to.shape[0]))

        # Convert to grayscale
        print(f"[{time.time():.3f}] [Worker] Converting to grayscale", flush=True)
        gray_from = cv2.cvtColor(img_from, cv2.COLOR_BGR2GRAY)
        gray_to = cv2.cvtColor(img_to, cv2.COLOR_BGR2GRAY)

        # Optional Gaussian blur
        if blur_sigma > 0:
            print(f"[{time.time():.3f}] [Worker] Applying Gaussian blur (sigma={blur_sigma})", flush=True)
            # OpenCV uses kernel size, convert sigma to kernel size: size = 2 * round(3*sigma) + 1
            ksize = int(2 * round(3 * blur_sigma)) + 1
            if ksize % 2 == 0:  # Must be odd
                ksize += 1
            gray_from = cv2.GaussianBlur(gray_from, (ksize, ksize), blur_sigma)
            gray_to = cv2.GaussianBlur(gray_to, (ksize, ksize), blur_sigma)
            print(f"[{time.time():.3f}] [Worker] Blur applied (kernel={ksize}x{ksize})", flush=True)

        # Calculate absolute difference
        print(f"[{time.time():.3f}] [Worker] Calculating absolute difference", flush=True)
        diff = cv2.absdiff(gray_from, gray_to)

        # Apply threshold
        print(f"[{time.time():.3f}] [Worker] Applying threshold ({threshold})", flush=True)
        _, thresholded = cv2.threshold(diff, int(threshold), 255, cv2.THRESH_BINARY)

        # Calculate change percentage
        total_pixels = thresholded.size
        changed_pixels = np.count_nonzero(thresholded)
        change_percentage = (changed_pixels / total_pixels) * 100.0

        # Determine if change detected
        changed_detected = change_percentage > min_change_percentage

        print(f"[{time.time():.3f}] [Worker] Comparison complete: changed={changed_detected}, percentage={change_percentage:.2f}%", flush=True)
        conn.send((changed_detected, float(change_percentage)))

    except Exception as e:
        print(f"[{time.time():.3f}] [Worker] Error: {e}", flush=True)
        import traceback
        traceback.print_exc()
        conn.send((False, 0.0))
    finally:
        conn.close()


async def compare_images_isolated(img_bytes_from, img_bytes_to, threshold, blur_sigma, min_change_percentage, crop_region=None):
    """
    Compare images in isolated subprocess using OpenCV (async-safe).

    Returns:
        tuple: (changed_detected, change_percentage)
    """
    import time
    import asyncio
    print(f"[{time.time():.3f}] [Parent] Starting OpenCV comparison subprocess", flush=True)

    # Use spawn method for clean process (no fork issues)
    ctx = multiprocessing.get_context('spawn')
    parent_conn, child_conn = ctx.Pipe()

    p = ctx.Process(
        target=_worker_compare,
        args=(child_conn, img_bytes_from, img_bytes_to, threshold, blur_sigma, min_change_percentage, crop_region)
    )

    print(f"[{time.time():.3f}] [Parent] Starting subprocess", flush=True)
    p.start()
    print(f"[{time.time():.3f}] [Parent] Subprocess started (pid={p.pid}), waiting for result ({POLL_TIMEOUT_ABSOLUTE}s timeout)", flush=True)

    result = (False, 0.0)
    try:
        # Async-friendly polling: check in small intervals without blocking event loop
        deadline = time.time() + POLL_TIMEOUT_ABSOLUTE
        while time.time() < deadline:
            # Run poll() in thread to avoid blocking event loop
            has_data = await asyncio.to_thread(parent_conn.poll, 0.1)
            if has_data:
                print(f"[{time.time():.3f}] [Parent] Result available, receiving", flush=True)
                result = await asyncio.to_thread(parent_conn.recv)
                print(f"[{time.time():.3f}] [Parent] Result received: {result}", flush=True)
                break
            await asyncio.sleep(0)  # Yield control to event loop
        else:
            from loguru import logger
            logger.critical(f"[OpenCV subprocess] Timeout waiting for compare_images result after {POLL_TIMEOUT_ABSOLUTE}s (subprocess may be hung)")
            print(f"[{time.time():.3f}] [Parent] Timeout waiting for result after {POLL_TIMEOUT_ABSOLUTE}s", flush=True)
    except Exception as e:
        print(f"[{time.time():.3f}] [Parent] Error receiving result: {e}", flush=True)
    finally:
        # Always close pipe first
        try:
            parent_conn.close()
        except:
            pass

        # Try graceful shutdown (async-safe)
        print(f"[{time.time():.3f}] [Parent] Waiting for subprocess to exit (5s timeout)", flush=True)
        join_start = time.time()
        await asyncio.to_thread(p.join, 5)
        join_elapsed = time.time() - join_start
        print(f"[{time.time():.3f}] [Parent] First join took {join_elapsed:.2f}s", flush=True)

        if p.is_alive():
            print(f"[{time.time():.3f}] [Parent] Process didn't exit gracefully, terminating", flush=True)
            term_start = time.time()
            p.terminate()
            await asyncio.to_thread(p.join, 3)
            term_elapsed = time.time() - term_start
            print(f"[{time.time():.3f}] [Parent] Terminate+join took {term_elapsed:.2f}s", flush=True)

        # Force kill if still alive
        if p.is_alive():
            print(f"[{time.time():.3f}] [Parent] Process didn't terminate, killing", flush=True)
            kill_start = time.time()
            p.kill()
            await asyncio.to_thread(p.join, 1)
            kill_elapsed = time.time() - kill_start
            print(f"[{time.time():.3f}] [Parent] Kill+join took {kill_elapsed:.2f}s", flush=True)

        print(f"[{time.time():.3f}] [Parent] Subprocess cleanup complete, returning result", flush=True)

    return result


def _worker_generate_diff(conn, img_bytes_from, img_bytes_to, threshold, blur_sigma, max_width, max_height):
    """
    Worker function for generating visual diff with red overlay.
    """
    import time
    try:
        import cv2

        cv2.setNumThreads(1)
        print(f"[{time.time():.3f}] [Worker] Generate diff worker starting", flush=True)

        # Decode images
        img_from = cv2.imdecode(np.frombuffer(img_bytes_from, np.uint8), cv2.IMREAD_COLOR)
        img_to = cv2.imdecode(np.frombuffer(img_bytes_to, np.uint8), cv2.IMREAD_COLOR)

        # Resize if needed to match dimensions
        if img_from.shape != img_to.shape:
            img_from = cv2.resize(img_from, (img_to.shape[1], img_to.shape[0]))

        # Downscale to max dimensions for faster processing
        h, w = img_to.shape[:2]
        if w > max_width or h > max_height:
            scale = min(max_width / w, max_height / h)
            new_w = int(w * scale)
            new_h = int(h * scale)
            img_from = cv2.resize(img_from, (new_w, new_h))
            img_to = cv2.resize(img_to, (new_w, new_h))

        # Convert to grayscale
        gray_from = cv2.cvtColor(img_from, cv2.COLOR_BGR2GRAY)
        gray_to = cv2.cvtColor(img_to, cv2.COLOR_BGR2GRAY)

        # Optional blur
        if blur_sigma > 0:
            ksize = int(2 * round(3 * blur_sigma)) + 1
            if ksize % 2 == 0:
                ksize += 1
            gray_from = cv2.GaussianBlur(gray_from, (ksize, ksize), blur_sigma)
            gray_to = cv2.GaussianBlur(gray_to, (ksize, ksize), blur_sigma)

        # Calculate difference
        diff = cv2.absdiff(gray_from, gray_to)

        # Apply threshold to get mask
        _, mask = cv2.threshold(diff, int(threshold), 255, cv2.THRESH_BINARY)

        # Create red overlay on original 'to' image
        # Where mask is 255 (changed), blend 50% red
        overlay = img_to.copy()
        overlay[:, :, 2] = np.where(mask > 0,
                                     np.clip(overlay[:, :, 2] * 0.5 + 127, 0, 255).astype(np.uint8),
                                     overlay[:, :, 2])
        overlay[:, :, 0:2] = np.where(mask[:, :, np.newaxis] > 0,
                                       (overlay[:, :, 0:2] * 0.5).astype(np.uint8),
                                       overlay[:, :, 0:2])

        # Encode as JPEG
        _, encoded = cv2.imencode('.jpg', overlay, [cv2.IMWRITE_JPEG_QUALITY, 85])
        diff_bytes = encoded.tobytes()

        print(f"[{time.time():.3f}] [Worker] Generated diff ({len(diff_bytes)} bytes)", flush=True)
        conn.send(diff_bytes)

    except Exception as e:
        print(f"[{time.time():.3f}] [Worker] Generate diff error: {e}", flush=True)
        import traceback
        traceback.print_exc()
        conn.send(None)
    finally:
        conn.close()


async def generate_diff_isolated(img_bytes_from, img_bytes_to, threshold, blur_sigma, max_width, max_height):
    """
    Generate visual diff with red overlay in isolated subprocess (async-safe).

    Returns:
        bytes: JPEG diff image or None on failure
    """
    import time
    import asyncio
    print(f"[{time.time():.3f}] [Parent] Starting generate_diff subprocess", flush=True)

    ctx = multiprocessing.get_context('spawn')
    parent_conn, child_conn = ctx.Pipe()

    p = ctx.Process(
        target=_worker_generate_diff,
        args=(child_conn, img_bytes_from, img_bytes_to, threshold, blur_sigma, max_width, max_height)
    )

    print(f"[{time.time():.3f}] [Parent] Starting subprocess", flush=True)
    p.start()
    print(f"[{time.time():.3f}] [Parent] Subprocess started (pid={p.pid}), waiting for result ({POLL_TIMEOUT_ABSOLUTE}s timeout)", flush=True)

    result = None
    try:
        # Async-friendly polling: check in small intervals without blocking event loop
        deadline = time.time() + POLL_TIMEOUT_ABSOLUTE
        while time.time() < deadline:
            # Run poll() in thread to avoid blocking event loop
            has_data = await asyncio.to_thread(parent_conn.poll, 0.1)
            if has_data:
                print(f"[{time.time():.3f}] [Parent] Result available, receiving", flush=True)
                result = await asyncio.to_thread(parent_conn.recv)
                print(f"[{time.time():.3f}] [Parent] Result received ({len(result) if result else 0} bytes)", flush=True)
                break
            await asyncio.sleep(0)  # Yield control to event loop
        else:
            from loguru import logger
            logger.critical(f"[OpenCV subprocess] Timeout waiting for generate_diff result after {POLL_TIMEOUT_ABSOLUTE}s (subprocess may be hung)")
            print(f"[{time.time():.3f}] [Parent] Timeout waiting for result after {POLL_TIMEOUT_ABSOLUTE}s", flush=True)
    except Exception as e:
        print(f"[{time.time():.3f}] [Parent] Error receiving diff: {e}", flush=True)
    finally:
        # Always close pipe first
        try:
            parent_conn.close()
        except:
            pass

        # Try graceful shutdown (async-safe)
        print(f"[{time.time():.3f}] [Parent] Waiting for subprocess to exit (5s timeout)", flush=True)
        join_start = time.time()
        await asyncio.to_thread(p.join, 5)
        join_elapsed = time.time() - join_start
        print(f"[{time.time():.3f}] [Parent] First join took {join_elapsed:.2f}s", flush=True)

        if p.is_alive():
            print(f"[{time.time():.3f}] [Parent] Process didn't exit gracefully, terminating", flush=True)
            term_start = time.time()
            p.terminate()
            await asyncio.to_thread(p.join, 3)
            term_elapsed = time.time() - term_start
            print(f"[{time.time():.3f}] [Parent] Terminate+join took {term_elapsed:.2f}s", flush=True)

        if p.is_alive():
            print(f"[{time.time():.3f}] [Parent] Process didn't terminate, killing", flush=True)
            kill_start = time.time()
            p.kill()
            await asyncio.to_thread(p.join, 1)
            kill_elapsed = time.time() - kill_start
            print(f"[{time.time():.3f}] [Parent] Kill+join took {kill_elapsed:.2f}s", flush=True)

        print(f"[{time.time():.3f}] [Parent] Subprocess cleanup complete, returning result", flush=True)

    return result


def _worker_draw_bounding_box(conn, img_bytes, x, y, width, height, color, thickness):
    """
    Worker function for drawing bounding box on image.
    """
    import time
    try:
        import cv2

        cv2.setNumThreads(1)
        print(f"[{time.time():.3f}] [Worker] Draw bounding box worker starting", flush=True)

        # Decode image
        img = cv2.imdecode(np.frombuffer(img_bytes, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            print(f"[{time.time():.3f}] [Worker] Failed to decode image", flush=True)
            conn.send(None)
            return

        # Draw rectangle (BGR format)
        cv2.rectangle(img, (x, y), (x + width, y + height), color, thickness)

        # Encode back to PNG
        _, encoded = cv2.imencode('.png', img)
        result_bytes = encoded.tobytes()

        print(f"[{time.time():.3f}] [Worker] Bounding box drawn ({len(result_bytes)} bytes)", flush=True)
        conn.send(result_bytes)

    except Exception as e:
        print(f"[{time.time():.3f}] [Worker] Draw bounding box error: {e}", flush=True)
        import traceback
        traceback.print_exc()
        conn.send(None)
    finally:
        conn.close()


async def draw_bounding_box_isolated(img_bytes, x, y, width, height, color=(255, 0, 0), thickness=3):
    """
    Draw bounding box on image in isolated subprocess (async-safe).

    Args:
        img_bytes: Image data as bytes
        x: Left coordinate
        y: Top coordinate
        width: Box width
        height: Box height
        color: BGR color tuple (default: blue)
        thickness: Line thickness in pixels

    Returns:
        bytes: PNG image with bounding box or None on failure
    """
    import time
    import asyncio
    print(f"[{time.time():.3f}] [Parent] Starting draw_bounding_box subprocess", flush=True)

    ctx = multiprocessing.get_context('spawn')
    parent_conn, child_conn = ctx.Pipe()

    p = ctx.Process(
        target=_worker_draw_bounding_box,
        args=(child_conn, img_bytes, x, y, width, height, color, thickness)
    )

    print(f"[{time.time():.3f}] [Parent] Starting subprocess", flush=True)
    p.start()
    print(f"[{time.time():.3f}] [Parent] Subprocess started (pid={p.pid}), waiting for result ({POLL_TIMEOUT_ABSOLUTE}s timeout)", flush=True)

    result = None
    try:
        # Async-friendly polling: check in small intervals without blocking event loop
        deadline = time.time() + POLL_TIMEOUT_ABSOLUTE
        while time.time() < deadline:
            # Run poll() in thread to avoid blocking event loop
            has_data = await asyncio.to_thread(parent_conn.poll, 0.1)
            if has_data:
                print(f"[{time.time():.3f}] [Parent] Result available, receiving", flush=True)
                # Run recv() in thread too
                result = await asyncio.to_thread(parent_conn.recv)
                print(f"[{time.time():.3f}] [Parent] Result received ({len(result) if result else 0} bytes)", flush=True)
                break
            # Yield control to event loop
            await asyncio.sleep(0)
        else:
            from loguru import logger
            logger.critical(f"[OpenCV subprocess] Timeout waiting for draw_bounding_box result after {POLL_TIMEOUT_ABSOLUTE}s (subprocess may be hung)")
            print(f"[{time.time():.3f}] [Parent] Timeout waiting for result after {POLL_TIMEOUT_ABSOLUTE}s", flush=True)
    except Exception as e:
        print(f"[{time.time():.3f}] [Parent] Error receiving result: {e}", flush=True)
    finally:
        # Always close pipe first
        try:
            parent_conn.close()
        except:
            pass

        # Try graceful shutdown (run join in thread to avoid blocking)
        print(f"[{time.time():.3f}] [Parent] Waiting for subprocess to exit (3s timeout)", flush=True)
        join_start = time.time()
        await asyncio.to_thread(p.join, 3)
        join_elapsed = time.time() - join_start
        print(f"[{time.time():.3f}] [Parent] First join took {join_elapsed:.2f}s", flush=True)

        if p.is_alive():
            print(f"[{time.time():.3f}] [Parent] Process didn't exit gracefully, terminating", flush=True)
            term_start = time.time()
            p.terminate()
            await asyncio.to_thread(p.join, 2)
            term_elapsed = time.time() - term_start
            print(f"[{time.time():.3f}] [Parent] Terminate+join took {term_elapsed:.2f}s", flush=True)

        if p.is_alive():
            print(f"[{time.time():.3f}] [Parent] Process didn't terminate, killing", flush=True)
            kill_start = time.time()
            p.kill()
            await asyncio.to_thread(p.join, 1)
            kill_elapsed = time.time() - kill_start
            print(f"[{time.time():.3f}] [Parent] Kill+join took {kill_elapsed:.2f}s", flush=True)

        print(f"[{time.time():.3f}] [Parent] Subprocess cleanup complete, returning result", flush=True)

    return result


def _worker_calculate_percentage(conn, img_bytes_from, img_bytes_to, threshold, blur_sigma, max_width, max_height):
    """
    Worker function for calculating change percentage.
    """
    import time
    try:
        import cv2

        cv2.setNumThreads(1)

        # Decode images
        img_from = cv2.imdecode(np.frombuffer(img_bytes_from, np.uint8), cv2.IMREAD_COLOR)
        img_to = cv2.imdecode(np.frombuffer(img_bytes_to, np.uint8), cv2.IMREAD_COLOR)

        # Resize if needed
        if img_from.shape != img_to.shape:
            img_from = cv2.resize(img_from, (img_to.shape[1], img_to.shape[0]))

        # Downscale to max dimensions
        h, w = img_to.shape[:2]
        if w > max_width or h > max_height:
            scale = min(max_width / w, max_height / h)
            new_w = int(w * scale)
            new_h = int(h * scale)
            img_from = cv2.resize(img_from, (new_w, new_h))
            img_to = cv2.resize(img_to, (new_w, new_h))

        # Convert to grayscale
        gray_from = cv2.cvtColor(img_from, cv2.COLOR_BGR2GRAY)
        gray_to = cv2.cvtColor(img_to, cv2.COLOR_BGR2GRAY)

        # Optional blur
        if blur_sigma > 0:
            ksize = int(2 * round(3 * blur_sigma)) + 1
            if ksize % 2 == 0:
                ksize += 1
            gray_from = cv2.GaussianBlur(gray_from, (ksize, ksize), blur_sigma)
            gray_to = cv2.GaussianBlur(gray_to, (ksize, ksize), blur_sigma)

        # Calculate difference
        diff = cv2.absdiff(gray_from, gray_to)

        # Apply threshold
        _, thresholded = cv2.threshold(diff, int(threshold), 255, cv2.THRESH_BINARY)

        # Calculate percentage
        total_pixels = thresholded.size
        changed_pixels = np.count_nonzero(thresholded)
        change_percentage = (changed_pixels / total_pixels) * 100.0

        conn.send(float(change_percentage))

    except Exception as e:
        print(f"[{time.time():.3f}] [Worker] Calculate percentage error: {e}", flush=True)
        conn.send(0.0)
    finally:
        conn.close()


async def calculate_change_percentage_isolated(img_bytes_from, img_bytes_to, threshold, blur_sigma, max_width, max_height):
    """
    Calculate change percentage in isolated subprocess (async-safe).

    Returns:
        float: Change percentage
    """
    import time
    import asyncio
    print(f"[{time.time():.3f}] [Parent] Starting calculate_percentage subprocess", flush=True)

    ctx = multiprocessing.get_context('spawn')
    parent_conn, child_conn = ctx.Pipe()

    p = ctx.Process(
        target=_worker_calculate_percentage,
        args=(child_conn, img_bytes_from, img_bytes_to, threshold, blur_sigma, max_width, max_height)
    )

    print(f"[{time.time():.3f}] [Parent] Starting subprocess", flush=True)
    p.start()
    print(f"[{time.time():.3f}] [Parent] Subprocess started (pid={p.pid}), waiting for result ({POLL_TIMEOUT_ABSOLUTE}s timeout)", flush=True)

    result = 0.0
    try:
        # Async-friendly polling: check in small intervals without blocking event loop
        deadline = time.time() + POLL_TIMEOUT_ABSOLUTE
        while time.time() < deadline:
            # Run poll() in thread to avoid blocking event loop
            has_data = await asyncio.to_thread(parent_conn.poll, 0.1)
            if has_data:
                print(f"[{time.time():.3f}] [Parent] Result available, receiving", flush=True)
                result = await asyncio.to_thread(parent_conn.recv)
                print(f"[{time.time():.3f}] [Parent] Result received: {result:.2f}%", flush=True)
                break
            await asyncio.sleep(0)  # Yield control to event loop
        else:
            from loguru import logger
            logger.critical(f"[OpenCV subprocess] Timeout waiting for calculate_change_percentage result after {POLL_TIMEOUT_ABSOLUTE}s (subprocess may be hung)")
            print(f"[{time.time():.3f}] [Parent] Timeout waiting for result after {POLL_TIMEOUT_ABSOLUTE}s", flush=True)
    except Exception as e:
        print(f"[{time.time():.3f}] [Parent] Error receiving percentage: {e}", flush=True)
    finally:
        # Always close pipe first
        try:
            parent_conn.close()
        except:
            pass

        # Try graceful shutdown (async-safe)
        print(f"[{time.time():.3f}] [Parent] Waiting for subprocess to exit (5s timeout)", flush=True)
        join_start = time.time()
        await asyncio.to_thread(p.join, 5)
        join_elapsed = time.time() - join_start
        print(f"[{time.time():.3f}] [Parent] First join took {join_elapsed:.2f}s", flush=True)

        if p.is_alive():
            print(f"[{time.time():.3f}] [Parent] Process didn't exit gracefully, terminating", flush=True)
            term_start = time.time()
            p.terminate()
            await asyncio.to_thread(p.join, 3)
            term_elapsed = time.time() - term_start
            print(f"[{time.time():.3f}] [Parent] Terminate+join took {term_elapsed:.2f}s", flush=True)

        if p.is_alive():
            print(f"[{time.time():.3f}] [Parent] Process didn't terminate, killing", flush=True)
            kill_start = time.time()
            p.kill()
            await asyncio.to_thread(p.join, 1)
            kill_elapsed = time.time() - kill_start
            print(f"[{time.time():.3f}] [Parent] Kill+join took {kill_elapsed:.2f}s", flush=True)

        print(f"[{time.time():.3f}] [Parent] Subprocess cleanup complete, returning result", flush=True)

    return result
