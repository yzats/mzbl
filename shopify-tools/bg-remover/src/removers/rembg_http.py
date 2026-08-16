import requests
from typing import Optional
from .base import (
    BaseBackgroundRemover,
    BackgroundRemoverError,
    RetryableBackgroundRemoverError,
    NonRetryableBackgroundRemoverError,
)
from ..utils.retry import retry_with_exponential_backoff


class RembgHostedRemover(BaseBackgroundRemover):
    """Background remover implementation using rembg.com API endpoint (`https://api.rembg.com/rmbg`).
    
    API parameters supported:
      - `image`: File multipart upload
      - `x-api-key`: Header with API key
      - `format`: Output format ("png" or "webp", default: "png" for lossless transparency)
      - `bg_color`: Hex color (e.g. "#ffffff" or "#ffffffff")
    """

    def __init__(
        self,
        api_url: str = "https://api.rembg.com/rmbg",
        api_key: Optional[str] = None,
        output_format: str = "png",
        timeout: int = 30,
        max_retries: int = 3,
        backoff_delay: float = 1.0,
    ):
        """Initialize rembg.com remover client."""
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key
        self.output_format = output_format
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_delay = backoff_delay

    def remove_background(
        self,
        image_data: bytes,
        bg_color: Optional[str] = "#ffffff",
    ) -> bytes:
        """Sends raw image bytes to rembg.com API with exponential backoff retries.

        Args:
            image_data: Raw input image bytes.
            bg_color: Optional solid background color hex (e.g. "#ffffff").

        Returns:
            bytes: Output image bytes directly from API.

        Raises:
            RetryableBackgroundRemoverError: On transient network, rate limits (429), or server errors (5xx).
            NonRetryableBackgroundRemoverError: On permanent client errors (400, 401, 403, 404).
        """
        if not image_data:
            raise NonRetryableBackgroundRemoverError("Input image bytes cannot be empty.")

        @retry_with_exponential_backoff(
            retries=self.max_retries,
            backoff_in_seconds=self.backoff_delay,
            retryable_exceptions=(RetryableBackgroundRemoverError,),
        )
        def _send_request() -> bytes:
            headers = {}
            if self.api_key:
                headers["x-api-key"] = self.api_key

            data = {
                "format": self.output_format,
            }

            if bg_color:
                data["bg_color"] = bg_color

            files = {"image": ("image.jpg", image_data, "image/jpeg")}

            try:
                response = requests.post(
                    self.api_url,
                    files=files,
                    data=data,
                    headers=headers,
                    timeout=self.timeout,
                )
            except (requests.Timeout, requests.ConnectionError) as e:
                raise RetryableBackgroundRemoverError(
                    f"Transient network/timeout error connecting to rembg API: {e}"
                ) from e
            except requests.RequestException as e:
                raise NonRetryableBackgroundRemoverError(
                    f"Fatal request error connecting to rembg API: {e}"
                ) from e

            # Categorize HTTP status codes into Retryable vs Non-Retryable
            if response.status_code == 200:
                pass
            elif response.status_code in (429, 500, 502, 503, 504):
                raise RetryableBackgroundRemoverError(
                    f"Transient rembg API error (HTTP {response.status_code}): {response.text}"
                )
            elif response.status_code in (400, 401, 403, 404, 415, 422):
                raise NonRetryableBackgroundRemoverError(
                    f"Permanent rembg API client error (HTTP {response.status_code}): {response.text}"
                )
            else:
                raise NonRetryableBackgroundRemoverError(
                    f"Unexpected rembg API error (HTTP {response.status_code}): {response.text}"
                )

            if not response.content:
                raise NonRetryableBackgroundRemoverError("rembg API returned empty response content.")

            return response.content

        return _send_request()
