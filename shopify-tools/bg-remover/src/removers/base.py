from abc import ABC, abstractmethod
from typing import Optional


class BackgroundRemoverError(Exception):
    """Base exception for background remover errors."""
    pass


class RetryableBackgroundRemoverError(BackgroundRemoverError):
    """Exception raised for transient/retryable errors (e.g. HTTP 429, HTTP 502/503/504, network timeouts)."""
    pass


class NonRetryableBackgroundRemoverError(BackgroundRemoverError):
    """Exception raised for permanent errors (e.g. HTTP 400 Bad Request, HTTP 401 Unauthorized, corrupted image)."""
    pass


class BaseBackgroundRemover(ABC):
    """Abstract base class for background removal implementations.
    
    This interface ensures that background removal providers can be configured
    and called cleanly without changing Shopify API, CLI, or queue logic.
    """

    @abstractmethod
    def remove_background(
        self, image_data: bytes, bg_color: Optional[str] = "#FFFFFF"
    ) -> bytes:
        """Remove background from image bytes.

        Args:
            image_data: Raw input image bytes (JPEG, PNG, WEBP, etc.).
            bg_color: Hex color code for new background (e.g., "#FFFFFF" for white, None/"" for transparent).
                      Defaults to white ("#FFFFFF").

        Returns:
            bytes: Raw output image bytes with background processed/replaced.

        Raises:
            RetryableBackgroundRemoverError: On transient network, rate limit (429), or 5xx server errors.
            NonRetryableBackgroundRemoverError: On permanent client errors (400, 401, 403, bad image format).
        """
        pass
