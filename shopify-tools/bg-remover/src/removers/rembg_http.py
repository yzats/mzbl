import requests
from typing import Any, Dict, Optional
from .base import (
    BaseBackgroundRemover,
    BackgroundRemoverError,
    RetryableBackgroundRemoverError,
    NonRetryableBackgroundRemoverError,
    RembgUnavailableError,
)
from ..utils.retry import retry_with_exponential_backoff

DEFAULT_MEMBERSHIP_USAGE_URL = "https://www.rembg.com/api/membership-usage"


def membership_has_credits(payload: Dict[str, Any]) -> bool:
    """True if rembg membership-usage reports usable credits or prepaidCredits."""

    def _as_number(value: Any) -> float:
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0

    return _as_number(payload.get("credits")) > 0 or _as_number(payload.get("prepaidCredits")) > 0


def raise_for_rembg_status(status_code: int, body: str, *, context: str = "rembg API") -> None:
    """Map rembg HTTP status codes onto the remover exception hierarchy."""
    if status_code == 200:
        return
    if status_code in (401, 402, 403):
        raise RembgUnavailableError(
            f"Rembg {context} credits or auth failure (HTTP {status_code}): {body}"
        )
    if status_code in (429, 500, 502, 503, 504):
        raise RetryableBackgroundRemoverError(
            f"Transient rembg {context} error (HTTP {status_code}): {body}"
        )
    if status_code in (400, 404, 415, 422):
        raise NonRetryableBackgroundRemoverError(
            f"Permanent rembg {context} client error (HTTP {status_code}): {body}"
        )
    raise NonRetryableBackgroundRemoverError(
        f"Unexpected rembg {context} error (HTTP {status_code}): {body}"
    )


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
        membership_usage_url: str = DEFAULT_MEMBERSHIP_USAGE_URL,
    ):
        """Initialize rembg.com remover client."""
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key
        self.output_format = output_format
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_delay = backoff_delay
        self.membership_usage_url = membership_usage_url.rstrip("/")

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
            RembgUnavailableError: On rembg credits/auth (401, 402, 403).
            NonRetryableBackgroundRemoverError: On permanent client errors (400, 404, 415, 422).
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

            raise_for_rembg_status(response.status_code, response.text, context="API")

            if not response.content:
                raise NonRetryableBackgroundRemoverError("rembg API returned empty response content.")

            return response.content

        return _send_request()

    def get_membership_usage(self) -> Dict[str, Any]:
        """GET www.rembg.com /api/membership-usage (account liveness and credits).

        See https://www.rembg.com/api/docs#tag/account
        """
        headers = {}
        if self.api_key:
            headers["x-api-key"] = self.api_key

        try:
            response = requests.get(
                self.membership_usage_url,
                headers=headers,
                timeout=self.timeout,
            )
        except (requests.Timeout, requests.ConnectionError) as e:
            raise RetryableBackgroundRemoverError(
                f"Transient network/timeout error connecting to rembg membership-usage: {e}"
            ) from e
        except requests.RequestException as e:
            raise NonRetryableBackgroundRemoverError(
                f"Fatal request error connecting to rembg membership-usage: {e}"
            ) from e

        raise_for_rembg_status(response.status_code, response.text, context="membership-usage")

        try:
            payload = response.json()
        except ValueError as e:
            raise NonRetryableBackgroundRemoverError(
                "rembg membership-usage returned non-JSON body."
            ) from e
        if not isinstance(payload, dict):
            raise NonRetryableBackgroundRemoverError(
                "rembg membership-usage returned a non-object JSON payload."
            )
        return payload

    def check_account_ready(self) -> Dict[str, Any]:
        """Confirm rembg is reachable and the account has credits or prepaidCredits > 0."""
        payload = self.get_membership_usage()
        if not membership_has_credits(payload):
            raise RembgUnavailableError(
                "Rembg account has no usable credits "
                f"(credits={payload.get('credits')}, prepaidCredits={payload.get('prepaidCredits')})"
            )
        return payload
