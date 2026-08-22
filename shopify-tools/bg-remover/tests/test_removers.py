import pytest
from io import BytesIO
from unittest.mock import MagicMock
from PIL import Image
import requests

from src.removers.base import (
    BaseBackgroundRemover,
    BackgroundRemoverError,
    RetryableBackgroundRemoverError,
    NonRetryableBackgroundRemoverError,
    RembgUnavailableError,
)
from src.removers.rembg_http import RembgHostedRemover


def _png_bytes(width: int, height: int) -> bytes:
    buf = BytesIO()
    Image.new("RGB", (width, height), (255, 255, 255)).save(buf, format="PNG")
    return buf.getvalue()



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


def test_rembg_hosted_remover_401_unavailable_no_retry(mocker):
    mocker.patch("time.sleep")
    mock_401 = MagicMock(status_code=401, text="Unauthorized")
    mocker.patch("requests.post", return_value=mock_401)

    remover = RembgHostedRemover(api_url="https://api.rembg.com/rmbg")
    with pytest.raises(RembgUnavailableError, match="HTTP 401"):
        remover.remove_background(b"fake_image")
    assert requests.post.call_count == 1


def test_rembg_hosted_remover_402_unavailable(mocker):
    mocker.patch("time.sleep")
    mock_402 = MagicMock(status_code=402, text="Payment Required")
    mocker.patch("requests.post", return_value=mock_402)

    remover = RembgHostedRemover(api_url="https://api.rembg.com/rmbg")
    with pytest.raises(RembgUnavailableError, match="HTTP 402"):
        remover.remove_background(b"fake_image")


def test_rmbg_429_monthly_limit_is_unavailable(mocker):
    mocker.patch("time.sleep")
    body = (
        '{"error":"You\'ve reached your monthly limit. Consider purchasing more credits.",'
        '"status":429}'
    )
    mocker.patch("requests.post", return_value=MagicMock(status_code=429, text=body))

    remover = RembgHostedRemover(api_url="https://api.rembg.com/rmbg", api_key="k")
    with pytest.raises(RembgUnavailableError, match="monthly/credit limit"):
        remover.remove_background(b"fake_image")
    assert requests.post.call_count == 1


def test_rmbg_429_rate_limit_is_retryable(mocker):
    mocker.patch("time.sleep")
    body = (
        '{"error":"You\'re making requests too quickly, Please Upgrade or slow down.",'
        '"status":429}'
    )
    mocker.patch("requests.post", return_value=MagicMock(status_code=429, text=body))

    remover = RembgHostedRemover(
        api_url="https://api.rembg.com/rmbg", api_key="k", max_retries=2, backoff_delay=0.01
    )
    with pytest.raises(RetryableBackgroundRemoverError, match="HTTP 429"):
        remover.remove_background(b"fake_image")
    assert requests.post.call_count == 3


def test_rembg_error_message_texts_single_and_multiple():
    from src.removers.rembg_http import rembg_error_message_texts, rembg_429_is_credit_exhaustion

    single = '{"error":"You\'ve reached your monthly limit. Consider purchasing more credits.","status":429}'
    assert rembg_429_is_credit_exhaustion(single) is True

    multi = (
        '{"error":"Multiple validation errors","details":['
        '{"field":"image","message":"Consider purchasing more credits."}'
        '],"status":429}'
    )
    texts = rembg_error_message_texts(multi)
    assert "Multiple validation errors" in texts
    assert "Consider purchasing more credits." in texts
    assert rembg_429_is_credit_exhaustion(multi) is True

    rate = '{"error":"You\'re making requests too quickly, Please Upgrade or slow down.","status":429}'
    assert rembg_429_is_credit_exhaustion(rate) is False
    assert rembg_429_is_credit_exhaustion("You've reached your daily limit.") is False


def test_membership_has_credits():
    from src.removers.rembg_http import membership_has_credits

    assert membership_has_credits({"credits": 5, "prepaidCredits": 0}) is True
    assert membership_has_credits({"credits": 0, "prepaidCredits": 3}) is True
    assert membership_has_credits({"credits": 0, "prepaidCredits": 0}) is False
    assert membership_has_credits({}) is False


def test_membership_usage_ready(mocker):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = '{"credits":0,"prepaidCredits":8}'
    mock_response.json.return_value = {"credits": 0, "prepaidCredits": 8}
    mocker.patch("requests.get", return_value=mock_response)

    remover = RembgHostedRemover(api_key="secret-token")
    payload = remover.check_account_ready()
    assert payload["prepaidCredits"] == 8
    requests.get.assert_called_once()
    assert requests.get.call_args[0][0] == "https://www.rembg.com/api/membership-usage"
    assert requests.get.call_args[1]["headers"] == {"x-api-key": "secret-token"}


def test_membership_usage_zero_credits(mocker):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = '{"credits":0,"prepaidCredits":0}'
    mock_response.json.return_value = {"credits": 0, "prepaidCredits": 0}
    mocker.patch("requests.get", return_value=mock_response)

    remover = RembgHostedRemover(api_key="secret-token")
    with pytest.raises(RembgUnavailableError, match="no usable credits"):
        remover.check_account_ready()


def test_membership_usage_401(mocker):
    mock_response = MagicMock(status_code=401, text="Unauthorized")
    mock_response.json.side_effect = ValueError("not json")
    mocker.patch("requests.get", return_value=mock_response)

    remover = RembgHostedRemover(api_key="bad")
    with pytest.raises(RembgUnavailableError, match="HTTP 401"):
        remover.check_account_ready()


def test_membership_usage_non_200_still_returns_credit_fields(mocker):
    mock_response = MagicMock(status_code=402, text='{"credits":0,"prepaidCredits":2}')
    mock_response.json.return_value = {"credits": 0, "prepaidCredits": 2}
    mocker.patch("requests.get", return_value=mock_response)

    remover = RembgHostedRemover(api_key="secret-token")
    assert remover.get_membership_usage() == {"credits": 0, "prepaidCredits": 2}


@pytest.mark.parametrize(
    "in_wh, out_wh, expected",
    [
        ((800, 600), (460, 460), True),
        ((800, 600), (460, 400), True),
        ((2000, 2000), (460, 460), True),
        ((469, 469), (460, 460), True),
        ((500, 50), (460, 46), True),
        ((800, 600), (800, 600), False),
        ((2000, 2000), (1000, 1000), False),
        ((400, 300), (400, 300), False),
        ((460, 460), (460, 460), False),
        ((461, 461), (460, 460), False),
        ((468, 468), (460, 460), False),
        ((2000, 2000), (461, 461), False),
        (None, (460, 460), False),
    ],
    ids=[
        "800x600_to_460x460",
        "800x600_to_460x400",
        "2000_to_460",
        "469_to_460_over_leeway",
        "wide_500x50_to_460_box",
        "800x600_unchanged",
        "2000_to_1000_not_free_box",
        "already_small_400x300",
        "already_at_cap_460",
        "461_to_460_within_leeway",
        "468_to_460_at_leeway",
        "2000_to_461_outside_free_box",
        "unreadable_input",
    ],
)
def test_output_is_freemium_capped(in_wh, out_wh, expected):
    from src.removers.rembg_http import output_is_freemium_capped

    inp = _png_bytes(*in_wh) if in_wh else b"not-an-image"
    out = _png_bytes(*out_wh)
    assert output_is_freemium_capped(inp, out) is expected


def test_rembg_200_freemium_cap_is_unavailable(mocker):
    large = _png_bytes(800, 600)
    capped = _png_bytes(460, 400)
    mock_response = MagicMock(status_code=200, content=capped)
    mocker.patch("requests.post", return_value=mock_response)

    remover = RembgHostedRemover(api_url="https://api.rembg.com/rmbg")
    with pytest.raises(RembgUnavailableError, match="460x460"):
        remover.remove_background(large)
    assert requests.post.call_count == 1


def test_rembg_200_paid_resolution_ok(mocker):
    large = _png_bytes(800, 600)
    mock_response = MagicMock(status_code=200, content=large)
    mocker.patch("requests.post", return_value=mock_response)

    remover = RembgHostedRemover(api_url="https://api.rembg.com/rmbg")
    assert remover.remove_background(large) == large


def test_rembg_200_half_size_not_freemium(mocker):
    """2000→1000 is a large shrink but still outside the 460×460 free API box."""
    src = _png_bytes(2000, 2000)
    out = _png_bytes(1000, 1000)
    mocker.patch("requests.post", return_value=MagicMock(status_code=200, content=out))

    remover = RembgHostedRemover(api_url="https://api.rembg.com/rmbg")
    assert remover.remove_background(src) == out


def test_fault_inject_out_of_credits_skips_rmbg(monkeypatch, mocker):
    monkeypatch.setenv("REMBG_FAULT_INJECT", "out_of_credits")
    post = mocker.patch("requests.post")
    remover = RembgHostedRemover(api_url="https://api.rembg.com/rmbg")
    with pytest.raises(RembgUnavailableError, match="monthly/credit limit"):
        remover.remove_background(b"fake_jpeg_data")
    post.assert_not_called()


def test_fault_inject_out_of_credits_membership_zeros(monkeypatch, mocker):
    monkeypatch.setenv("REMBG_FAULT_INJECT", "out_of_credits")
    get = mocker.patch("requests.get")
    remover = RembgHostedRemover(api_key="secret-token")
    assert remover.get_membership_usage() == {"credits": 0, "prepaidCredits": 0}
    get.assert_not_called()
    with pytest.raises(RembgUnavailableError, match="no usable credits"):
        remover.check_account_ready()
    get.assert_not_called()


def test_fault_inject_other_value_uses_http(monkeypatch, mocker):
    monkeypatch.setenv("REMBG_FAULT_INJECT", "rate_limit")
    mocker.patch("requests.post", return_value=MagicMock(status_code=200, content=b"ok"))
    remover = RembgHostedRemover(api_url="https://api.rembg.com/rmbg")
    assert remover.remove_background(b"fake_jpeg_data") == b"ok"
    requests.post.assert_called_once()

