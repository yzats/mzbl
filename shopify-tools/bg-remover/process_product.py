import argparse
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

try:
    import config
    SHOPIFY_STORE_URL = getattr(config, "SHOPIFY_STORE_URL", "")
    SHOPIFY_ADMIN_API_ACCESS_TOKEN = getattr(config, "SHOPIFY_ADMIN_API_ACCESS_TOKEN", "")
    SHOPIFY_API_VERSION = getattr(config, "SHOPIFY_API_VERSION", "2024-04")
    REMBG_API_URL = getattr(config, "REMBG_API_URL", "https://api.rembg.com/rmbg")
    REMBG_API_KEY = getattr(config, "REMBG_API_KEY", "")
    DEFAULT_BG_COLOR = getattr(config, "DEFAULT_BG_COLOR", "#ffffff")
    DELETE_ORIGINAL = getattr(config, "DELETE_ORIGINAL", False)
except ImportError:
    SHOPIFY_STORE_URL = ""
    SHOPIFY_ADMIN_API_ACCESS_TOKEN = ""
    SHOPIFY_API_VERSION = "2024-04"
    REMBG_API_URL = "https://api.rembg.com/rmbg"
    REMBG_API_KEY = ""
    DEFAULT_BG_COLOR = "#ffffff"
    DELETE_ORIGINAL = False

from src.shopify import (
    ShopifyGraphQLClient,
    ShopifyAPIError,
    append_alt_tag,
)
from src.removers import (
    RembgHostedRemover,
    BackgroundRemoverError,
    RetryableBackgroundRemoverError,
    RembgUnavailableError,
)
from src.utils import applog


def process_product_batch(
    shopify_client: ShopifyGraphQLClient,
    remover: RembgHostedRemover,
    product_id: str,
    unprocessed_images: list,
    bg_color: str,
    delete_original: bool = False,
) -> int:
    """Process all unprocessed images for a product in a batched pipeline.

    1. Removes backgrounds & uploads staged files for all images.
    2. Batches creation of new media (`productCreateMedia`).
    3. Batches reordering of new media (`productReorderMedia`).
    4. Batches updating original media alt text (`productUpdateMedia`) or deletion (`productDeleteMedia`).
    """
    if not unprocessed_images:
        return 0

    # Step 1: Process images and perform staged uploads
    prepared_items = []
    failed_images = []

    for img_info in unprocessed_images:
        media_id = img_info["media_id"]
        original_url = img_info["url"]
        pos = str(img_info.get("position", 0))
        clean_id = media_id.split("/")[-1]
        upload_filename = f"{clean_id}-bg-removed.png"

        try:
            orig_bytes = shopify_client.download_image_bytes(original_url)
            processed_bytes = remover.remove_background(orig_bytes, bg_color=bg_color)

            staged_target = shopify_client.create_staged_upload(filename=upload_filename)
            resource_url = shopify_client.upload_file_to_staged_target(
                staged_target=staged_target,
                file_bytes=processed_bytes,
                filename=upload_filename,
            )

            prepared_items.append({
                "original_media_id": media_id,
                "original_alt": img_info.get("alt_text") or "",
                "target_position": pos,
                "resource_url": resource_url,
            })
        except (RetryableBackgroundRemoverError, RembgUnavailableError):
            raise
        except Exception as e:
            applog.warning(f"Skipping media {media_id}: {e}")
            failed_images.append((img_info, e))

    if not prepared_items:
        if failed_images:
            raise failed_images[0][1]
        return 0

    # Step 2: Batched productCreateMedia
    create_payload = [
        {"originalSource": item["resource_url"], "alt": "bg-removed"}
        for item in prepared_items
    ]
    created_media_list = shopify_client.create_product_media_batch(
        product_id=product_id,
        media_items=create_payload,
    )

    # Step 3: Batched productReorderMedia & update/delete originals
    moves = []
    original_updates = []
    original_deletes = []

    for item, created_media in zip(prepared_items, created_media_list):
        new_media_id = created_media.get("id")
        if new_media_id:
            moves.append({
                "id": new_media_id,
                "newPosition": item["target_position"],
            })

        orig_id = item["original_media_id"]
        if orig_id:
            if delete_original:
                original_deletes.append(orig_id)
            else:
                updated_alt = append_alt_tag(item["original_alt"], "hide")
                original_updates.append({
                    "id": orig_id,
                    "alt": updated_alt,
                })

    if moves:
        shopify_client.reorder_product_media(product_id=product_id, moves=moves)

    if original_deletes:
        shopify_client.delete_product_media(product_id=product_id, media_ids=original_deletes)
    elif original_updates:
        shopify_client.update_product_media_batch(product_id=product_id, updates=original_updates)

    return len(prepared_items)


def process_image(
    shopify_client: ShopifyGraphQLClient,
    remover: RembgHostedRemover,
    product_id: str,
    image_info: dict,
    bg_color: str,
    delete_original: bool = False,
) -> None:
    """Process a single image using process_product_batch."""
    process_product_batch(
        shopify_client=shopify_client,
        remover=remover,
        product_id=product_id,
        unprocessed_images=[image_info],
        bg_color=bg_color,
        delete_original=delete_original,
    )


def main():
    parser = argparse.ArgumentParser(
        description="Fetch image(s) of a Shopify product, remove background via rembg, and upload modified image back to Shopify."
    )
    parser.add_argument(
        "--product-id",
        "-p",
        required=True,
        help="Shopify Product ID (e.g. 12345678 or 'gid://shopify/Product/12345678')",
    )
    parser.add_argument(
        "--sequence",
        "-s",
        type=int,
        default=None,
        help="Target a specific image sequence number (1-based index). If provided, only this specific image will be processed. Defaults to processing ALL unprocessed images.",
    )

    args = parser.parse_args()

    if not SHOPIFY_STORE_URL or SHOPIFY_STORE_URL == "your-shop.myshopify.com":
        print("Error: Missing valid SHOPIFY_STORE_URL in config.py", file=sys.stderr)
        sys.exit(1)

    if not SHOPIFY_ADMIN_API_ACCESS_TOKEN or SHOPIFY_ADMIN_API_ACCESS_TOKEN.startswith("shpat_xxxx"):
        print("Error: Missing valid SHOPIFY_ADMIN_API_ACCESS_TOKEN in config.py", file=sys.stderr)
        sys.exit(1)

    shopify_client = ShopifyGraphQLClient(
        store_url=SHOPIFY_STORE_URL,
        access_token=SHOPIFY_ADMIN_API_ACCESS_TOKEN,
        api_version=SHOPIFY_API_VERSION,
    )
    remover = RembgHostedRemover(api_key=REMBG_API_KEY, api_url=REMBG_API_URL)

    try:
        if args.sequence is not None:
            print(f"Fetching image at sequence #{args.sequence} for Product ID: {args.product_id}...")
            unprocessed_images = shopify_client.get_unprocessed_images(
                args.product_id, sequence=args.sequence
            )
        else:
            print(f"Fetching ALL unprocessed images for Product ID: {args.product_id}...")
            unprocessed_images = shopify_client.get_unprocessed_images(args.product_id)

        if not unprocessed_images:
            print(f"Product ID {args.product_id} has no unprocessed images to process. Skipping.")
            sys.exit(0)

        print(f"Found {len(unprocessed_images)} image(s) to process.")

        # Batch process all unprocessed images for the product in a single batched run
        process_product_batch(
            shopify_client=shopify_client,
            remover=remover,
            product_id=args.product_id,
            unprocessed_images=unprocessed_images,
            bg_color=DEFAULT_BG_COLOR,
            delete_original=DELETE_ORIGINAL,
        )

        print(f"\n✨ Done! Processed {len(unprocessed_images)} image(s) on product {args.product_id}.")

    except (ShopifyAPIError, BackgroundRemoverError) as e:
        print(f"Error during execution: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
