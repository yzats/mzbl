import pytest
from unittest.mock import MagicMock
import requests

from src.removers.base import (
    BaseBackgroundRemover,
    BackgroundRemoverError,
    RetryableBackgroundRemoverError,
    NonRetryableBackgroundRemoverError,
)
from src.removers.rembg_http import RembgHostedRemover


class DummyRemover(BaseBackgroundRemover):
    """Concrete implementation for testing abstract base class."""
    def remove_background(
        self, image_data: bytes, bg_color: str | None = "#ffffff"
    ) -> bytes:
        if not image_data:
            raise NonRetryableBackgroundRemoverError("Empty image")
        return b"processed_" + image_data


def test_base_remover_contract():
    remover = DummyRemover()
    assert isinstance(remover, BaseBackgroundRemover)
    assert remover.remove_background(b"test") == b"processed_test"
    with pytest.raises(BackgroundRemoverError):
        remover.remove_background(b"")


def test_rembg_hosted_remover_success(mocker):
    fake_input_image = b"fake_jpeg_data"
    fake_output_image = b"fake_png_bytes_from_api"

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = fake_output_image

    mocker.patch("requests.post", return_value=mock_response)

    remover = RembgHostedRemover(api_url="https://api.rembg.com/rmbg", api_key="secret-token")
    result = remover.remove_background(fake_input_image, bg_color="#ffffff")

    assert result == fake_output_image
    requests.post.assert_called_once()
    
    call_args, call_kwargs = requests.post.call_args
    assert call_args[0] == "https://api.rembg.com/rmbg"
    assert call_kwargs["headers"] == {"x-api-key": "secret-token"}
    assert call_kwargs["data"] == {"format": "png", "bg_color": "#ffffff"}
    assert "image" in call_kwargs["files"]


def test_rembg_hosted_remover_empty_input():
    remover = RembgHostedRemover(api_url="https://api.rembg.com/rmbg")
    with pytest.raises(NonRetryableBackgroundRemoverError, match="cannot be empty"):
        remover.remove_background(b"")


def test_rembg_hosted_remover_retryable_503(mocker):
    mocker.patch("time.sleep")  # Skip sleep delay in unit test
    mock_503 = MagicMock(status_code=503, text="Service Unavailable")
    mock_200 = MagicMock(status_code=200, content=b"fake_png_data")

    mocker.patch("requests.post", side_effect=[mock_503, mock_503, mock_200])

    remover = RembgHostedRemover(
        api_url="https://api.rembg.com/rmbg", max_retries=3, backoff_delay=0.01
    )
    result = remover.remove_background(b"fake_image")
    assert result == b"fake_png_data"
    assert requests.post.call_count == 3


def test_rembg_hosted_remover_non_retryable_400(mocker):
    mocker.patch("time.sleep")
    mock_400 = MagicMock(status_code=400, text="Bad Request / Invalid image")

    mocker.patch("requests.post", return_value=mock_400)

    remover = RembgHostedRemover(api_url="https://api.rembg.com/rmbg")
    with pytest.raises(NonRetryableBackgroundRemoverError, match="HTTP 400"):
        remover.remove_background(b"fake_image")
    assert requests.post.call_count == 1  # Should NOT retry on 400
