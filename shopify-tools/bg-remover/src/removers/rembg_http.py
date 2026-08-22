import json
import os

from src.utils import applog
from io import BytesIO
from typing import Any, Dict, List, Optional, Tuple

import requests
from PIL import Image
from .base import (
    BaseBackgroundRemover,
    BackgroundRemoverError,
    RetryableBackgroundRemoverError,
    NonRetryableBackgroundRemoverError,
    RembgUnavailableError,
)
from ..utils.retry import retry_with_exponential_backoff

DEFAULT_MEMBERSHIP_USAGE_URL = "https://www.rembg.com/api/membership-usage"

# https://www.rembg.com/en/pricing — Free API max resolution 460×460
FREEMIUM_API_MAX_EDGE = 460
# Ignore sources only slightly above 460 (e.g. 461→460). Freemium is a large original stuffed into 460×460.
FREEMIUM_SHRINK_LEEWAY_PX = 8
# https://www.rembg.com/en/api-usage — monthly credits 429 vs short-term rate limit 429
_CREDIT_EXHAUSTION_NEEDLES = ("monthly limit", "purchasing")
FAULT_INJECT_ENV = "REMBG_FAULT_INJECT"
FAULT_OUT_OF_CREDITS = "out_of_credits"
FAULT_INJECT_LOG = "[FAULT INJECT] rembg out_of_credits"
_FAULT_CREDIT_429_BODY = (
    '{"error":"You\'ve reached your monthly limit. Consider purchasing more credits.",'
    '"status":429}'
)


def rembg_fault_inject() -> str:
    """Runtime fault flag from REMBG_FAULT_INJECT (empty if unset)."""
    return (os.environ.get(FAULT_INJECT_ENV) or "").strip().lower()


def rembg_out_of_credits_fault() -> bool:
    return rembg_fault_inject() == FAULT_OUT_OF_CREDITS


def rembg_error_message_texts(body: str) -> List[str]:
    """Collect human-readable strings from rembg single- or multi-error JSON (or raw text)."""
    if not body:
        return []
    try:
        payload = json.loads(body)
    except (TypeError, ValueError):
        return [body]
    if not isinstance(payload, dict):
        return [body]

    texts: List[str] = []
    err = payload.get("error")
    if isinstance(err, str) and err.strip():
        texts.append(err)
    details = payload.get("details")
    if isinstance(details, list):
        for item in details:
            if isinstance(item, dict):
                msg = item.get("message")
                if isinstance(msg, str) and msg.strip():
                    texts.append(msg)
            elif isinstance(item, str) and item.strip():
                texts.append(item)
    return texts or [body]


def rembg_429_is_credit_exhaustion(body: str) -> bool:
    """True if a 429 body looks like monthly/prepaid credit exhaustion, not a short-term rate limit."""
    blob = " ".join(rembg_error_message_texts(body)).lower()
    return any(needle in blob for needle in _CREDIT_EXHAUSTION_NEEDLES)


def image_pixel_size(data: bytes) -> Optional[Tuple[int, int]]:
    """Return (width, height) or None if the bytes are not a readable image."""
    if not data:
        return None
    try:
        with Image.open(BytesIO(data)) as im:
            return im.size
    except Exception:
        return None


def output_is_freemium_capped(input_data: bytes, output_data: bytes) -> bool:
    """True when output fits the free 460×460 API box and the source was clearly larger.

    Leeway is on how far the *input* sat above 460, not an isolated longest-side
    shrink. 461→460 is allowed; 800→460 is not.
    """
    src = image_pixel_size(input_data)
    out = image_pixel_size(output_data)
    if src is None or out is None:
        return False
    in_w, in_h = src
    out_w, out_h = out
    if in_w <= FREEMIUM_API_MAX_EDGE and in_h <= FREEMIUM_API_MAX_EDGE:
        return False
    if out_w > FREEMIUM_API_MAX_EDGE or out_h > FREEMIUM_API_MAX_EDGE:
        return False
    return max(in_w, in_h) > FREEMIUM_API_MAX_EDGE + FREEMIUM_SHRINK_LEEWAY_PX


def _raise_for_rmbg_429(body: str) -> None:
    """HTTP 429 is short-term rate limit or monthly credit exhaustion (same status).

    See https://www.rembg.com/en/api-usage error reference.
    """
    if rembg_429_is_credit_exhaustion(body):
        raise RembgUnavailableError(
            f"Rembg monthly/credit limit (HTTP 429): {body}"
        )
    raise RetryableBackgroundRemoverError(
        f"Transient rembg API rate limit (HTTP 429): {body}"
    )


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
            RetryableBackgroundRemoverError: On transient network, rate limits (429 with credits remaining), or server errors (5xx).
            RembgUnavailableError: On rembg credits/auth (401, 402, 403), HTTP 429 credit-exhaustion text, or HTTP 200 whose output is capped at the free API 460×460 box while the input was larger.
            NonRetryableBackgroundRemoverError: On permanent client errors (400, 404, 415, 422).
        """
        if not image_data:
            raise NonRetryableBackgroundRemoverError("Input image bytes cannot be empty.")

        if rembg_out_of_credits_fault():
            applog.warning(FAULT_INJECT_LOG)
            raise RembgUnavailableError(
                f"Rembg monthly/credit limit (HTTP 429): {FAULT_INJECT_LOG} {_FAULT_CREDIT_429_BODY}"
            )

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

            if response.status_code == 429:
                _raise_for_rmbg_429(response.text)
            raise_for_rembg_status(response.status_code, response.text, context="API")

            if not response.content:
                raise NonRetryableBackgroundRemoverError("rembg API returned empty response content.")

            if output_is_freemium_capped(image_data, response.content):
                in_size = image_pixel_size(image_data)
                out_size = image_pixel_size(response.content)
                raise RembgUnavailableError(
                    "Rembg returned free-tier max resolution 460x460 "
                    f"(input={in_size[0]}x{in_size[1]}, output={out_size[0]}x{out_size[1]}); "
                    "treat as out of credits and do not use the image"
                )

            return response.content

        return _send_request()

    def get_membership_usage(self) -> Dict[str, Any]:
        """GET www.rembg.com /api/membership-usage (account liveness and credits).

        See https://www.rembg.com/api/docs#tag/account
        """
        if rembg_out_of_credits_fault():
            applog.warning(FAULT_INJECT_LOG)
            return {"credits": 0, "prepaidCredits": 0}

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

        try:
            payload = response.json()
        except ValueError:
            payload = None

        # Prefer account numbers for the dashboard even when rembg uses a non-200 status.
        if isinstance(payload, dict) and (
            "credits" in payload or "prepaidCredits" in payload
        ):
            return payload

        raise_for_rembg_status(response.status_code, response.text, context="membership-usage")

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
