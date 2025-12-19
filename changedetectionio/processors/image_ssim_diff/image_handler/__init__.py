"""
Abstract base class for image processing operations.

All image operations for the image_ssim_diff processor must be implemented
through this interface to allow different backends (libvips, OpenCV, PIL, etc.).
"""

from abc import ABC, abstractmethod
from typing import Tuple, Optional, Any


class ImageDiffHandler(ABC):
    """
    Abstract base class for image processing operations.

    Implementations must handle all image operations needed for screenshot
    comparison including loading, cropping, resizing, diffing, and overlays.
    """

    @abstractmethod
    def load_from_bytes(self, img_bytes: bytes) -> Any:
        """
        Load image from bytes.

        Args:
            img_bytes: Image data as bytes (PNG, JPEG, etc.)

        Returns:
            Handler-specific image object
        """
        pass

    @abstractmethod
    def save_to_bytes(self, img: Any, format: str = 'png', quality: int = 85) -> bytes:
        """
        Save image to bytes.

        Args:
            img: Handler-specific image object
            format: Output format ('png' or 'jpeg')
            quality: Quality for JPEG (1-100)

        Returns:
            Image data as bytes
        """
        pass

    @abstractmethod
    def crop(self, img: Any, left: int, top: int, right: int, bottom: int) -> Any:
        """
        Crop image to specified region.

        Args:
            img: Handler-specific image object
            left: Left coordinate
            top: Top coordinate
            right: Right coordinate
            bottom: Bottom coordinate

        Returns:
            Cropped image object
        """
        pass

    @abstractmethod
    def resize(self, img: Any, max_width: int, max_height: int) -> Any:
        """
        Resize image maintaining aspect ratio.

        Args:
            img: Handler-specific image object
            max_width: Maximum width in pixels
            max_height: Maximum height in pixels

        Returns:
            Resized image object
        """
        pass

    @abstractmethod
    def get_dimensions(self, img: Any) -> Tuple[int, int]:
        """
        Get image dimensions.

        Args:
            img: Handler-specific image object

        Returns:
            Tuple of (width, height)
        """
        pass

    @abstractmethod
    def to_grayscale(self, img: Any) -> Any:
        """
        Convert image to grayscale.

        Args:
            img: Handler-specific image object

        Returns:
            Grayscale image object
        """
        pass

    @abstractmethod
    def gaussian_blur(self, img: Any, sigma: float) -> Any:
        """
        Apply Gaussian blur to image.

        Args:
            img: Handler-specific image object
            sigma: Blur sigma value (0 = no blur)

        Returns:
            Blurred image object
        """
        pass

    @abstractmethod
    def absolute_difference(self, img1: Any, img2: Any) -> Any:
        """
        Calculate absolute difference between two images.

        Args:
            img1: First image (handler-specific object)
            img2: Second image (handler-specific object)

        Returns:
            Difference image object
        """
        pass

    @abstractmethod
    def threshold(self, img: Any, threshold_value: int) -> Tuple[float, Any]:
        """
        Apply threshold to image and calculate change percentage.

        Args:
            img: Handler-specific image object (typically grayscale difference)
            threshold_value: Threshold value (0-255)

        Returns:
            Tuple of (change_percentage, binary_mask)
            - change_percentage: Percentage of pixels above threshold (0-100)
            - binary_mask: Handler-specific binary mask object
        """
        pass

    @abstractmethod
    def apply_red_overlay(self, img: Any, mask: Any) -> bytes:
        """
        Apply red overlay to image where mask is True.

        Args:
            img: Handler-specific image object (color)
            mask: Handler-specific binary mask object

        Returns:
            JPEG bytes with red overlay applied
        """
        pass

    @abstractmethod
    def close(self, img: Any) -> None:
        """
        Clean up image resources if needed.

        Args:
            img: Handler-specific image object
        """
        pass

    @abstractmethod
    def find_template(
        self,
        img: Any,
        template_img: Any,
        original_bbox: Tuple[int, int, int, int],
        search_tolerance: float = 0.2
    ) -> Optional[Tuple[int, int, int, int]]:
        """
        Find template in image using template matching.

        Args:
            img: Handler-specific image object to search in
            template_img: Handler-specific template image object to find
            original_bbox: Original bounding box (left, top, right, bottom)
            search_tolerance: How far to search (0.2 = ±20% of region size)

        Returns:
            New bounding box (left, top, right, bottom) or None if not found
        """
        pass

    @abstractmethod
    def save_template(
        self,
        img: Any,
        bbox: Tuple[int, int, int, int],
        output_path: str
    ) -> bool:
        """
        Save a cropped region as a template file.

        Args:
            img: Handler-specific image object
            bbox: Bounding box to crop (left, top, right, bottom)
            output_path: Where to save the template PNG

        Returns:
            True if successful, False otherwise
        """
        pass
