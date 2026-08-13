import argparse
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

try:
    import config
    SHOPIFY_STORE_URL = getattr(config, "SHOPIFY_STORE_URL", "")
    SHOPIFY_ADMIN_API_ACCESS_TOKEN = getattr(config, "SHOPIFY_ADMIN_API_ACCESS_TOKEN", "")
    SHOPIFY_API_VERSION = getattr(config, "SHOPIFY_API_VERSION", "2024-04")
except ImportError:
    SHOPIFY_STORE_URL = ""
    SHOPIFY_ADMIN_API_ACCESS_TOKEN = ""
    SHOPIFY_API_VERSION = "2024-04"

from src.shopify import ShopifyGraphQLClient, ShopifyAPIError


def main():
    parser = argparse.ArgumentParser(
        description="CLI tool to fetch and download the first image of a Shopify product."
    )
    parser.add_argument(
        "--product-id",
        "-p",
        required=True,
        help="Shopify Product ID (e.g. 12345678 or 'gid://shopify/Product/12345678')",
    )
    parser.add_argument(
        "--output",
        "-o",
        required=True,
        help="Path where the downloaded image should be saved (e.g. original_image.jpg)",
    )
    parser.add_argument(
        "--store-url",
        default=SHOPIFY_STORE_URL,
        help="Shopify store domain (default from config.py)",
    )
    parser.add_argument(
        "--access-token",
        default=SHOPIFY_ADMIN_API_ACCESS_TOKEN,
        help="Shopify Admin API access token (default from config.py)",
    )

    args = parser.parse_args()

    if not args.store_url or args.store_url == "your-shop.myshopify.com":
        print("Error: Missing valid --store-url or SHOPIFY_STORE_URL in config.py", file=sys.stderr)
        sys.exit(1)

    if not args.access_token or args.access_token.startswith("shpat_xxxx"):
        print("Error: Missing valid --access-token or SHOPIFY_ADMIN_API_ACCESS_TOKEN in config.py", file=sys.stderr)
        sys.exit(1)

    client = ShopifyGraphQLClient(
        store_url=args.store_url,
        access_token=args.access_token,
        api_version=SHOPIFY_API_VERSION,
    )

    try:
        print(f"Fetching first image details for Product ID: {args.product_id} from {args.store_url}...")
        images = client.get_unprocessed_images(args.product_id, limit=1)

        if not images:
            print(f"No image found for Product ID: {args.product_id}")
            sys.exit(0)

        image_info = images[0]

        print(f"Product: {image_info.get('product_title')} (ID: {image_info.get('product_id')})")
        print(f"Image ID: {image_info.get('image_id')}")
        print(f"CDN URL: {image_info.get('url')}")
        print(f"Dimensions: {image_info.get('width')}x{image_info.get('height')}")

        image_url = image_info["url"]
        print(f"Downloading image from CDN...")
        image_bytes = client.download_image_bytes(image_url)

        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(image_bytes)

        print(f"Success! Downloaded image ({len(image_bytes)} bytes) and saved to {output_path}")

    except ShopifyAPIError as e:
        print(f"Shopify API Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
