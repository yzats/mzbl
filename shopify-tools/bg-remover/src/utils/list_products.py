import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import config
from src.shopify import ShopifyGraphQLClient

def list_products():
    client = ShopifyGraphQLClient(
        store_url=config.SHOPIFY_STORE_URL,
        access_token=config.SHOPIFY_ADMIN_API_ACCESS_TOKEN,
        api_version=config.SHOPIFY_API_VERSION,
    )
    query = """
    query {
      products(first: 5) {
        nodes {
          id
          title
          handle
          media(first: 5) {
            nodes {
              id
              mediaContentType
            }
          }
        }
      }
    }
    """
    data = client._execute_query(query)
    products = data.get("products", {}).get("nodes", [])
    print(f"Found {len(products)} products on {config.SHOPIFY_STORE_URL}:")
    for p in products:
        media_count = len(p.get("media", {}).get("nodes", []))
        print(f" - ID: {p['id']} | Title: '{p['title']}' | Handle: {p['handle']} | Media count: {media_count}")

if __name__ == "__main__":
    list_products()
