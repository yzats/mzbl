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
- [ ] Implement batch media processing for all images on a product.
- [ ] Preserve original media ordering / positions on the product.
- [ ] Implement media-level idempotency guard:
  - [ ] Check media `altText` before processing (`alt == "hide"` or `alt == "bg-removed"` -> skip).
- [ ] Write CLI script to safely process an entire product by ID/handle (`process_product.py`).
- [ ] Write unit tests:
  - [ ] Idempotency guard logic (verifying skip on already-processed media).
  - [ ] Image order preservation logic.

### Stage 4: Webhook Receiver & Local Async Execution
- [ ] Implement Webhook HTTP Server (FastAPI / Flask).
- [ ] Add Shopify HMAC-SHA256 signature verification middleware/helper.
- [ ] Implement local async in-memory task queue (decouple webhook response from background work).
- [ ] Configure `ngrok` setup for testing live Shopify webhooks locally.
- [ ] Write unit tests:
  - [ ] Valid & invalid HMAC signature verification tests.
  - [ ] Fast <500ms webhook HTTP 200 response test.
  - [ ] Queue dispatch & worker execution tests.

### Stage 5: Production GCP Deployment, Queueing, Rate Limiting & Reconciliation
- [ ] Direct Shopify Webhooks to **Google Cloud Pub/Sub** using Shopify's official Pub/Sub integration (`delivery@shopify-pubsub-webhooks.iam.gserviceaccount.com`).
- [ ] Deploy Webhook Consumer Cloud Function triggered by GCP Pub/Sub / Cloud Tasks.
- [ ] Provision GCP Cloud Tasks Queue:
  - [ ] Set max dispatches/sec & concurrency limits for Shopify API / rembg hosted API.
  - [ ] Configure exponential backoff retry rules and Dead-Letter Queue (DLQ).
- [ ] Deploy Worker Cloud Function (triggered by Cloud Tasks).
- [ ] Implement Nightly Reconciliation Job (Cloud Scheduler + Cloud Function) to process any products updated in last 24h lacking `custom.bg_removed`.
- [ ] Write unit tests:
  - [ ] Cloud Tasks payload serialization/deserialization.
  - [ ] Rate-limiting decorator and error backoff handling.

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
