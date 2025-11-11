import requests
import time
import csv
from collections import defaultdict
import argparse
import os

# Squarespace API base URL
API_BASE = "https://api.squarespace.com/1.0/commerce/"

# Rate limit delay: 300 requests per minute ~ 0.2 sec per request, use 0.3 for safety
RATE_LIMIT_DELAY = 0.3

def fetch_all_products(api_key):
    """
    Fetch all products from Squarespace, handling pagination.
    """
    products = []
    url = API_BASE + "products"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "User-Agent": "DuplicateImageRemover/1.0"
    }
    cursor = None
    while True:
        params = {"cursor": cursor} if cursor else {}
        try:
            response = requests.get(url, headers=headers, params=params)
            response.raise_for_status()
            data = response.json()
            products.extend(data.get("products", []))
            pagination = data.get("pagination", {})
            cursor = pagination.get("nextPageCursor")
            if not cursor:
                break
            time.sleep(RATE_LIMIT_DELAY)
        except requests.RequestException as e:
            print(f"Error fetching products: {e}")
            break
    return products

def build_sku_to_product_map(products):
    """
    Create a mapping from SKU to product ID and images.
    """
    sku_to_product = {}
    for product in products:
        for variant in product.get("variants", []):
            sku = variant.get("sku")
            if sku:
                # Assume SKUs are unique across products
                sku_to_product[sku] = {
                    "product_id": product["id"],
                    "images": product.get("images", [])
                }
    return sku_to_product

def delete_duplicate_images(api_key, product_id, images):
    """
    Delete duplicate images based on filename.
    Keep the first occurrence, delete the rest.
    """
    headers = {
        "Authorization": f"Bearer {api_key}",
        "User-Agent": "DuplicateImageRemover/1.0"
    }
    # Group images by lowercase filename (case-insensitive)
    filename_to_images = defaultdict(list)
    for image in images:
        filename = image.get("filename", "").lower()
        if filename:  # Skip if no filename
            filename_to_images[filename].append(image)
    
    deleted_count = 0
    for filename, img_list in filename_to_images.items():
        if len(img_list) > 1:
            # Keep the first, delete the rest
            for img in img_list[1:]:
                image_id = img["id"]
                delete_url = f"{API_BASE}products/{product_id}/images/{image_id}"
                try:
                    response = requests.delete(delete_url, headers=headers)
                    response.raise_for_status()
                    print(f"Deleted duplicate image {image_id} for filename '{filename}'")
                    deleted_count += 1
                    time.sleep(RATE_LIMIT_DELAY)
                except requests.RequestException as e:
                    print(f"Error deleting image {image_id}: {e}")
    return deleted_count

def main():
    parser = argparse.ArgumentParser(description="Delete duplicate images from Squarespace products based on SKUs in a CSV.")
    parser.add_argument("csv_file", help="Path to the CSV file containing SKUs (one per row).")
    args = parser.parse_args()

    # Get API key from environment variable for security
    api_key = os.environ.get("SQUARESPACE_API_KEY")
    if not api_key:
        raise ValueError("SQUARESPACE_API_KEY environment variable not set.")

    # Fetch all products
    print("Fetching all products...")
    products = fetch_all_products(api_key)
    print(f"Fetched {len(products)} products.")

    # Build SKU map
    sku_to_product = build_sku_to_product_map(products)

    # Read SKUs from CSV
    skus = []
    with open(args.csv_file, "r") as f:
        reader = csv.reader(f)
        skus = [row[0].strip() for row in reader if row and row[0].strip()]

    print(f"Processing {len(skus)} SKUs...")

    total_deleted = 0
    for sku in skus:
        if sku in sku_to_product:
            print(f"Processing SKU: {sku}")
            product_info = sku_to_product[sku]
            deleted = delete_duplicate_images(api_key, product_info["product_id"], product_info["images"])
            total_deleted += deleted
        else:
            print(f"SKU {sku} not found.")
    
    print(f"Total duplicate images deleted: {total_deleted}")

if __name__ == "__main__":
    main()