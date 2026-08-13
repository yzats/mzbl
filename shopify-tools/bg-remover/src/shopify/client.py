import requests
from typing import Optional, Dict, Any, List
from ..removers.base import RetryableBackgroundRemoverError, NonRetryableBackgroundRemoverError
from ..utils.retry import retry_with_exponential_backoff


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
        api_version: str = "2024-04",
        timeout: int = 30,
        max_retries: int = 3,
        backoff_delay: float = 1.0,
    ):
        """Initialize Shopify GraphQL client.

        Args:
            store_url: Store domain (e.g. "my-store.myshopify.com" or "https://my-store.myshopify.com").
            access_token: Admin API access token ("shpat_...").
            api_version: Shopify API version (default: "2024-04").
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
    ) -> List[Dict[str, Any]]:
        """Fetch details of unprocessed images of a Shopify product.

        An image is considered already processed (and skipped) if:
          - alt text contains 'hide' or 'bg-removed'
          - image URL contains 'bg-removed'

        Args:
            product_id: Shopify product ID.
            limit: Optional maximum number of images to return.
            sequence: Optional 1-based sequence index of the specific image to target.

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
            media(first: 50) {
              nodes {
                id
                mediaContentType
                status
                alt
                ... on MediaImage {
                  image {
                    id
                    url
                    altText
                    width
                    height
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

        media_nodes = product.get("media", {}).get("nodes", [])
        if not media_nodes:
            return []

        # Filter only IMAGE media types
        image_nodes = [m for m in media_nodes if m.get("mediaContentType") == "IMAGE"]

        # If sequence is specified (1-based index), target that specific image node
        if sequence is not None:
            seq_idx = sequence - 1
            if seq_idx < 0 or seq_idx >= len(image_nodes):
                raise NonRetryableShopifyError(
                    f"Invalid sequence number {sequence}. Product has {len(image_nodes)} image(s)."
                )
            target_node = image_nodes[seq_idx]
            # Find its actual position in media_nodes list
            media_pos = media_nodes.index(target_node)
            image_info = target_node.get("image") or {}
            raw_alt = target_node.get("alt") or image_info.get("altText") or ""

            from .alt_helpers import has_alt_tag
            if has_alt_tag(raw_alt, "hide") or has_alt_tag(raw_alt, "bg-removed") or "bg-removed" in raw_alt.lower() or "bg-removed" in (image_info.get("url") or "").lower():
                print(f"Warning: Image at sequence {sequence} is already marked as processed/hidden.")

            return [{
                "media_id": target_node.get("id"),
                "image_id": image_info.get("id"),
                "url": image_info.get("url"),
                "alt_text": raw_alt,
                "position": media_pos,
                "sequence": sequence,
                "width": image_info.get("width"),
                "height": image_info.get("height"),
                "product_id": product.get("id"),
                "product_title": product.get("title"),
            }]

        unprocessed = []
        for idx, media in enumerate(media_nodes):
            if media.get("mediaContentType") != "IMAGE":
                continue

            image_info = media.get("image") or {}
            raw_alt = media.get("alt") or image_info.get("altText") or ""
            
            # Check if already marked 'hide' or 'bg-removed' as comma-separated tags or substring
            from .alt_helpers import has_alt_tag
            if has_alt_tag(raw_alt, "hide") or has_alt_tag(raw_alt, "bg-removed") or "bg-removed" in raw_alt.lower():
                continue

            # Check if image URL/filename already indicates bg-removed
            img_url = image_info.get("url") or ""
            if "bg-removed" in img_url.lower():
                continue

            unprocessed.append({
                "media_id": media.get("id"),
                "image_id": image_info.get("id"),
                "url": image_info.get("url"),
                "alt_text": raw_alt,
                "position": idx,
                "width": image_info.get("width"),
                "height": image_info.get("height"),
                "product_id": product.get("id"),
                "product_title": product.get("title"),
            })

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
        self, filename: str, mime_type: str = "image/png"
    ) -> Dict[str, Any]:
        """Create a staged upload target URL for uploading new image bytes to Shopify.

        Args:
            filename: Name of the file (e.g. "product-bg-removed.png").
            mime_type: MIME type of the file (default: "image/png").

        Returns:
            Dict[str, Any]: Staged upload target parameters containing url, resourceUrl, and parameters list.
        """
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
        self, staged_target: Dict[str, Any], file_bytes: bytes, filename: str = "image.png"
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

        files = {"file": (filename, file_bytes, "image/png")}

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
        """Attach a newly uploaded image media to a product.

        Args:
            product_id: Shopify product ID (e.g. "gid://shopify/Product/12345").
            original_source_url: The resourceUrl returned from staged upload.
            alt_text: Optional alt text.

        Returns:
            Dict[str, Any]: Created media object information.
        """
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
        variables = {
            "productId": gql_product_id,
            "media": [
                {
                    "originalSource": original_source_url,
                    "mediaContentType": "IMAGE",
                    "alt": alt_text,
                }
            ],
        }

        data = self._execute_query(mutation, variables)
        result = data.get("productCreateMedia", {})
        errors = result.get("mediaUserErrors", [])
        if errors:
            err_msg = "; ".join(f"{e.get('field')}: {e.get('message')}" for e in errors)
            raise NonRetryableShopifyError(f"productCreateMedia failed: {err_msg}")

        media_list = result.get("media", [])
        return media_list[0] if media_list else {}

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
        """Update media details (such as alt text) for a product.

        Args:
            product_id: Shopify product ID.
            media_id: Media ID to update.
            alt_text: New alt text (e.g. "hide").

        Returns:
            Dict[str, Any]: Updated media information.
        """
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
            "media": [
                {
                    "id": media_id,
                    "alt": alt_text,
                }
            ],
        }

        data = self._execute_query(mutation, variables)
        result = data.get("productUpdateMedia", {})
        errors = result.get("mediaUserErrors", [])
        if errors:
            err_msg = "; ".join(f"{e.get('field')}: {e.get('message')}" for e in errors)
            raise NonRetryableShopifyError(f"productUpdateMedia failed: {err_msg}")

        media_list = result.get("media", [])
        return media_list[0] if media_list else {}

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
