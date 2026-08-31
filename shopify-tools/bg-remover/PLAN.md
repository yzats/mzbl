# Shopify Background Remover — Implementation Plan

A resilient, pluggable, and serverless pipeline for removing backgrounds from Shopify product images.

---

## 🏗️ Architecture Summary

```
[Shopify Webhook] ──> [Cloud Function Receiver] ──> [GCP Cloud Tasks Queue] ──> [Worker Cloud Function]
                           (Validates HMAC,            (Rate-limited retry        (Pluggable Remover +
                            returns HTTP 200)           queue w/ DLQ)              Shopify GraphQL API)
```

- **Pluggable Removers:** Abstract strategy pattern (`BaseBackgroundRemover`) to support hosted `rembg` instances.
- **Layered Idempotency & Anti-Race Guards:**
  - *Layer 1 (Receiver):* `X-Shopify-Webhook-Id` de-duplication prevents processing duplicate retransmissions (backed by `InMemoryDedupStore` locally, **Cloud Firestore** `webhook_dedup` collection in production).
  - *Layer 2 (Queue):* Named task `task-product-{shop_hash}-{clean_pid}-{pid_hash}-{update_hash}` coalesces the same shop + Shopify `updated_at`; later edits get a new name (Cloud Tasks ~1h tombstone is per-name).
  - *Layer 3 (Worker Lock):* Product processing lock (`lock:product:{shop_domain}:{product_id}`) prevents concurrent worker race conditions (backed by `InMemoryLockStore` locally, **Cloud Firestore** `product_locks` collection in production).
  - *Layer 4 (Media Level):* App-owned MediaImage metafield `$app.bg_state` (`source` / `result` skip; empty = process). Product tag `bg_skip` skips the product. Alt is copied, never used as a flag.
- **Resilience:** GCP Cloud Tasks for rate limiting + auto-retry, plus a daily Reconciliation Cron job to catch missed webhooks.
- **Testing:** Unit tests required at every stage.

---

## 📌 Development Stages

### Stage 1: Pluggable Remover Engine & Local Processing
- [x] Implement `BaseBackgroundRemover` abstract interface.
- [x] Implement `RembgHostedRemover` (HTTP client targeting hosted `rembg` API).
- [x] Support background hex color parameter (defaulting to white `#FFFFFF`).
- [x] Skip height/dimension parameters in API calls to let `rembg` use default image processing and sizing.
- [x] Implement error classification (retryable vs non-retryable) with exponential backoff retries.
- [x] Write CLI runner script to process a local file (`input.jpg` -> `output.png`).
- [x] Write unit tests:
  - [x] Abstract interface contract tests.
  - [x] Mocked `rembg` API tests (successful response, retryable 503 errors, non-retryable 400 errors, bad image payload).

### Stage 2: Shopify Single Image Processor
- [x] Setup Shopify GraphQL Admin API client (`ShopifyGraphQLClient`).
- [x] Implement single image processing pipeline:
  1. Download original image from Shopify CDN URL.
  2. Pass image bytes through remover provider (`RembgHostedRemover`).
  3. Upload background-removed PNG back via `stagedUploadsCreate`.
  4. Attach new media using `productCreateMedia` (originals always kept).
- [x] Write CLI script to process product images (`process_product.py`).
- [x] Write unit tests (`tests/test_shopify.py`):
  - [x] Mocked Shopify GraphQL API response handlers.
  - [x] Image download and upload error handling tests.

### Stage 3: Full Product Processing & Idempotency Guard
- [x] Implement batch media processing for all images on a product.
- [x] Preserve original media ordering / positions on the product.
  - [x] Implement media-level idempotency guard:
  - [x] Skip media with `$app.bg_state` `source` or `result`; process empty `bg_state` only.
  - [x] Skip product when tagged `bg_skip`.
  - [x] Copy original alt onto new media; do not stamp alt flags.
  - [x] Always keep originals; write `$app.bg_source` (original GID) on result media.
- [x] Write CLI script to safely process an entire product by ID/handle or target by sequence number (`process_product.py`).
- [x] Write unit tests:
  - [x] Idempotency guard logic (`tests/test_metafields.py` / `tests/test_shopify.py` verifying skip on `$app.bg_state` and `bg_skip`).
  - [x] Image order preservation logic.

### Stage 4: Webhook Receiver & HMAC Verification (Functions Framework)
- [x] Implement `verify_shopify_hmac()` helper to validate incoming `X-Shopify-Hmac-Sha256` headers against `SHOPIFY_CLIENT_SECRET`.
- [x] Implement `WebhookDeduplicator` (`X-Shopify-Webhook-Id` tracking) to prevent rapid webhook retransmissions/replays.
- [x] Implement `shopify_webhook_receiver` HTTP entrypoint using Google's `functions-framework` format.
- [x] Parse Shopify product update/create webhook payloads and extract product ID & media info.
- [x] Return fast `<500ms` `HTTP 200 OK` response to Shopify.
- [x] Write unit tests (`tests/test_webhooks.py`):
  - [x] Valid HMAC verification passes.
  - [x] Invalid/tampered HMAC returns `HTTP 401 Unauthorized`.
  - [x] Webhook ID deduplication test (`X-Shopify-Webhook-Id` duplicate detection).
  - [x] Malformed payload / non-product webhook handling.

### Stage 5: Pluggable Task Queue & Local/GCP Worker Pipeline
- [x] Implement `BaseTaskDispatcher` interface for dispatching lightweight background tasks (`product_id`, `shop_domain`, `topic`).
- [x] Implement `LocalTaskDispatcher` (background thread execution with `InMemoryLockStore` concurrency guard for local dev/testing).
- [x] Implement `GCPCloudTasksDispatcher` using Named Tasks (`task-product-{shop_hash}-{clean_pid}-{pid_hash}-{update_hash}`) to coalesce the same shop + product revision without a 1-hour per-product tombstone.
- [x] Implement provider-agnostic `BaseLockStore` & `BaseDedupStore` interfaces:
  - [x] `InMemoryLockStore` / `InMemoryDedupStore`: In-memory implementation with TTL for local development and testing.
  - [x] `GCPFirestoreLockStore` / `GCPFirestoreDedupStore`: GCP Cloud Firestore backend (`product_locks` and `webhook_dedup` collections with TTL) for production GCP Cloud Functions.
- [x] Implement `bg_remover_worker` Cloud Function entrypoint to process queued product removal tasks (processing all unprocessed images per task).
- [x] Write unit tests (`tests/test_queue.py`):
  - [x] Local task dispatcher thread execution test.
  - [x] Product processing lock acquire/release and conflict test.
  - [x] Cloud Tasks payload serialization/deserialization.
  - [x] End-to-end local queue to worker execution test.

### Stage 6: Live Local Webhook Testing via ngrok & Shopify
- [x] Create helper runner script (`run_local_server.py`) to launch local `functions-framework` server on port 8080.
- [x] Configure `ngrok` tunnel (`ngrok http 8080`) for receiving live Shopify webhooks locally.
- [x] Register webhook on Shopify store pointing to `https://<ngrok-url>`.
- [x] Perform live end-to-end test from Shopify store image upload to background removal and verify trace logs & idempotency cascade stopping.

### Stage 7: Production GCP Deployment Ready
- [x] Write GCP automated deployment script (`deploy_gcp.sh`).
- [x] Provision GCP Cloud Tasks Queue (`bg-remover-queue` with rate limits & retries).
- [x] Provision GCP Cloud Firestore collections (`webhook_dedup`, `product_locks`, and `shops` via Firestore stores).
- [x] Document GCP Cloud Tasks, Secret Manager, IAM, and deployment procedure in `ARCHITECTURE.md`.

### Stage 8: Multi-store control plane
- [x] MediaImage `$app.bg_state` Layer 4; copy original alt; product tag `bg_skip`. Originals always kept. Result stores `$app.bg_source` (original GID).
- [x] Shop registry (in-memory / Firestore `shops`) and `bg_remover_control` HTTP API (`registerShop`, `unregisterShop`, `setConfig`, `getShopStatus`, `syncEntitlement`).
- [x] Worker loads per-shop token from registry (local `config.py` fallback); shop-scoped locks and Cloud Tasks names.
- [x] Honor `autoEnabled`, `imagesScope`, and hex `fillMode` from shop config.

---

## 🛠️ Tech Stack & Directory Structure
```text
mzbl/shopify-tools/bg-remover/
├── src/
│   ├── removers/          # Pluggable remover interfaces & implementations
│   │   ├── __init__.py
│   │   ├── base.py        # Abstract Base class
│   │   └── rembg_http.py  # Rembg hosted API client
│   ├── shopify/           # Shopify GraphQL API client & metafield guards
│   ├── queue/             # Queue execution abstraction (Local -> GCP Cloud Tasks)
│   ├── control/           # Multi-shop control-plane HTTP API
│   └── webhooks/          # Webhook handlers & HMAC verification
├── tests/                 # Stage-by-stage unit & integration tests
│   ├── test_removers.py
│   └── ...
├── PLAN.md                # Tracking plan
├── requirements.txt       # Dependencies
└── main.py                # Local runner / entry point
```
