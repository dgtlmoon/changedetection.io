"""
Subprocess-isolated utility functions for image operations.

These functions use multiprocessing to run image operations in separate
processes, ensuring complete memory cleanup. Raw bytes are passed via
Pipe to avoid pickle overhead for large objects.
"""

import multiprocessing
from loguru import logger


def _worker_find_region_with_template_matching(conn, original_bbox, search_tolerance):
    """
    Worker function for template matching (runs in subprocess).

    Receives via pipe: (current_img_bytes, template_bytes)
    Sends via pipe: new_bbox [left, top, right, bottom] or None
    """
    import cv2
    import numpy as np
    from PIL import Image
    import io

    try:
        # Receive image data from parent process
        current_img_bytes, template_bytes = conn.recv()

        # Load images from bytes
        template_img = Image.open(io.BytesIO(template_bytes))
        template_img.load()

        current_img = Image.open(io.BytesIO(current_img_bytes))
        current_img.load()

        # Calculate search region
        left, top, right, bottom = original_bbox
        width = right - left
        height = bottom - top

        margin_x = int(width * search_tolerance)
        margin_y = int(height * search_tolerance)

        search_left = max(0, left - margin_x)
        search_top = max(0, top - margin_y)
        search_right = min(current_img.width, right + margin_x)
        search_bottom = min(current_img.height, bottom + margin_y)

        # Crop search region
        current_img_cropped = current_img.crop((search_left, search_top, search_right, search_bottom)).copy()
        current_img_cropped.load()

        # Convert to numpy arrays
        current_array = np.array(current_img_cropped)
        template_array = np.array(template_img)

        # Convert to grayscale
        if len(current_array.shape) == 3:
            current_gray = cv2.cvtColor(current_array, cv2.COLOR_RGB2GRAY)
        else:
            current_gray = current_array

        if len(template_array.shape) == 3:
            template_gray = cv2.cvtColor(template_array, cv2.COLOR_RGB2GRAY)
        else:
            template_gray = template_array

        logger.debug(f"[subprocess] Searching for template in region: ({search_left}, {search_top}) to ({search_right}, {search_bottom})")

        # Perform template matching
        result = cv2.matchTemplate(current_gray, template_gray, cv2.TM_CCOEFF_NORMED)
        min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)

        logger.debug(f"[subprocess] Template matching confidence: {max_val:.2%}")

        # Check if match is good enough (80% confidence threshold)
        if max_val >= 0.8:
            # Calculate new bounding box in original image coordinates
            match_x = search_left + max_loc[0]
            match_y = search_top + max_loc[1]

            new_bbox = [match_x, match_y, match_x + width, match_y + height]

            # Calculate movement distance
            move_x = abs(match_x - left)
            move_y = abs(match_y - top)

            logger.info(f"[subprocess] Template found at ({match_x}, {match_y}), "
                       f"moved {move_x}px horizontally, {move_y}px vertically, "
                       f"confidence: {max_val:.2%}")

            conn.send(new_bbox)
        else:
            logger.warning(f"[subprocess] Template match confidence too low: {max_val:.2%} (need 80%)")
            conn.send(None)

    except Exception as e:
        logger.error(f"[subprocess] Template matching error: {e}")
        conn.send(None)
    finally:
        conn.close()


def _worker_regenerate_template(conn, bbox):
    """
    Worker function for template regeneration (runs in subprocess).

    Receives via pipe: (snapshot_img_bytes, output_path)
    Sends via pipe: True/False for success
    """
    from PIL import Image
    import io
    import os

    try:
        # Receive data from parent process
        snapshot_img_bytes, output_path = conn.recv()

        left, top, right, bottom = bbox
        width = right - left
        height = bottom - top

        # Ensure output directory exists
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        # Load snapshot from bytes
        snapshot_img = Image.open(io.BytesIO(snapshot_img_bytes))
        snapshot_img.load()

        # Crop template region
        template = snapshot_img.crop(tuple(bbox)).copy()
        template.load()

        # Save as PNG
        template.save(output_path, format='PNG', optimize=True)

        logger.info(f"[subprocess] Regenerated template: {output_path} ({width}x{height}px)")
        conn.send(True)

    except Exception as e:
        logger.error(f"[subprocess] Failed to regenerate template: {e}")
        conn.send(False)
    finally:
        conn.close()


def _worker_crop_image(conn, bbox):
    """
    Worker function for image cropping (runs in subprocess).

    Receives via pipe: input_img_bytes
    Sends via pipe: cropped_img_bytes or None
    """
    from PIL import Image
    import io

    try:
        # Receive image data from parent process
        input_img_bytes = conn.recv()

        # Load image from bytes
        img = Image.open(io.BytesIO(input_img_bytes))
        img.load()

        # Crop and force independent buffer
        cropped = img.crop(tuple(bbox)).copy()
        cropped.load()

        # Convert back to bytes
        output = io.BytesIO()
        cropped.save(output, format='PNG', optimize=True)
        cropped_bytes = output.getvalue()

        logger.debug(f"[subprocess] Cropped image: {cropped.size}")
        conn.send(cropped_bytes)

    except Exception as e:
        logger.error(f"[subprocess] Failed to crop image: {e}")
        conn.send(None)
    finally:
        conn.close()


# Public API functions

def find_region_with_template_matching_isolated(
    current_img_bytes,
    template_bytes,
    original_bbox,
    search_tolerance=0.2
):
    """
    Find region using template matching in isolated subprocess.

    Args:
        current_img_bytes: Current screenshot as PNG bytes
        template_bytes: Template image as PNG bytes
        original_bbox: (left, top, right, bottom) tuple
        search_tolerance: How far to search (0.2 = ±20% of region size)

    Returns:
        tuple: New (left, top, right, bottom) region, or None if not found
    """
    parent_conn, child_conn = multiprocessing.Pipe()

    # Start subprocess
    p = multiprocessing.Process(
        target=_worker_find_region_with_template_matching,
        args=(child_conn, original_bbox, search_tolerance)
    )
    p.start()

    try:
        # Send image data to subprocess
        parent_conn.send((current_img_bytes, template_bytes))

        # Wait for result
        result = parent_conn.recv()

        # Convert list back to tuple if we got a result
        if result is not None:
            result = tuple(result)

        return result

    finally:
        parent_conn.close()
        p.join(timeout=30)  # 30 second timeout
        if p.is_alive():
            logger.warning("Template matching subprocess timed out, terminating")
            p.terminate()
            p.join()


def regenerate_template_isolated(snapshot_img_bytes, bbox, output_path):
    """
    Regenerate template file from snapshot in isolated subprocess.

    Args:
        snapshot_img_bytes: Snapshot image as PNG bytes
        bbox: (left, top, right, bottom) tuple
        output_path: Where to save the template PNG

    Returns:
        bool: True if successful, False otherwise
    """
    parent_conn, child_conn = multiprocessing.Pipe()

    # Start subprocess
    p = multiprocessing.Process(
        target=_worker_regenerate_template,
        args=(child_conn, bbox)
    )
    p.start()

    try:
        # Send data to subprocess
        parent_conn.send((snapshot_img_bytes, output_path))

        # Wait for result
        success = parent_conn.recv()
        return success

    finally:
        parent_conn.close()
        p.join(timeout=30)  # 30 second timeout
        if p.is_alive():
            logger.warning("Template regeneration subprocess timed out, terminating")
            p.terminate()
            p.join()


def crop_image_isolated(input_img_bytes, bbox):
    """
    Crop image in isolated subprocess.

    Args:
        input_img_bytes: Input image as PNG bytes
        bbox: (left, top, right, bottom) tuple

    Returns:
        bytes: Cropped image as PNG bytes, or None if failed
    """
    parent_conn, child_conn = multiprocessing.Pipe()

    # Start subprocess
    p = multiprocessing.Process(
        target=_worker_crop_image,
        args=(child_conn, bbox)
    )
    p.start()

    try:
        # Send image data to subprocess
        parent_conn.send(input_img_bytes)

        # Wait for result
        cropped_bytes = parent_conn.recv()
        return cropped_bytes

    finally:
        parent_conn.close()
        p.join(timeout=30)  # 30 second timeout
        if p.is_alive():
            logger.warning("Image crop subprocess timed out, terminating")
            p.terminate()
            p.join()
