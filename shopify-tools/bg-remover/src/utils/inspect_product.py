import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import config
from src.shopify import ShopifyGraphQLClient

def inspect_product_media(product_id: str):
    client = ShopifyGraphQLClient(
        store_url=config.SHOPIFY_STORE_URL,
        access_token=config.SHOPIFY_ADMIN_API_ACCESS_TOKEN,
        api_version=config.SHOPIFY_API_VERSION,
    )
    if not product_id.startswith("gid://shopify/Product/"):
        gql_id = f"gid://shopify/Product/{product_id}"
    else:
        gql_id = product_id

    query = """
    query inspectProduct($id: ID!) {
      product(id: $id) {
        id
        title
        media(first: 10) {
          nodes {
            id
            mediaContentType
            alt
            ... on MediaImage {
              image {
                id
                altText
                url
              }
            }
          }
        }
      }
    }
    """
    data = client._execute_query(query, {"id": gql_id})
    product = data.get("product")
    if not product:
        print(f"Product not found: {product_id}")
        return

    print(f"Product Title: {product['title']}")
    media_nodes = product.get("media", {}).get("nodes", [])
    print(f"Total media count: {len(media_nodes)}")
    for idx, node in enumerate(media_nodes):
        node_alt = node.get("alt")
        img_alt = node.get("image", {}).get("altText") if node.get("image") else None
        print(f" [{idx}] Media ID: {node['id']} | Type: {node['mediaContentType']} | Media Alt: '{node_alt}' | Image Alt: '{img_alt}'")

if __name__ == "__main__":
    inspect_product_media("8287376212025")
