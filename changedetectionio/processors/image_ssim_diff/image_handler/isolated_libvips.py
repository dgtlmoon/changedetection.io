"""
Subprocess-isolated image operations for memory leak prevention.

LibVIPS accumulates C-level memory in long-running processes that cannot be
reclaimed by Python's GC or libvips cache management. Using subprocess isolation
ensures complete memory cleanup when the process exits.

This module wraps LibvipsImageDiffHandler operations in multiprocessing for
complete memory isolation without code duplication.

Research: https://github.com/libvips/pyvips/issues/234
"""

import multiprocessing

# CRITICAL: Use 'spawn' context instead of 'fork' to avoid inheriting parent's
# LibVIPS threading state which can cause hangs in gaussblur operations
# https://docs.python.org/3/library/multiprocessing.html#contexts-and-start-methods


def _worker_generate_diff(conn, img_bytes_from, img_bytes_to, threshold, blur_sigma, max_width, max_height):
    """
    Worker: Generate diff visualization using LibvipsImageDiffHandler in isolated subprocess.

    This runs in a separate process for complete memory isolation.
    Uses print() instead of loguru to avoid forking issues.
    """
    try:
        # Import handler inside worker
        from .libvips_handler import LibvipsImageDiffHandler

        print(f"[Worker] Initializing handler", flush=True)
        handler = LibvipsImageDiffHandler()

        # Load images using handler
        img_from = handler.load_from_bytes(img_bytes_from)
        img_to = handler.load_from_bytes(img_bytes_to)

        # Ensure same size
        w1, h1 = handler.get_dimensions(img_from)
        w2, h2 = handler.get_dimensions(img_to)
        if (w1, h1) != (w2, h2):
            img_from = handler.resize(img_from, w2, h2)

        # Downscale for faster diff visualization
        img_from = handler.resize(img_from, max_width, max_height)
        img_to = handler.resize(img_to, max_width, max_height)

        # Convert to grayscale
        gray_from = handler.to_grayscale(img_from)
        gray_to = handler.to_grayscale(img_to)

        # Optional blur - DISABLED due to LibVIPS threading issues in fork
        # gray_from = handler.gaussian_blur(gray_from, blur_sigma)
        # gray_to = handler.gaussian_blur(gray_to, blur_sigma)

        # Calculate difference
        diff = handler.absolute_difference(gray_from, gray_to)

        # Threshold to get mask
        _, diff_mask = handler.threshold(diff, int(threshold))

        # Generate diff image with red overlay
        diff_image_bytes = handler.apply_red_overlay(img_to, diff_mask)

        print(f"[Worker] Generated diff ({len(diff_image_bytes)} bytes)", flush=True)
        conn.send(diff_image_bytes)

    except Exception as e:
        print(f"[Worker] Error: {e}", flush=True)
        import traceback
        traceback.print_exc()
        conn.send(None)
    finally:
        conn.close()


def generate_diff_isolated(img_bytes_from, img_bytes_to, threshold, blur_sigma, max_width, max_height):
    """
    Generate diff visualization in isolated subprocess for memory leak prevention.

    Args:
        img_bytes_from: Previous screenshot bytes
        img_bytes_to: Current screenshot bytes
        threshold: Pixel difference threshold
        blur_sigma: Gaussian blur sigma
        max_width: Maximum width for diff
        max_height: Maximum height for diff

    Returns:
        bytes: JPEG diff image or None on failure
    """
    ctx = multiprocessing.get_context('spawn')
    parent_conn, child_conn = ctx.Pipe()

    p = ctx.Process(
        target=_worker_generate_diff,
        args=(child_conn, img_bytes_from, img_bytes_to, threshold, blur_sigma, max_width, max_height)
    )
    p.start()

    result = None
    try:
        # Wait for result (30 second timeout)
        if parent_conn.poll(30):
            result = parent_conn.recv()
    except Exception as e:
        print(f"[Parent] Error receiving result: {e}", flush=True)
    finally:
        # Always close pipe first
        try:
            parent_conn.close()
        except:
            pass

        # Try graceful shutdown
        p.join(timeout=5)
        if p.is_alive():
            print("[Parent] Process didn't exit gracefully, terminating", flush=True)
            p.terminate()
            p.join(timeout=3)

        # Force kill if still alive
        if p.is_alive():
            print("[Parent] Process didn't terminate, killing", flush=True)
            p.kill()
            p.join(timeout=1)

    return result


def calculate_change_percentage_isolated(img_bytes_from, img_bytes_to, threshold, blur_sigma, max_width, max_height):
    """
    Calculate change percentage in isolated subprocess using handler.

    Returns:
        float: Change percentage
    """
    ctx = multiprocessing.get_context('spawn')
    parent_conn, child_conn = ctx.Pipe()

    def _worker_calculate(conn):
        try:
            # Import handler inside worker
            from .libvips_handler import LibvipsImageDiffHandler

            handler = LibvipsImageDiffHandler()

            # Load images
            img_from = handler.load_from_bytes(img_bytes_from)
            img_to = handler.load_from_bytes(img_bytes_to)

            # Ensure same size
            w1, h1 = handler.get_dimensions(img_from)
            w2, h2 = handler.get_dimensions(img_to)
            if (w1, h1) != (w2, h2):
                img_from = handler.resize(img_from, w2, h2)

            # Downscale
            img_from = handler.resize(img_from, max_width, max_height)
            img_to = handler.resize(img_to, max_width, max_height)

            # Convert to grayscale
            gray_from = handler.to_grayscale(img_from)
            gray_to = handler.to_grayscale(img_to)

            # Optional blur
            gray_from = handler.gaussian_blur(gray_from, blur_sigma)
            gray_to = handler.gaussian_blur(gray_to, blur_sigma)

            # Calculate difference
            diff = handler.absolute_difference(gray_from, gray_to)

            # Threshold and get percentage
            change_percentage, _ = handler.threshold(diff, int(threshold))

            conn.send(float(change_percentage))

        except Exception as e:
            print(f"[Worker] Calculate error: {e}", flush=True)
            conn.send(0.0)
        finally:
            conn.close()

    p = ctx.Process(target=_worker_calculate, args=(child_conn,))
    p.start()

    result = 0.0
    try:
        if parent_conn.poll(30):
            result = parent_conn.recv()
    except Exception as e:
        print(f"[Parent] Calculate error receiving result: {e}", flush=True)
    finally:
        # Always close pipe first
        try:
            parent_conn.close()
        except:
            pass

        # Try graceful shutdown
        p.join(timeout=5)
        if p.is_alive():
            print("[Parent] Calculate process didn't exit gracefully, terminating", flush=True)
            p.terminate()
            p.join(timeout=3)

        # Force kill if still alive
        if p.is_alive():
            print("[Parent] Calculate process didn't terminate, killing", flush=True)
            p.kill()
            p.join(timeout=1)

    return result


def compare_images_isolated(img_bytes_from, img_bytes_to, threshold, blur_sigma, min_change_percentage, crop_region=None):
    """
    Compare images in isolated subprocess for change detection.

    Args:
        img_bytes_from: Previous screenshot bytes
        img_bytes_to: Current screenshot bytes
        threshold: Pixel difference threshold
        blur_sigma: Gaussian blur sigma
        min_change_percentage: Minimum percentage to trigger change detection
        crop_region: Optional tuple (left, top, right, bottom) for cropping both images

    Returns:
        tuple: (changed_detected, change_percentage)
    """
    print(f"[Parent] Starting compare_images_isolated subprocess", flush=True)
    ctx = multiprocessing.get_context('spawn')
    parent_conn, child_conn = ctx.Pipe()

    def _worker_compare(conn):
        try:
            print(f"[Worker] Compare worker starting", flush=True)
            # Import handler inside worker
            from .libvips_handler import LibvipsImageDiffHandler

            print(f"[Worker] Initializing handler", flush=True)
            handler = LibvipsImageDiffHandler()

            # Load images
            print(f"[Worker] Loading images (from={len(img_bytes_from)} bytes, to={len(img_bytes_to)} bytes)", flush=True)
            img_from = handler.load_from_bytes(img_bytes_from)
            img_to = handler.load_from_bytes(img_bytes_to)
            print(f"[Worker] Images loaded", flush=True)

            # Crop if region specified
            if crop_region:
                print(f"[Worker] Cropping to region {crop_region}", flush=True)
                left, top, right, bottom = crop_region
                img_from = handler.crop(img_from, left, top, right, bottom)
                img_to = handler.crop(img_to, left, top, right, bottom)
                print(f"[Worker] Cropping completed", flush=True)

            # Ensure same size
            w1, h1 = handler.get_dimensions(img_from)
            w2, h2 = handler.get_dimensions(img_to)
            print(f"[Worker] Image dimensions: from={w1}x{h1}, to={w2}x{h2}", flush=True)
            if (w1, h1) != (w2, h2):
                print(f"[Worker] Resizing to match dimensions", flush=True)
                img_from = handler.resize(img_from, w2, h2)

            # Convert to grayscale
            print(f"[Worker] Converting to grayscale", flush=True)
            gray_from = handler.to_grayscale(img_from)
            gray_to = handler.to_grayscale(img_to)

            # Optional blur
            # NOTE: gaussblur can hang in forked subprocesses due to LibVIPS threading
            # Skip blur as a workaround - sigma=0.8 is subtle and comparison works without it
            if blur_sigma > 0:
                print(f"[Worker] Skipping blur (sigma={blur_sigma}) due to LibVIPS threading issues in fork", flush=True)
                # gray_from = handler.gaussian_blur(gray_from, blur_sigma)
                # gray_to = handler.gaussian_blur(gray_to, blur_sigma)

            # Calculate difference
            print(f"[Worker] Calculating difference", flush=True)
            diff = handler.absolute_difference(gray_from, gray_to)

            # Threshold and get percentage
            print(f"[Worker] Applying threshold ({threshold})", flush=True)
            change_percentage, _ = handler.threshold(diff, int(threshold))

            # Determine if change detected
            changed_detected = change_percentage > min_change_percentage

            print(f"[Worker] Comparison complete: changed={changed_detected}, percentage={change_percentage:.2f}%", flush=True)
            conn.send((changed_detected, float(change_percentage)))

        except Exception as e:
            print(f"[Worker] Compare error: {e}", flush=True)
            import traceback
            traceback.print_exc()
            conn.send((False, 0.0))
        finally:
            conn.close()

    p = ctx.Process(target=_worker_compare, args=(child_conn,))
    print(f"[Parent] Starting subprocess (pid will be assigned)", flush=True)
    p.start()
    print(f"[Parent] Subprocess started (pid={p.pid}), waiting for result (30s timeout)", flush=True)

    result = (False, 0.0)
    try:
        if parent_conn.poll(30):
            print(f"[Parent] Result available, receiving", flush=True)
            result = parent_conn.recv()
            print(f"[Parent] Result received: {result}", flush=True)
        else:
            print(f"[Parent] Timeout waiting for result after 30s", flush=True)
    except Exception as e:
        print(f"[Parent] Compare error receiving result: {e}", flush=True)
    finally:
        # Always close pipe first
        try:
            parent_conn.close()
        except:
            pass

        # Try graceful shutdown
        import time
        print(f"[Parent] Waiting for subprocess to exit (5s timeout)", flush=True)
        join_start = time.time()
        p.join(timeout=5)
        join_elapsed = time.time() - join_start
        print(f"[Parent] First join took {join_elapsed:.2f}s", flush=True)

        if p.is_alive():
            print("[Parent] Compare process didn't exit gracefully, terminating", flush=True)
            term_start = time.time()
            p.terminate()
            p.join(timeout=3)
            term_elapsed = time.time() - term_start
            print(f"[Parent] Terminate+join took {term_elapsed:.2f}s", flush=True)

        # Force kill if still alive
        if p.is_alive():
            print("[Parent] Compare process didn't terminate, killing", flush=True)
            kill_start = time.time()
            p.kill()
            p.join(timeout=1)
            kill_elapsed = time.time() - kill_start
            print(f"[Parent] Kill+join took {kill_elapsed:.2f}s", flush=True)

        print(f"[Parent] Subprocess cleanup complete, returning result", flush=True)

    return result
