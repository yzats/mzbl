from unittest.mock import MagicMock

from process_product import process_product_batch
from src.shopify.metafields import (
    BG_STATE_RESULT,
    BG_STATE_SOURCE,
    bg_source_metafield,
    bg_state_metafield,
)


def test_process_product_batch_copies_alt_and_sets_bg_state():
    client = MagicMock()
    client.download_image_bytes.return_value = b"orig"
    remover = MagicMock()
    remover.remove_background.return_value = b"out"
    client.create_staged_upload.return_value = {"url": "https://upload", "resourceUrl": "https://cdn/staged"}
    client.upload_file_to_staged_target.return_value = "https://cdn/staged"
    client.create_product_media_batch.return_value = [
        {"id": "gid://shopify/MediaImage/new"}
    ]

    count = process_product_batch(
        shopify_client=client,
        remover=remover,
        product_id="gid://shopify/Product/1",
        unprocessed_images=[
            {
                "media_id": "gid://shopify/MediaImage/orig",
                "url": "https://cdn/orig.jpg",
                "alt_text": "Air Jordan 4",
                "position": 0,
            }
        ],
    )

    assert count == 1
    create_items = client.create_product_media_batch.call_args.kwargs["media_items"]
    assert create_items[0]["alt"] == "Air Jordan 4"
    client.update_product_media_batch.assert_not_called()
    client.delete_product_media.assert_not_called()
    metafields = client.set_media_bg_state.call_args.args[0]
    assert bg_state_metafield("gid://shopify/MediaImage/new", BG_STATE_RESULT) in metafields
    assert bg_source_metafield("gid://shopify/MediaImage/new", "gid://shopify/MediaImage/orig") in metafields
    assert bg_state_metafield("gid://shopify/MediaImage/orig", BG_STATE_SOURCE) in metafields
    remover.remove_background.assert_called_once()
    assert remover.remove_background.call_args.kwargs.get("bg_color") is None


def test_process_product_batch_passes_bg_color_and_keeps_original():
    client = MagicMock()
    client.download_image_bytes.return_value = b"orig"
    remover = MagicMock()
    remover.remove_background.return_value = b"out"
    client.create_staged_upload.return_value = {"url": "https://upload", "resourceUrl": "https://cdn/staged"}
    client.upload_file_to_staged_target.return_value = "https://cdn/staged"
    client.create_product_media_batch.return_value = [
        {"id": "gid://shopify/MediaImage/new"}
    ]

    process_product_batch(
        shopify_client=client,
        remover=remover,
        product_id="gid://shopify/Product/1",
        unprocessed_images=[
            {
                "media_id": "gid://shopify/MediaImage/orig",
                "url": "https://cdn/orig.jpg",
                "alt_text": "",
                "position": 0,
            }
        ],
        bg_color="#FFFFFF",
    )

    client.delete_product_media.assert_not_called()
    metafields = client.set_media_bg_state.call_args.args[0]
    assert bg_state_metafield("gid://shopify/MediaImage/new", BG_STATE_RESULT) in metafields
    assert bg_source_metafield("gid://shopify/MediaImage/new", "gid://shopify/MediaImage/orig") in metafields
    assert bg_state_metafield("gid://shopify/MediaImage/orig", BG_STATE_SOURCE) in metafields
    assert remover.remove_background.call_args.kwargs["bg_color"] == "#FFFFFF"
