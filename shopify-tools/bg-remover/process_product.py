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
from src.removers import RembgHostedRemover, BackgroundRemoverError


def process_image(
    shopify_client: ShopifyGraphQLClient,
    remover: RembgHostedRemover,
    product_id: str,
    image_info: dict,
    bg_color: str,
    delete_original: bool = False,
) -> None:
    """Process a single image for a product: remove background, upload, reorder, and tag/delete original."""
    original_media_id = image_info["media_id"]
    original_url = image_info["url"]
    target_position = str(image_info.get("position", 0))
    orig_height = image_info.get("height")
    product_title = image_info.get("product_title", "Product")
    clean_orig_id = original_media_id.split("/")[-1]
    upload_filename = f"{clean_orig_id}-bg-removed.png"

    print(f"\n--- Processing image ID: {original_media_id} at position {target_position} (height: {orig_height}px) ---")
    print(f"    Product: '{product_title}'")

    # Step 1: Download image bytes from Shopify CDN
    print("    1. Downloading image bytes from Shopify CDN...")
    original_bytes = shopify_client.download_image_bytes(original_url)
    print(f"       Downloaded {len(original_bytes)} bytes.")

    # Step 2: Remove background via rembg API (passing height parameter 'h' to preserve original height)
    print(f"    2. Removing background via rembg API (bg_color={bg_color}, h={orig_height})...")
    processed_bytes = remover.remove_background(
        original_bytes, bg_color=bg_color, height=orig_height
    )
    print(f"       Processed image: {len(processed_bytes)} bytes.")

    # Step 3: Staged upload to Shopify
    print(f"    3. Creating staged upload target on Shopify (filename: {upload_filename})...")
    staged_target = shopify_client.create_staged_upload(filename=upload_filename)

    print("    4. Uploading modified image to Shopify staged storage...")
    resource_url = shopify_client.upload_file_to_staged_target(
        staged_target=staged_target,
        file_bytes=processed_bytes,
        filename=upload_filename,
    )
    print(f"       Staged Resource URL: {resource_url}")

    # Step 4: Attach new media to Product with alt_text = "bg-removed"
    print("    5. Attaching new media to Shopify product...")
    new_image_alt = "bg-removed"

    new_media = shopify_client.create_product_media(
        product_id=product_id,
        original_source_url=resource_url,
        alt_text=new_image_alt,
    )
    new_media_id = new_media.get("id")
    print(f"       Successfully created new media ID: {new_media_id} (alt='{new_image_alt}')")

    # Explicitly update alt text to guarantee it is saved on Shopify
    if new_media_id:
        shopify_client.update_product_media(
            product_id=product_id,
            media_id=new_media_id,
            alt_text=new_image_alt,
        )

    # Step 5: Explicitly set new media to original image's position
    if new_media_id:
        print(f"    6. Moving new background-removed image to position {target_position}...")
        shopify_client.reorder_product_media(
            product_id=product_id,
            moves=[{"id": new_media_id, "newPosition": target_position}],
        )

    # Step 6: Update original media alt text by appending 'hide' in comma-separated tag format
    if original_media_id:
        if delete_original:
            print(f"    7. Deleting original media ID: {original_media_id}...")
            deleted_ids = shopify_client.delete_product_media(
                product_id=product_id, media_ids=[original_media_id]
            )
            print(f"       Deleted media IDs: {deleted_ids}")
        else:
            original_alt = image_info.get("alt_text") or ""
            updated_alt = append_alt_tag(original_alt, "hide")
            print(f"    7. Updating original media ID {original_media_id} alt text to '{updated_alt}'...")
            shopify_client.update_product_media(
                product_id=product_id,
                media_id=original_media_id,
                alt_text=updated_alt,
            )
            print(f"       Original image preserved with alt='{updated_alt}'.")


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

        for image_info in unprocessed_images:
            process_image(
                shopify_client=shopify_client,
                remover=remover,
                product_id=args.product_id,
                image_info=image_info,
                bg_color=DEFAULT_BG_COLOR,
                delete_original=DELETE_ORIGINAL,
            )

        print(f"\n✨ Done! Processed {len(unprocessed_images)} image(s) on product {args.product_id}.")

    except (ShopifyAPIError, BackgroundRemoverError) as e:
        print(f"Error during execution: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
