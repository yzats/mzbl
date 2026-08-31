from typing import Optional, Dict, Any, List

import requests

from .metafields import (
    is_processed_bg_state,
    product_has_bg_skip,
)
from ..removers.base import RetryableBackgroundRemoverError, NonRetryableBackgroundRemoverError
from ..utils import applog
from ..utils.retry import retry_with_exponential_backoff


def image_mime_type(filename: str) -> str:
    """MIME type for a Shopify staged image upload from the filename suffix."""
    lower = (filename or "").lower()
    if lower.endswith(".png"):
        return "image/png"
    if lower.endswith(".jpg") or lower.endswith(".jpeg"):
        return "image/jpeg"
    return "image/webp"


class ShopifyAPIError(Exception):
    """Base exception for Shopify API errors."""
    pass


class RetryableShopifyError(ShopifyAPIError):
    """Retryable error for Shopify API (e.g. HTTP 429 rate limit, 5xx server errors)."""
    pass


class NonRetryableShopifyError(ShopifyAPIError):
    """Non-retryable error for Shopify API (e.g. bad credentials, invalid product ID)."""
    pass


class ShopifyGraphQLClient:
    """Shopify Admin GraphQL API client for fetching product media and performing staged uploads."""

    def __init__(
        self,
        store_url: str,
        access_token: str,
        api_version: str = "2026-10",
        timeout: int = 30,
        max_retries: int = 3,
        backoff_delay: float = 1.0,
    ):
        """Initialize Shopify GraphQL client.

        Args:
            store_url: Store domain (e.g. "my-store.myshopify.com" or "https://my-store.myshopify.com").
            access_token: Admin API access token ("shpat_...").
            api_version: Shopify API version (default: "2026-10").
            timeout: Request timeout in seconds.
            max_retries: Retry attempts for transient errors.
            backoff_delay: Initial retry backoff delay in seconds.
        """
        clean_url = store_url.replace("https://", "").replace("http://", "").strip("/")
        self.endpoint_url = f"https://{clean_url}/admin/api/{api_version}/graphql.json"
        self.access_token = access_token
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_delay = backoff_delay

    @retry_with_exponential_backoff(
        retries=3,
        backoff_in_seconds=1.0,
        retryable_exceptions=(RetryableShopifyError,),
    )
    def _execute_query(
        self, query: str, variables: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Execute a GraphQL query/mutation against Shopify Admin API.

        Args:
            query: GraphQL query string.
            variables: Optional variables dict.

        Returns:
            Dict[str, Any]: Parsed JSON response 'data' dictionary.

        Raises:
            RetryableShopifyError: On HTTP 429 rate limit or 5xx server errors.
            NonRetryableShopifyError: On 40x client errors or GraphQL user errors.
        """
        headers = {
            "Content-Type": "application/json",
            "X-Shopify-Access-Token": self.access_token,
        }
        payload = {"query": query, "variables": variables or {}}

        try:
            response = requests.post(
                self.endpoint_url,
                json=payload,
                headers=headers,
                timeout=self.timeout,
            )
        except (requests.Timeout, requests.ConnectionError) as e:
            raise RetryableShopifyError(f"Network timeout connecting to Shopify API: {e}") from e
        except requests.RequestException as e:
            raise NonRetryableShopifyError(f"Fatal HTTP error connecting to Shopify API: {e}") from e

        if response.status_code == 200:
            res_json = response.json()
            if "errors" in res_json and res_json["errors"]:
                err_msg = "; ".join(e.get("message", str(e)) for e in res_json["errors"])
                raise NonRetryableShopifyError(f"Shopify GraphQL error: {err_msg}")
            return res_json.get("data", {})
        elif response.status_code in (429, 500, 502, 503, 504):
            raise RetryableShopifyError(
                f"Shopify transient HTTP {response.status_code}: {response.text}"
            )
        else:
            raise NonRetryableShopifyError(
                f"Shopify HTTP {response.status_code}: {response.text}"
            )

    def get_unprocessed_images(
        self,
        product_id: str,
        limit: Optional[int] = None,
        sequence: Optional[int] = None,
        images_scope: str = "all",
    ) -> List[Dict[str, Any]]:
        """Fetch IMAGE media whose `$app.bg_state` is empty.

        Skips the whole product when it is tagged `bg_skip`. Skips media with
        `$app.bg_state` ``source`` or ``result``. Does not inspect alt text.

        Args:
            product_id: Shopify product ID.
            limit: Optional maximum number of images to return.
            sequence: Optional 1-based sequence index of the specific image to target.
            images_scope: ``all`` or ``featured`` (first IMAGE only).

        Returns:
            List[Dict[str, Any]]: List of image detail dicts.
        """
        if not product_id.startswith("gid://shopify/Product/"):
            gql_product_id = f"gid://shopify/Product/{product_id}"
        else:
            gql_product_id = product_id

        query = """
        query getProductMedia($id: ID!) {
          product(id: $id) {
            id
            title
            tags
            media(first: 50) {
              nodes {
                id
                mediaContentType
                status
                alt
                ... on MediaImage {
                  bgState: metafield(key: "bg_state") {
                    value
                  }
                  image {
                    id
                    url
                    altText
                    width
                  }
                }
              }
            }
          }
        }
        """

        data = self._execute_query(query, {"id": gql_product_id})
        product = data.get("product")
        if not product:
            raise NonRetryableShopifyError(f"Product not found for ID: {gql_product_id}")

        if product_has_bg_skip(product.get("tags")):
            applog.info(f"Product {gql_product_id} tagged bg_skip; skipping.")
            return []

        media_nodes = product.get("media", {}).get("nodes", [])
        if not media_nodes:
            return []

        image_nodes = [m for m in media_nodes if m.get("mediaContentType") == "IMAGE"]
        if images_scope == "featured" and sequence is None:
            image_nodes = image_nodes[:1]

        def _image_dict(node: Dict[str, Any], position: int, seq: Optional[int] = None) -> Dict[str, Any]:
            image_info = node.get("image") or {}
            raw_alt = node.get("alt") or image_info.get("altText") or ""
            bg_meta = node.get("bgState") or {}
            bg_state = (bg_meta.get("value") if isinstance(bg_meta, dict) else None) or ""
            info = {
                "media_id": node.get("id"),
                "image_id": image_info.get("id"),
                "url": image_info.get("url"),
                "alt_text": raw_alt,
                "position": position,
                "width": image_info.get("width"),
                "product_id": product.get("id"),
                "product_title": product.get("title"),
                "bg_state": bg_state,
            }
            if seq is not None:
                info["sequence"] = seq
            return info

        if sequence is not None:
            seq_idx = sequence - 1
            all_images = [m for m in media_nodes if m.get("mediaContentType") == "IMAGE"]
            if seq_idx < 0 or seq_idx >= len(all_images):
                raise NonRetryableShopifyError(
                    f"Invalid sequence number {sequence}. Product has {len(all_images)} image(s)."
                )
            target_node = all_images[seq_idx]
            media_pos = media_nodes.index(target_node)
            bg_meta = target_node.get("bgState") or {}
            bg_state = (bg_meta.get("value") if isinstance(bg_meta, dict) else None) or ""
            if is_processed_bg_state(bg_state):
                applog.debug(
                    f"Image at sequence {sequence} already has $app.bg_state={bg_state!r}."
                )
                return []
            return [_image_dict(target_node, media_pos, sequence)]

        unprocessed = []
        for idx, media in enumerate(media_nodes):
            if media.get("mediaContentType") != "IMAGE":
                continue
            if images_scope == "featured" and media not in image_nodes:
                continue

            bg_meta = media.get("bgState") or {}
            bg_state = (bg_meta.get("value") if isinstance(bg_meta, dict) else None) or ""
            if is_processed_bg_state(bg_state):
                continue

            unprocessed.append(_image_dict(media, idx))

            if limit is not None and len(unprocessed) >= limit:
                break

        return unprocessed

    def download_image_bytes(self, image_url: str) -> bytes:
        """Download raw image bytes from Shopify CDN URL with retries.

        Args:
            image_url: Full HTTP/HTTPS URL of the image.

        Returns:
            bytes: Raw image file bytes.
        """
        if not image_url:
            raise NonRetryableShopifyError("Image URL cannot be empty.")

        @retry_with_exponential_backoff(
            retries=self.max_retries,
            backoff_in_seconds=self.backoff_delay,
            retryable_exceptions=(RetryableShopifyError,),
        )
        def _fetch() -> bytes:
            try:
                resp = requests.get(image_url, timeout=self.timeout)
            except (requests.Timeout, requests.ConnectionError) as e:
                raise RetryableShopifyError(f"Timeout downloading image from CDN: {e}") from e
            except requests.RequestException as e:
                raise NonRetryableShopifyError(f"Error downloading image from CDN: {e}") from e

            if resp.status_code == 200:
                return resp.content
            elif resp.status_code in (429, 500, 502, 503, 504):
                raise RetryableShopifyError(f"CDN transient error HTTP {resp.status_code}")
            else:
                raise NonRetryableShopifyError(f"CDN error HTTP {resp.status_code}: {resp.text}")

        return _fetch()

    def create_staged_upload(
        self, filename: str, mime_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create a staged upload target URL for uploading new image bytes to Shopify.

        Args:
            filename: Name of the file (e.g. "product-bg-removed.webp").
            mime_type: MIME type of the file. Defaults from the filename suffix.
        """
        mime_type = mime_type or image_mime_type(filename)
        mutation = """
        mutation stagedUploadsCreate($input: [StagedUploadInput!]!) {
          stagedUploadsCreate(input: $input) {
            stagedTargets {
              url
              resourceUrl
              parameters {
                name
                value
              }
            }
            userErrors {
              field
              message
            }
          }
        }
        """
        variables = {
            "input": [
                {
                    "filename": filename,
                    "mimeType": mime_type,
                    "resource": "IMAGE",
                    "httpMethod": "POST",
                }
            ]
        }

        data = self._execute_query(mutation, variables)
        result = data.get("stagedUploadsCreate", {})
        user_errors = result.get("userErrors", [])
        if user_errors:
            err_msg = "; ".join(f"{e.get('field')}: {e.get('message')}" for e in user_errors)
            raise NonRetryableShopifyError(f"stagedUploadsCreate failed: {err_msg}")

        targets = result.get("stagedTargets", [])
        if not targets:
            raise NonRetryableShopifyError("stagedUploadsCreate returned no upload targets.")

        return targets[0]

    def upload_file_to_staged_target(
        self, staged_target: Dict[str, Any], file_bytes: bytes, filename: str = "image.webp"
    ) -> str:
        """Upload raw file bytes to Shopify's staged upload target URL (Google Cloud Storage / S3).

        Args:
            staged_target: Target dictionary returned from create_staged_upload().
            file_bytes: Raw binary file bytes to upload.
            filename: Filename for the multipart upload.

        Returns:
            str: The resourceUrl to be used in productCreateMedia.
        """
        upload_url = staged_target["url"]
        params = staged_target.get("parameters", [])

        # Build multipart/form-data payload with parameters in exact order provided by Shopify
        form_data = {}
        for p in params:
            form_data[p["name"]] = p["value"]

        files = {"file": (filename, file_bytes, image_mime_type(filename))}

        try:
            resp = requests.post(upload_url, data=form_data, files=files, timeout=self.timeout)
        except requests.RequestException as e:
            raise RetryableShopifyError(f"Failed to upload file to staged target URL: {e}") from e

        if resp.status_code not in (200, 201, 204):
            raise NonRetryableShopifyError(
                f"Staged target upload failed HTTP {resp.status_code}: {resp.text}"
            )

        return staged_target["resourceUrl"]

    def create_product_media(
        self, product_id: str, original_source_url: str, alt_text: str = ""
    ) -> Dict[str, Any]:
        """Attach a single newly uploaded image media to a product."""
        results = self.create_product_media_batch(
            product_id=product_id,
            media_items=[{"originalSource": original_source_url, "alt": alt_text}],
        )
        return results[0] if results else {}

    def create_product_media_batch(
        self, product_id: str, media_items: List[Dict[str, str]]
    ) -> List[Dict[str, Any]]:
        """Attach multiple newly uploaded image media items to a product in a single batched GraphQL call.

        Args:
            product_id: Shopify product ID (e.g. "gid://shopify/Product/12345").
            media_items: List of dicts, e.g. [{"originalSource": "...", "alt": original_alt}]

        Returns:
            List[Dict[str, Any]]: List of created media objects.
        """
        if not media_items:
            return []

        if not product_id.startswith("gid://shopify/Product/"):
            gql_product_id = f"gid://shopify/Product/{product_id}"
        else:
            gql_product_id = product_id

        mutation = """
        mutation productCreateMedia($media: [CreateMediaInput!]!, $productId: ID!) {
          productCreateMedia(media: $media, productId: $productId) {
            media {
              id
              mediaContentType
              status
            }
            mediaUserErrors {
              field
              message
            }
          }
        }
        """
        formatted_media = []
        for item in media_items:
            formatted_media.append({
                "originalSource": item["originalSource"],
                "mediaContentType": "IMAGE",
                "alt": item.get("alt", ""),
            })

        variables = {
            "productId": gql_product_id,
            "media": formatted_media,
        }

        data = self._execute_query(mutation, variables)
        result = data.get("productCreateMedia", {})
        errors = result.get("mediaUserErrors", [])
        if errors:
            err_msg = "; ".join(f"{e.get('field')}: {e.get('message')}" for e in errors)
            raise NonRetryableShopifyError(f"productCreateMedia failed: {err_msg}")

        return result.get("media", [])

    def delete_product_media(self, product_id: str, media_ids: List[str]) -> List[str]:
        """Delete old media objects from a product.

        Args:
            product_id: Shopify product ID.
            media_ids: List of Media IDs to delete.

        Returns:
            List[str]: List of deleted media IDs.
        """
        if not product_id.startswith("gid://shopify/Product/"):
            gql_product_id = f"gid://shopify/Product/{product_id}"
        else:
            gql_product_id = product_id

        mutation = """
        mutation productDeleteMedia($mediaIds: [ID!]!, $productId: ID!) {
          productDeleteMedia(mediaIds: $mediaIds, productId: $productId) {
            deletedMediaIds
            deletedProductImageIds
            mediaUserErrors {
              field
              message
            }
          }
        }
        """
        variables = {
            "productId": gql_product_id,
            "mediaIds": media_ids,
        }

        data = self._execute_query(mutation, variables)
        result = data.get("productDeleteMedia", {})
        errors = result.get("mediaUserErrors", [])
        if errors:
            err_msg = "; ".join(f"{e.get('field')}: {e.get('message')}" for e in errors)
            raise NonRetryableShopifyError(f"productDeleteMedia failed: {err_msg}")

        return result.get("deletedMediaIds", [])

    def update_product_media(
        self, product_id: str, media_id: str, alt_text: str
    ) -> Dict[str, Any]:
        """Update media details for a single item on a product."""
        results = self.update_product_media_batch(
            product_id=product_id,
            updates=[{"id": media_id, "alt": alt_text}],
        )
        return results[0] if results else {}

    def update_product_media_batch(
        self, product_id: str, updates: List[Dict[str, str]]
    ) -> List[Dict[str, Any]]:
        """Update media details (such as alt text) for multiple items on a product in a single batched GraphQL call.

        Args:
            product_id: Shopify product ID.
            updates: List of dicts, e.g. [{"id": "gid://shopify/MediaImage/123", "alt": "hide"}]

        Returns:
            List[Dict[str, Any]]: List of updated media objects.
        """
        if not updates:
            return []

        if not product_id.startswith("gid://shopify/Product/"):
            gql_product_id = f"gid://shopify/Product/{product_id}"
        else:
            gql_product_id = product_id

        mutation = """
        mutation productUpdateMedia($media: [UpdateMediaInput!]!, $productId: ID!) {
          productUpdateMedia(media: $media, productId: $productId) {
            media {
              id
              alt
            }
            mediaUserErrors {
              field
              message
            }
          }
        }
        """
        variables = {
            "productId": gql_product_id,
            "media": updates,
        }

        data = self._execute_query(mutation, variables)
        result = data.get("productUpdateMedia", {})
        errors = result.get("mediaUserErrors", [])
        if errors:
            err_msg = "; ".join(f"{e.get('field')}: {e.get('message')}" for e in errors)
            raise NonRetryableShopifyError(f"productUpdateMedia failed: {err_msg}")

        return result.get("media", [])

    def reorder_product_media(
        self, product_id: str, moves: List[Dict[str, Any]]
    ) -> bool:
        """Reorder media items on a product.

        Args:
            product_id: Shopify product ID.
            moves: List of move input dicts, e.g. [{"id": "gid://shopify/MediaImage/123", "newPosition": "0"}]

        Returns:
            bool: True if reorder succeeded.
        """
        if not product_id.startswith("gid://shopify/Product/"):
            gql_product_id = f"gid://shopify/Product/{product_id}"
        else:
            gql_product_id = product_id

        mutation = """
        mutation productReorderMedia($id: ID!, $moves: [MoveInput!]!) {
          productReorderMedia(id: $id, moves: $moves) {
            job {
              id
              done
            }
            userErrors {
              field
              message
            }
          }
        }
        """
        variables = {
            "id": gql_product_id,
            "moves": moves,
        }

        data = self._execute_query(mutation, variables)
        result = data.get("productReorderMedia", {})
        errors = result.get("userErrors", [])
        if errors:
            err_msg = "; ".join(f"{e.get('field')}: {e.get('message')}" for e in errors)
            raise NonRetryableShopifyError(f"productReorderMedia failed: {err_msg}")

        return True

    def set_media_bg_state(self, metafields: List[Dict[str, str]]) -> List[Dict[str, Any]]:
        """Write `$app.bg_state` on MediaImage nodes via one batched metafieldsSet.

        Args:
            metafields: List of metafieldsSet inputs (ownerId, key, type, value).
                Namespace is omitted so Shopify defaults to ``$app``.

        Returns:
            List of written metafield objects.
        """
        if not metafields:
            return []

        mutation = """
        mutation metafieldsSet($metafields: [MetafieldsSetInput!]!) {
          metafieldsSet(metafields: $metafields) {
            metafields {
              id
              key
              value
            }
            userErrors {
              field
              message
            }
          }
        }
        """
        data = self._execute_query(mutation, {"metafields": metafields})
        result = data.get("metafieldsSet", {})
        errors = result.get("userErrors", [])
        if errors:
            err_msg = "; ".join(f"{e.get('field')}: {e.get('message')}" for e in errors)
            raise NonRetryableShopifyError(f"metafieldsSet failed: {err_msg}")

        return result.get("metafields", []) or []
