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
- **Idempotency Guard:** Media-level alt text (`alt="hide"` for original, `alt="bg-removed"` for processed) to prevent reprocessing and infinite loops.
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
  4. Replace / add image using `productCreateMedia` / `productDeleteMedia`.
- [x] Write CLI script to process product images (`process_product.py`).
- [x] Write unit tests (`tests/test_shopify.py`):
  - [x] Mocked Shopify GraphQL API response handlers.
  - [x] Image download and upload error handling tests.

### Stage 3: Full Product Processing & Idempotency Guard
- [x] Implement batch media processing for all images on a product.
- [x] Preserve original media ordering / positions on the product.
- [x] Implement media-level idempotency guard:
  - [x] Check media `altText` before processing (`alt == "hide"` or `alt == "bg-removed"` -> skip).
- [x] Write CLI script to safely process an entire product by ID/handle or target by sequence number (`process_product.py`).
- [x] Write unit tests:
  - [x] Idempotency guard logic (`tests/test_alt_helpers.py` verifying skip on already-processed media).
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
- [ ] Implement `BaseTaskDispatcher` interface for dispatching background tasks.
- [ ] Implement `LocalTaskDispatcher` (background thread execution for local dev/testing with in-memory deduplication).
- [ ] Implement `GCPCloudTasksDispatcher` (publishes tasks to GCP Cloud Tasks queue).
- [ ] Support GCP persistent deduplication backend (Firestore / Memorystore / Cloud Redis) for production multi-instance Cloud Functions.
- [ ] Implement `pubsub_worker` Cloud Function entrypoint to process dispatched product removal tasks.
- [ ] Write unit tests:
  - [ ] Local task dispatcher thread execution test.
  - [ ] Cloud Tasks payload serialization/deserialization.
  - [ ] End-to-end local queue to worker execution test.

### Stage 6: Live Local Webhook Testing via ngrok & Shopify
- [ ] Configure `ngrok` tunnel for testing live Shopify webhooks locally.
- [ ] Register test webhook on Shopify store pointing to `https://<ngrok-url>/shopify_webhook_receiver`.
- [ ] Perform live end-to-end test from Shopify store image upload to background removal.

### Stage 7: Production GCP Deployment Ready
- [ ] Write GCP deployment scripts (`gcloud functions deploy`).
- [ ] Provision GCP Cloud Tasks Queue (set rate limits, max dispatches/sec, exponential backoff retries, and DLQ).
- [ ] Provision GCP persistent deduplication backend (Firestore / Cloud Redis) for `X-Shopify-Webhook-Id` de-duplication across distributed Cloud Function instances.
- [ ] Document GCP Cloud Tasks, Pub/Sub, Secret Manager, and Cloud Scheduler setup.

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
│   └── webhooks/          # Webhook handlers & HMAC verification
├── tests/                 # Stage-by-stage unit & integration tests
│   ├── test_removers.py
│   └── ...
├── PLAN.md                # Tracking plan
├── requirements.txt       # Dependencies
└── main.py                # Local runner / entry point
```
