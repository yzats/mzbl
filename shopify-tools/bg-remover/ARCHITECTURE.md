# Shopify Background Remover — System Architecture & Design Specification

> **IMPORTANT MAINTENANCE RULE FOR AGENTS & DEVELOPERS:**
> This document is the single source of truth for the Shopify Background Remover architecture, design decisions, data models, and component contracts.
> **Mandatory Rule:** Whenever any implementation detail, method signature, data structure, or infrastructure component is modified, added, or removed in the codebase, this document **MUST** be updated immediately in the same commit/change set to remain 100% in sync with the codebase.

---

## 📌 1. Executive Summary & Objectives

The **Shopify Background Remover** is a pluggable, serverless, rate-limited, and idempotent pipeline that automatically removes backgrounds from Shopify product images when products are created or updated. Default rembg output is **transparent WebP**. When a shop’s Autopilot BgRemover config uses `fillMode=hex`, the worker sends `bg_color` on `/rmbg`.

### Key Objectives
- **Zero Human Intervention:** Runs automatically in the background via Shopify HTTP Webhooks.
- **Strict Idempotency:** Guarantees that re-sent webhooks, cascade webhooks from media additions, or rapid concurrent updates **never** cause infinite loops or duplicate image processing.
- **Provider Agnostic:** Uses abstract strategy patterns for background removers, task dispatchers, lock stores, and deduplication stores.
- **100% Local Development Parity:** Runs locally using Google's `functions-framework` and `ngrok` with exact parity to production GCP Cloud Functions.

---

## 🏗️ 2. System Architecture & Data Flow

### Complete System Topology

```
                               ┌─────────────────────────────────────────────────────────┐
                               │                    SHOPIFY STORE                        │
                               └───────────────────────────┬─────────────────────────────┘
                                                           │ HTTP POST (products/update)
                                                           ▼
                               ┌─────────────────────────────────────────────────────────┐
                               │             STAGE 4: WEBHOOK RECEIVER                   │
                               │        (functions-framework / Cloud Function)           │
                               │                                                         │
                               │  1. Verify X-Shopify-Hmac-Sha256                        │
                               │  2. Check X-Shopify-Webhook-Id in DedupStore            │
                               │  3. Respond HTTP 200 OK (<200ms)                        │
                               └───────────────────────────┬─────────────────────────────┘
                                                           │ Async Dispatch
                                                           ▼
                               ┌─────────────────────────────────────────────────────────┐
                               │             STAGE 5: TASK DISPATCHER                    │
                               │  Local: ThreadPool / GCP: Cloud Tasks (Named Tasks)     │
                               └───────────────────────────┬─────────────────────────────┘
                                                           │ Executes Job Payload
                                                           ▼
                               ┌─────────────────────────────────────────────────────────┐
                               │              STAGE 5: WORKER FUNCTION                   │
                               │                                                         │
                               │  1. Acquire ProductLock(shop_domain, product_id)        │
                               │  2. Load shop token from registry (or local fallback)   │
                               │  3. Query get_unprocessed_images() (`$app.bg_state`)    │
                               │  4. Download original CDN image bytes                   │
                               │  5. Send to RembgHostedRemover API (hex fill optional)  │
                               │  6. Upload staged file (stagedUploadsCreate)            │
                               │  7. Batch GraphQL: productCreateMedia (copy original alt)│
                               │  8. Batch GraphQL: productReorderMedia                  │
                               │  9. metafieldsSet bg_state + bg_source (keep originals) │
                               │ 10. Release ProductLock                                 │
                               └─────────────────────────────────────────────────────────┘
```

---

## 🛡️ 3. 4-Layer Idempotency & Anti-Race Architecture

Because background removal takes 3–5 seconds per image and Shopify emits webhooks on every product/media change, we employ a **4-Layer Idempotency & Concurrency Defense**:

```
Layer 1: Webhook ID Guard (DedupStore)
  └── Drop retransmitted webhooks using X-Shopify-Webhook-Id header (5 min TTL).

Layer 2: Named Task Queue Guard (GCP Cloud Tasks / Local Task ID)
  └── Task Name = task-product-{shop_hash}-{clean_pid}-{pid_hash}-{update_hash}.
      Coalesces in-flight duplicates of the same shop + Shopify updated_at.
      A later product edit gets a new name (Cloud Tasks tombstones names ~1 hour).

Layer 3: Distributed Worker Lock (ProductLock)
  └── Acquires 2-minute lock lock:product:{shop_domain}:{product_id}. Concurrent runs exit immediately.

Layer 4: Media-Level `$app.bg_state` Guard (get_unprocessed_images)
  └── Skip product tag `bg_skip`. Skip media with bg_state source or result. Empty = process.
      Result media also stores `$app.bg_source` (original MediaImage GID). Alt is copied, never a flag.
```

### Layer Details:
1. **Layer 1 (Receiver Level):** Verifies `X-Shopify-Hmac-Sha256` **first**. Only then does it consult `X-Shopify-Webhook-Id`. Failed HMAC must not record the id (`was_seen` / `remember`, not mark-on-read `is_duplicate`). If Shopify re-sends the same id within 5 minutes, the receiver logs `[200 SKIPPED]`, returns `"status": "ignored"`.
2. **Layer 2 (Queue Level):** In GCP, task names are `projects/.../tasks/task-product-{shop_hash}-{clean_pid}-{pid_hash}-{update_hash}`. `shop_hash` is SHA-256[:8] of the shop domain (product IDs are per-shop). `update_hash` is SHA-256[:12] of Shopify `updated_at` (fallback: webhook id, then a 30-second time bucket). Cloud Tasks uniqueness therefore drops **duplicate deliveries of the same shop+product revision** while a task is queued/running, without blocking a new image upload an hour later. Completed names remain tombstoned for ~1 hour, but only for that revision's name. A hit logs `[TASK DEDUPED]` / `[200 DEDUPED]` at WARNING and returns `"status": "deduplicated"`.
3. **Layer 3 (Worker Level):** A distributed lock `lock:product:{shop_domain}:{product_id}` is acquired before worker processing begins. If another worker thread is actively processing the same product on that shop, the new worker logs `Product lock active` and terminates cleanly (HTTP 200).
4. **Layer 4 (Media State Level):** The worker queries Shopify GraphQL for live product media. The product tag `bg_skip` skips the whole product. Each MediaImage `$app.bg_state` is `source` (original we processed), `result` (background-removed output), or empty (not processed). Skip `source` and `result`. Originals are always kept. Result media stores `$app.bg_source` with the original MediaImage GID (pairing, not a skip flag). Copy the original `alt` onto new media; do not write flags into alt. When nothing is left to process, the worker exits in `<100ms`.

---

## 🧩 4. Component Contracts & Interfaces

All major subsystems use abstract interfaces to support provider swapping (e.g. Local vs GCP vs AWS).

### A. Background Remover Interface (`src/removers/`)
- **`BaseBackgroundRemover` (`base.py`)**:
  ```python
  def remove_background(self, image_data: bytes, bg_color: Optional[str] = None) -> bytes
  ```
- **`RembgHostedRemover` (`rembg_http.py`)**:
  - Sends raw image bytes to rembg API (`https://api.rembg.com/rmbg`).
  - **No `height` parameter is sent** — lets rembg perform default image processing and sizing.
  - Multipart `image` plus `x-api-key`. **Do not send `format`**. Omit `bg_color` for transparent WebP; send `bg_color` only when the shop config `fillMode` is `hex`.
  - Classifies HTTP errors (`RetryableBackgroundRemoverError`, `RembgUnavailableError`, `NonRetryableBackgroundRemoverError`). On HTTP 200, rejects free-tier **460×460** API output via `output_is_freemium_capped` (see below).

### B. Task Dispatcher Interface (`src/queue/`)
- **`BaseTaskDispatcher` (`base.py`)**:
  ```python
  class DispatchResult(NamedTuple):
      task_id: str
      outcome: str  # "enqueued" | "deduplicated" | "simulated"

  def dispatch_product_task(self, product_id: str, shop_domain: str, topic: str, metadata: Optional[dict]) -> DispatchResult
  ```
  Dedup is **not silent**: Cloud Tasks `ALREADY_EXISTS` and duplicate webhook IDs emit one structured line (`src/utils/applog.py`) with `severity` + `message` (no `print` + `logger` doubles). Expected skips/dedup/enqueue are **INFO**; HMAC 401 is **WARNING**; poison/enqueue failure is **ERROR**. Circuit OPEN/STILL OPEN are **WARNING**; CLOSED and “queue already running” are **INFO**. Tags (`[TASK DEDUPED]`, `[200 DEDUPED]`, `[CIRCUIT OPEN]`, …) stay in `message` for log-based metrics. The HTTP JSON body uses `"status": "deduplicated"` or `"status": "ignored"` instead of `"success"`.
- **`LocalTaskDispatcher` (`local_dispatcher.py`)**: Dispatches tasks in background Python daemon threads for local development.
- **`GCPCloudTasksDispatcher` (`gcp_dispatcher.py`)**: Named Cloud Tasks `task-product-{shop_hash}-{clean_pid}-{pid_hash}-{update_hash}` so the same shop + Shopify `updated_at` is coalesced, but a later edit is not blocked by the 1-hour name tombstone.

### C. Lock & Deduplication Stores (`src/queue/`)
- **`BaseLockStore` (`base.py`)** & **`BaseDedupStore` (`base.py`)**: Abstract contracts for locks and webhook-id dedup (`was_seen` / `remember`; `is_duplicate` is check-then-remember).
- **`InMemoryLockStore` & `InMemoryDedupStore` (`memory_stores.py`)**: In-memory dict-based stores with TTL expiration for local development.
- **`GCPFirestoreLockStore` & `GCPFirestoreDedupStore` (`firestore_stores.py`)**: GCP Cloud Firestore implementations (`product_locks` and `webhook_dedup` collections) with TTL policy support. Document IDs are `firestore_document_id(key)` (SHA-256 hex) because Shopify GIDs contain `/`. Client construction catches missing credentials / import errors so unit tests and local runs without ADC do not crash.

### D. Shop registry (`src/queue/`)
- **`BaseShopStore` (`base.py`)**: `get_shop` / `upsert_shop` / `delete_shop`. Document ID is SHA-256 of the `*.myshopify.com` host. Never log `accessToken`.
- **`InMemoryShopStore` (`memory_stores.py`)** & **`GCPFirestoreShopStore` (`firestore_stores.py`, `shops` collection)**. Local CLI keeps `config.py` token fallback when the shop is **not** in the registry (and the configured `SHOPIFY_STORE_URL` is empty or matches that host).
- **`product_lock_key(shop_domain, product_id)`** → `lock:product:{shop_domain}:{product_id}` (product IDs are per-shop).

### E. Control-plane HTTP API (`src/control/api.py`)
Public HTTPS Cloud Function `bg_remover_control` (not Shopify HMAC). Header `X-Bg-Control-Secret` must match Secret Manager / env `GCP_CONTROL_SECRET`. Writes return `{ ok: true }`. Status JSON matches Autopilot BgRemover `ShopStatus` with `placeholder: false`; credits/progress are zeros or null until billing.

| App client | HTTP | Body / query |
|------------|------|----------------|
| `registerShop` | `POST /v1/shops/register` | `{ shop, accessToken, scope? }` |
| `unregisterShop` | `POST /v1/shops/unregister` | `{ shop }` |
| `setConfig` | `PUT /v1/shops/config` | `{ shop, autoEnabled, fillMode, fillHex, imagesScope, forceReprocessDefault }` |
| `getShopStatus` | `GET /v1/shops/status?shop=` | — |
| `syncEntitlement` | `POST /v1/shops/entitlement` | `{ shop, planHandle, creditsIncluded, periodStart?, periodEnd? }` |

Worker: resolve Admin host from `X-Shopify-Shop-Domain` (already in the task payload). Unregistered shop → HTTP 200 skip. Registered with `autoEnabled` false → HTTP 200 skip. Honor `imagesScope` (`all` \| `featured`) and hex `fillMode`/`fillHex` via rembg `bg_color`. Product tag `bg_skip` skips the whole product (Layer 4).

---

## ⚡ 5. Resiliency, Error Classification & Retry Strategies

To ensure zero lost tasks and prevent infinite retries on permanent failures, both external provider interfaces (`rembg` and `Shopify Admin API`) implement strict **Error Classification**, **Exponential Backoff Retries**, and **HTTP Status Code Mapping**.

---

### A. Background Remover Interface (`src/removers/`) Error Handling

The background remover client (`RembgHostedRemover`) categorizes rembg API responses in `src/removers/base.py`:

```
                    ┌───────────────────────────────┐
                    │    BackgroundRemoverError     │
                    └──────────────┬────────────────┘
           ┌───────────────────────┼───────────────────────┐
           ▼                       ▼                       ▼
┌─────────────────────┐ ┌──────────────────────┐ ┌──────────────────────────┐
│ RetryableBackground │ │ RembgUnavailableError│ │ NonRetryableBackground   │
│ RemoverError        │ │ 401, 402, 403        │ │ RemoverError             │
│ 429, 5xx, timeout   │ │ Pause queue + 503    │ │ 400, 404, bad image      │
└─────────────────────┘ └──────────────────────┘ └──────────────────────────┘
```

#### Status Code & Exception Mapping (`rembg_http.py`):
| HTTP Status / Condition | Exception Raised | Worker Response | Retry Strategy |
| :--- | :--- | :--- | :--- |
| **HTTP 200 OK (paid-size output)** | None (Returns image bytes) | HTTP 200 Success | None |
| **HTTP 200, output fits 460×460, and input longest side > 468** | `RembgUnavailableError` | Pause queue + **HTTP 503** | Free API cap per [pricing](https://www.rembg.com/en/pricing). Do not upload. Leeway is on input vs 460 (461–468 into the box is allowed), not an isolated shrink delta. Originals already ≤ 460×460 are not flagged. |
| **HTTP 429 short-term / daily rate limit** | `RetryableBackgroundRemoverError` (`pause_circuit=False`) | **HTTP 503** after in-process retries; **do not pause** the queue | rembg allows **200 req / 10s** per key. Honor response `Retry-After` (`45`, `45s`, or HTTP-date) on that task only; fall back to 1s/2s/4s if the header is missing. Skip the sleep and raise if it would exceed a **90s** in-process budget (worker timeout is 120s). Parse JSON `error` / `details[].message` ([api-usage](https://www.rembg.com/en/api-usage)); if the text does **not** match credit exhaustion, treat as rate limit. |
| **HTTP 429 monthly / credits** | `RembgUnavailableError` | Pause queue + **HTTP 503** | Same JSON shapes; if any message contains `monthly limit` **or** `purchasing` (e.g. "You've reached your monthly limit. Consider purchasing more credits."), no in-process `/rmbg` retries. |
| **HTTP 500, 502, 503, 504** | `RetryableBackgroundRemoverError` | Pause queue + **HTTP 503** | Same as 429. |
| **Network Timeout / Connection Error** | `RetryableBackgroundRemoverError` | Pause queue + **HTTP 503** | Same as 429. |
| **HTTP 400 (Bad Request / Corrupted)** | `NonRetryableBackgroundRemoverError` | **HTTP 400** | **NO RETRY.** Queue stays running. |
| **HTTP 401, 402, 403 (credits / auth)** | `RembgUnavailableError` | Pause queue + **HTTP 503** | No in-process retry. Pause Cloud Tasks; do not ack the task. |
| **HTTP 404, 415, 422** | `NonRetryableBackgroundRemoverError` | **HTTP 400** | **NO RETRY.** Queue stays running. |
| **Empty Input / Empty Response Bytes** | `NonRetryableBackgroundRemoverError` | **HTTP 400** | **NO RETRY.** |

#### Free-tier 200 detection (`output_is_freemium_capped`)

When credits run out, rembg may still return HTTP 200 with a downscaled image ([pricing](https://www.rembg.com/en/pricing): Free API max **460×460**). Constants: `FREEMIUM_API_MAX_EDGE = 460`, `FREEMIUM_SHRINK_LEEWAY_PX = 8`.

Treat as **out of credits** (`RembgUnavailableError`, do not upload) only if **all** of the following hold:

1. Input and output bytes both decode as images.
2. Input does **not** already fit in 460×460 (at least one side > 460).
3. Output **does** fit entirely in 460×460 (`out_w ≤ 460` and `out_h ≤ 460`).
4. Input longest side is **> 468** (`460 + 8`).

Otherwise keep the image. In particular **2000→1000** is not freemium (1000 is outside the free box). **461→460** and **468→460** are allowed (source only barely above the cap).

| Input | Output | Freemium? |
| :--- | :--- | :--- |
| 800×600 | 460×460 or 460×400 | Yes |
| 2000×2000 | 460×460 | Yes |
| 469×469 | 460×460 | Yes |
| 2000×2000 | 1000×1000 | No |
| 800×600 | 800×600 | No |
| 400×300 | 400×300 | No |
| 461×461 or 468×468 | 460×460 | No |
| 2000×2000 | 461×461 | No (outside free box) |
| Unreadable bytes | any | No (skip check) |

---

### B. Shopify Admin GraphQL Client (`src/shopify/`) Error Handling

The Shopify GraphQL client (`ShopifyGraphQLClient` in `src/shopify/client.py`) implements matching error classification for CDN downloads and GraphQL queries/mutations:

```
                      ┌───────────────────────────────┐
                      │        ShopifyAPIError        │
                      │        (Base Exception)       │
                      └──────────────┬────────────────┘
                                     │
            ┌────────────────────────┴────────────────────────┐
            ▼                                                 ▼
┌───────────────────────────────────────┐   ┌───────────────────────────────────────────┐
│        RetryableShopifyError          │   │       NonRetryableShopifyError            │
│ (Transient errors: 429, 500, 502-504) │   │ (GraphQL userErrors, 400, Product 404)    │
└───────────────────────────────────────┘   └───────────────────────────────────────────┘
```

#### Status Code & Exception Mapping (`client.py`):
| Condition / GraphQL Field | Exception Raised | Worker Response | Retry Strategy |
| :--- | :--- | :--- | :--- |
| **HTTP 200 + `errors: []` / `userErrors: []`** | None (Returns parsed GraphQL data) | HTTP 200 Success | None |
| **HTTP 429 (Leaky Bucket Limit)** | `RetryableShopifyError` | **HTTP 503** | Retried with exponential backoff (1s, 2s, 4s...). |
| **HTTP 500, 502, 503, 504** | `RetryableShopifyError` | **HTTP 503** | Retried with exponential backoff. |
| **CDN Download Timeout / Conn Error** | `RetryableShopifyError` | **HTTP 503** | Retried with exponential backoff. |
| **GraphQL `userErrors` Present** | `NonRetryableShopifyError` | **HTTP 400** | **NO RETRY.** Logged as invalid GraphQL payload and dropped. |
| **Product Not Found (`product: null`)** | `NonRetryableShopifyError` | **HTTP 400** | **NO RETRY.** Product deleted from store; drops task cleanly. |

---

### C. Exponential Backoff Decorator Contract (`src/utils/retry.py`)

All HTTP network operations utilize the `@retry_with_exponential_backoff` decorator:

```python
def retry_with_exponential_backoff(
    retries: int = 3,
    backoff_in_seconds: float = 1.0,
    retryable_exceptions: Tuple[Type[Exception], ...] = (Exception,),
)
```

- **Algorithm:** Delay between retry $i$ (where $i \in \{1, \dots, N\}$) is calculated as:
  $$\text{delay} = \text{backoff\_in\_seconds} \times 2^{(i - 1)}$$
  *(e.g., initial delay 1.0s $\rightarrow$ 1.0s, 2.0s, 4.0s).*
- **Retry-After:** If the exception has `retry_after_seconds` (rembg rate-limit 429), sleep that duration instead of the exponential delay. Sleeps that would exceed `max_in_process_seconds` (default **90s** from the first attempt) are skipped and the error is re-raised so the worker can return 503 before the 120s timeout.
- **Queue Level Escalation:** If all $N$ in-memory retries fail, the exception bubbles up to `worker.py`. `RembgUnavailableError` and retryable rembg errors with `pause_circuit=True` (5xx, timeout) **pause** `bg-remover-queue` and return **HTTP 503**. Rate-limit 429 (`pause_circuit=False`) returns **HTTP 503** without pausing. `RetryableShopifyError` returns **HTTP 503** without pausing (Shopify leaky bucket is not a rembg outage).

---

## ⚡ 6. GraphQL Batching & Shopify API Optimizations

To minimize API costs and webhook cascades, processing is **batched per product**:

```text
1. Fetch live product media via GraphQL (get_unprocessed_images: tags + `$app.bg_state`)
2. For each unprocessed image:
   ├── Download raw image bytes from Shopify CDN
   ├── Send bytes to rembg API
   └── Upload WebP via stagedUploadsCreate & upload_file_to_staged_target
3. Batched GraphQL for the entire product:
   ├── productCreateMedia: new staged WebPs with original alt copied verbatim
   ├── productReorderMedia: move new media to original position indices
   └── metafieldsSet: `$app.bg_state=result` and `$app.bg_source` (original MediaImage GID)
       on new media; `$app.bg_state=source` on originals (always kept)
```

### Key Benefits:
- **Reduces GraphQL API Calls:** Mutations are batched per product (create, reorder, one metafieldsSet).
- **Coalesces Webhooks:** Rapid GraphQL calls in 1 second cause Shopify to coalesce follow-up webhooks, preventing webhook storms.

---

## ☁️ 8. Production GCP Infrastructure Specification

The production deployment runs on a 100% serverless, zero-standing-cost Google Cloud Platform (GCP) architecture:

```
[Shopify shops] ── HMAC products/create|update ──> [Receiver Cloud Function v2]
                                                         │
                                                         ├─ Read Secrets ──> [GCP Secret Manager]
                                                         ├─ Deduplicate ───> [GCP Cloud Firestore] (webhook_dedup)
                                                         │
                                                         ▼
                                               [GCP Cloud Tasks Queue]
                                               (Queue: bg-remover-queue, Rate Limit: 5/s)
                                                         │
                                                         ▼ (OIDC Authenticated HTTP POST)
                                               [Worker Cloud Function v2]
                                                         │
                                                         ├─ Shop token ────> [GCP Cloud Firestore] (shops)
                                                         ├─ Acquire Lock ──> [GCP Cloud Firestore] (product_locks)
                                                         ├─ Image Rembg ───> [Rembg Hosted API]
                                                         └─ GraphQL Admin ─> [per-shop Shopify API]

[Autopilot BgRemover] ── X-Bg-Control-Secret ──> [bg_remover_control]
                                              └─ register / setConfig / status / entitlement / unregister
                                                 writes Firestore `shops`
```

---

### A. GCP Cloud Functions (v2 Serverless Runtime)

| Function Name | Trigger Type | Runtime | Memory / CPU | Concurrency | Timeout | IAM Roles & Secret Access |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `shopify_webhook_receiver` | HTTP POST | Python 3.11/3.12 | 256 MB / 0.17 vCPU | 80 | 10 seconds | `roles/cloudtasks.enqueuer`, access to `SHOPIFY_WEBHOOK_SECRET` |
| `bg_remover_worker` | HTTP POST | Python 3.11/3.12 | 512 MB / 0.5 vCPU | 10 | 120 seconds | `roles/datastore.user`, Cloud Tasks runner/queueAdmin, `SHOPIFY_ADMIN_API_ACCESS_TOKEN` (local fallback), `REMBG_API_KEY`. Admin host from task `shop_domain` (`*.myshopify.com`); token from Firestore `shops` (else local fallback matching that host). |
| `rembg_circuit_probe` | HTTP GET/POST (Cloud Scheduler every 5 min, OIDC) | Python 3.11/3.12 | 256 MB / 0.17 vCPU | 1 | 60 seconds | Same runtime SA; `REMBG_API_KEY`. Always `GET` membership-usage for credit gauges. If the queue is **paused** and `credits > 0` or `prepaidCredits > 0`, one `/rmbg` canary (32×32 PNG, `max_retries=0`) must succeed before resume. Canary failures back off 5/15/30/60 minutes via Firestore `circuit_state/rembg` (fail-open). No canary while the queue is running. **Not** a task on `bg-remover-queue`. |
| `bg_remover_control` | HTTP POST/PUT/GET | Python 3.11/3.12 | 256 MB / 0.17 vCPU | 80 | 10 seconds | `roles/datastore.user`, `GCP_CONTROL_SECRET`. Public HTTPS; auth header `X-Bg-Control-Secret`. Paths: `POST /v1/shops/register`, `POST /v1/shops/unregister`, `PUT /v1/shops/config`, `GET /v1/shops/status`, `POST /v1/shops/entitlement`. |

---

### B. GCP Cloud Tasks Queue (`bg-remover-queue`)

- **Purpose:** Acts as a rate-limiting buffer, retry scheduler, and deduplication layer between incoming webhooks and background removal workers.
- **Deduplication Strategy:** Named Tasks `task-product-{shop_hash}-{clean_pid}-{pid_hash}-{update_hash}`. Uniqueness coalesces the same shop + `updated_at` (retries / webhook storms). A new Shopify `updated_at` creates a new task name so Cloud Tasks' ~1 hour tombstone does not skip later product edits. Layers 3–4 still no-op cascade webhooks from our own media writes.
- **Queue Configuration Specification:**
  ```yaml
  name: projects/{PROJECT_ID}/locations/us-central1/queues/bg-remover-queue
  rateLimits:
    maxDispatchesPerSecond: 5.0
    maxBurstSize: 10
    maxConcurrentDispatches: 10
  retryConfig:
    maxAttempts: -1
    minBackoff: 5s
    maxBackoff: 300s
    maxDoublings: 3
  ```
  `maxAttempts: -1` is unlimited. Rembg down or out of credits must **not** drop product work: the worker pauses the queue and returns HTTP **503**; tasks sit until resume and retry until rembg succeeds. The probe will not resume a paused queue until a `/rmbg` canary succeeds (membership-usage credits alone are not enough). Unlimited attempts are the safety net if `/rmbg` flaps after resume. Shopify HTTP **503** uses the same queue and also retries until success. HTTP **400** (poison) still acks and drops.
- **Rembg circuit (pause, not a Pub/Sub DLQ):** On rembg 401/402/403 or credit-exhaustion 429 (immediately) or 5xx/timeout (after in-process retries), the **worker** calls Cloud Tasks `pause_queue` on `bg-remover-queue` and returns **HTTP 503** so the current task is **not** deleted. Short-term rembg 429 does **not** pause; the worker honors `Retry-After` in-process then returns **HTTP 503** so Cloud Tasks retries that task. The probe never pauses the queue. New webhooks can still enqueue; they sit until resume. `rembg_circuit_probe` (Cloud Scheduler every **5 minutes**, HTTP OIDC, **not** a task on this queue) **always** calls [`GET /api/membership-usage`](https://www.rembg.com/api/docs#tag/account) on `www.rembg.com` (the account API; not `/rmbg`) so the credits dashboard updates every tick. It writes `custom.googleapis.com/bg_remover/rembg_credits` and `.../rembg_prepaid_credits` whenever the JSON includes those fields (including zeros or a non-200 body that still reports balances; fail-open). If the queue is paused and `credits > 0` or `prepaidCredits > 0`, it then runs one `/rmbg` canary (32×32 PNG, no in-process retry) and `resume_queue` only when that succeeds. Consecutive canary failures set `next_canary_at` 5/15/30/60 minutes out on Firestore `circuit_state/rembg` (fail-open). Empty credits (`credits = 0` and `prepaidCredits = 0`) reset that backoff and skip the canary. No canary while the queue is already running. Pause/resume and the probe write `.../circuit_open` (**1** paused, **0** running) for the dashboard state chart. The worker increments `.../images_processed` after a successful batch. Logs `[CIRCUIT OPEN]` on a new worker pause and `[CIRCUIT STILL OPEN]` only if the probe fails **while the queue is already paused** (one `applog` line via `emit_circuit_log`: WARNING for OPEN/STILL OPEN, INFO for CLOSED). Optional `alert_sms` (E.164) and/or `alert_email`: metric alert on those logs (5-minute buckets). SMS/email on **open** and **close**; the incident **closes ~5 minutes after resume** when STILL OPEN logs stop. No 24-hour nag. Poison pills (bad image, product 404) still HTTP 400 and do not pause.

**Out-of-credits fault inject:** set `REMBG_FAULT_INJECT=out_of_credits` at request time in `RembgHostedRemover` (not in Terraform or `deploy_gcp.sh`). `/rmbg` raises `RembgUnavailableError` without calling rembg; membership-usage returns `{credits: 0, prepaidCredits: 0}`. Logs `[FAULT INJECT] rembg out_of_credits`. Toggle both Gen2 Cloud Run services so the probe cannot resume while the worker is faulted. Next `deploy_gcp.sh` `--set-env-vars` replace-all **clears** the flag.

```bash
for svc in bg-remover-worker rembg-circuit-probe; do
  gcloud run services update "$svc" --region=us-central1 --project=mzbl-shopify-bg-remover \
    --update-env-vars=REMBG_FAULT_INJECT=out_of_credits
done
```

```bash
for svc in bg-remover-worker rembg-circuit-probe; do
  gcloud run services update "$svc" --region=us-central1 --project=mzbl-shopify-bg-remover \
    --remove-env-vars=REMBG_FAULT_INJECT
done
```

Local: `export REMBG_FAULT_INJECT=out_of_credits`.

---

### C. GCP Cloud Firestore (Native Serverless Storage)

- **Database Mode:** Native Mode.
- **Collections Specification:**
  1. **`webhook_dedup` Collection:**
     - **Document ID:** SHA-256 hex of the `X-Shopify-Webhook-Id` value (Firestore IDs cannot contain `/`).
     - **Fields:** `key` (original webhook id string), `created_at` (number, unix seconds), `expires_at` (number, unix seconds, set to `now + 300s`).
     - **TTL Policy:** Enabled on `expires_at` field to auto-delete expired webhook records.
  2. **`product_locks` Collection:**
     - **Document ID:** SHA-256 hex of `lock:product:{shop_domain}:{product_id}` (product_id is a Shopify GID containing `/`, which is illegal in a raw document name).
     - **Fields:** `lock_key` (original lock string), `created_at` (number, unix seconds), `expires_at` (number, unix seconds, set to `now + 120s`).
     - **TTL Policy:** Enabled on `expires_at` field for automatic lock auto-release on crashed workers.
  3. **`shops` Collection:**
     - **Document ID:** SHA-256 hex of the shop domain (`cool-shoes.myshopify.com`).
     - **Fields:** `shop`, `accessToken` (offline token; never log), `scope`, `status`, `autoEnabled`, `fillMode`, `fillHex`, `imagesScope`, `forceReprocessDefault`, `planHandle`, `creditsIncluded`, `periodStart`, `periodEnd`, `updatedAt`.
     - **No TTL.** Written by `bg_remover_control`; read by `bg_remover_worker`.
  4. **`circuit_state` Collection:**
     - **Document ID:** `rembg`.
     - **Fields:** `fail_count` (int), `next_canary_at` (unix seconds), `updated_at` (unix seconds). Written fail-open by the probe. After a failed `/rmbg` canary, `next_canary_at` is now plus 5/15/30/60 minutes by consecutive `fail_count`. Success or a probe with `credits = 0` and `prepaidCredits = 0` resets both fields.

---

### D. GCP Secret Manager & IAM Security

- **Secrets Managed:**
  - `SHOPIFY_WEBHOOK_SECRET`
  - `SHOPIFY_CLIENT_SECRET`
  - `SHOPIFY_ADMIN_API_ACCESS_TOKEN`
  - `REMBG_API_KEY`
  - `GCP_CONTROL_SECRET`
- **Secret Access:** Mounted directly into Cloud Functions environment variables at container startup (`secretKeyRef`). `get_webhook_secret()` and the worker settings loader **prefer environment variables** over `config.py`, so production Secret Manager values are never shadowed by a local or third-party `config` module. Secrets are stripped of surrounding whitespace (common Secret Manager paste issue).
- **OIDC Service Account Authentication:** Cloud Tasks uses an OIDC ID token generated by a dedicated Service Account (`bg-remover-sa@...iam.gserviceaccount.com`) to authenticate HTTP POST invocations to `bg_remover_worker`. The worker endpoint enforces `roles/run.invoker`.

---

## 💻 7. Local Development vs. Production GCP Parity

| Component | Local Development (`functions-framework`) | GCP Production Deployment |
| :--- | :--- | :--- |
| **HTTP Server** | `functions-framework --port=8080` | GCP Cloud Functions (v2) HTTP Trigger |
| **Tunnel / Delivery** | `ngrok http 8080` | Direct Shopify Webhook delivery |
| **Task Queue** | `LocalTaskDispatcher` (Daemon Thread) | `GCPCloudTasksDispatcher` (Cloud Tasks Queue) |
| **Deduplication Store** | `InMemoryDedupStore` | `GCPFirestoreDedupStore` (`webhook_dedup` coll) |
| **Product Lock Store** | `InMemoryLockStore` | `GCPFirestoreLockStore` (`product_locks` coll) |
| **Shop registry** | `InMemoryShopStore` | `GCPFirestoreShopStore` (`shops` coll) |
| **Control plane** | `run_local_control.py` port 8081 | `bg_remover_control` Cloud Function |
| **Secrets & Config** | `config.py` / `.env` | GCP Secret Manager / Environment Vars |

---

## 📁 9. Repository Directory Structure

```text
shopify-tools/
├── config.py                            # Local configuration & credentials (git-ignored)
└── bg-remover/
    ├── PLAN.md                          # Milestone tracking plan
    ├── ARCHITECTURE.md                  # System architecture & design specification
    ├── process_product.py               # CLI tool & process_product_batch execution core
    ├── main.py                          # CLI runner + Cloud Functions --entry-point exports
    ├── run_local_server.py              # functions-framework receiver on port 8080
    ├── run_local_control.py             # functions-framework control-plane on port 8081
    ├── requirements.txt                 # Project dependencies
    ├── src/
    │   ├── utils/
    │   │   ├── applog.py                # One JSON Cloud Logging line per event + severity
    │   │   └── retry.py                 # Exponential backoff for rembg/Shopify HTTP
    │   ├── removers/
    │   │   ├── base.py                  # BaseBackgroundRemover interface & custom errors
    │   │   └── rembg_http.py            # RembgHostedRemover HTTP client implementation
    │   ├── shopify/
    │   │   ├── client.py                # ShopifyGraphQLClient (queries, mutations, batching)
    │   │   ├── store_host.py            # Allowlist *.myshopify.com Admin host
    │   │   └── metafields.py            # `$app.bg_state`, `$app.bg_source`, `bg_skip`
    │   ├── control/
    │   │   └── api.py                   # bg_remover_control (register / setConfig / status)
    │   ├── queue/
    │   │   ├── base.py                  # BaseTaskDispatcher, BaseLockStore, BaseDedupStore, BaseShopStore
    │   │   ├── memory_stores.py         # InMemory lock, dedup, and shop stores
    │   │   ├── firestore_stores.py      # Firestore lock, dedup, and shop stores
    │   │   ├── shop_registry.py         # get_shop_store()
    │   │   ├── local_dispatcher.py      # LocalTaskDispatcher (thread-based)
    │   │   ├── gcp_dispatcher.py        # GCPCloudTasksDispatcher (Cloud Tasks Named Tasks)
    │   │   ├── queue_control.py         # Pause/resume bg-remover-queue (rembg circuit)
    │   │   ├── circuit_probe.py         # rembg_circuit_probe; membership-usage + /rmbg canary before resume
    │   │   ├── custom_metrics.py        # Cloud Monitoring gauges/counters (fail open)
    │   │   └── worker.py                # bg_remover_worker HTTP Cloud Function entrypoint
    │   └── webhooks/
    │       ├── hmac_verifier.py         # verify_shopify_hmac() signature verifier
    │       └── receiver.py              # shopify_webhook_receiver HTTP Cloud Function
    └── tests/
        ├── test_metafields.py           # `$app.bg_state` / `$app.bg_source` / `bg_skip`
        ├── test_process_product.py      # Alt copy, keep originals, metafieldsSet pairing
        ├── test_control_api.py          # bg_remover_control auth and shop registry
        ├── test_removers.py             # Rembg API client unit tests
        ├── test_shopify.py              # Shopify GraphQL client unit tests
        ├── test_webhooks.py             # Webhook receiver, HMAC, env-first secret loading
        └── test_queue.py                # Queue dispatchers, locks, & worker unit tests
```

---

## 🧪 10. Testing & Verification Command Reference

Run the entire test suite locally across all modules:

```bash
PYTHONPATH=shopify-tools/bg-remover:shopify-tools uv run pytest shopify-tools/bg-remover/tests
```

Run local webhook receiver server:
```bash
PYTHONPATH=shopify-tools/bg-remover:shopify-tools uv run functions-framework \
  --target=shopify_webhook_receiver \
  --source=shopify-tools/bg-remover/src/webhooks/receiver.py \
  --port=8080
```

Run CLI manual product processor:
```bash
python3 shopify-tools/bg-remover/process_product.py --product-id <PRODUCT_ID>
```

---

## 🚀 11. Infrastructure Provisioning & Deployment Specification

Deployment and infrastructure management are strictly separated into a **2-Phase Lifecycle**:

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│ PHASE 1: INFRASTRUCTURE PROVISIONING (Local Machine — One-Time / Terraform)      │
│                                                                                 │
│   Your Machine ──(terraform apply)──> Provisions GCP Infrastructure:           │
│                                      ├── Required GCP APIs                       │
│                                      ├── Firestore Database (product_locks/dedup)│
│                                      ├── Cloud Tasks Queue (bg-remover-queue)   │
│                                      ├── Secret Manager Secrets                 │
│                                      └── Service Accounts & IAM Permissions     │
│                                                                                 │
│   Terraform automatically writes `GCP_PROJECT_ID` and `GCP_SA_KEY` to GitHub    │
│   Repository Secrets using the `integrations/github` Terraform provider.        │
└────────────────────────────────────────┬────────────────────────────────────────┘
                                         │
                                         │ Triggered Manually via GitHub UI
                                         ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│ PHASE 2: APPLICATION CODE DEPLOYMENT (GitHub Actions — Manual On-Demand)        │
│                                                                                 │
│   GitHub Actions ──(deploy_gcp.sh)──> Deploys Cloud Functions only:             │
│                                       ├── Worker Cloud Function (worker.py)     │
│                                       └── Receiver Cloud Function (receiver.py) │
│   The script does NOT enable APIs, create service accounts, or create queues.   │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

### A. Phase 1: Terraform Infrastructure Provisioning (`shopify-tools/bg-remover/terraform/`)

#### 1. One-Time Setup Commands
```bash
# 1. Login to GCP Application Default Credentials
gcloud auth application-default login

# 2. Set GitHub Token (Fine-grained PAT with Secrets: Read & Write permissions)
export GITHUB_TOKEN="github_pat_..."

# 3. Configure Terraform Variables
cd shopify-tools/bg-remover/terraform
cp terraform.tfvars.example terraform.tfvars
# Fill in gcp_project_id, secrets, github_owner="yzats", github_repo_name="mzbl"

# 4. Initialize and Apply
terraform init
terraform apply
```

Terraform enables these project APIs (GitHub Actions does not):
- `cloudfunctions.googleapis.com`
- `run.googleapis.com`
- `cloudbuild.googleapis.com`
- `artifactregistry.googleapis.com`
- `cloudresourcemanager.googleapis.com`
- `storage.googleapis.com`
- `cloudtasks.googleapis.com`
- `firestore.googleapis.com`
- `secretmanager.googleapis.com`
- `iam.googleapis.com`
- `cloudscheduler.googleapis.com`
- `monitoring.googleapis.com`
- `logging.googleapis.com`

#### 2. How GitHub Secrets & Service Accounts are Automated
Terraform creates a GCP Service Account (`github-deployer`) used only by GitHub Actions to deploy Cloud Functions. It generates a private JSON key (`google_service_account_key`) and writes `GCP_PROJECT_ID` and `GCP_SA_KEY` into the `yzats/mzbl` GitHub repository via `github_actions_secret`.

`github-deployer` IAM (deploy-only; APIs are enabled by Terraform, not by the deploy script):
- `roles/cloudfunctions.developer`
- `roles/run.admin`
- `roles/cloudbuild.builds.builder`
- `roles/artifactregistry.writer`
- `roles/storage.objectAdmin`
- `roles/logging.logWriter`
- `roles/iam.serviceAccountUser`
- `roles/cloudtasks.admin` (describe/verify the queue)
- `roles/cloudscheduler.admin` (upsert `rembg-circuit-probe` job)
- `roles/secretmanager.viewer` / `roles/secretmanager.secretAccessor` (bind Secret Manager secrets to functions)

Runtime service account `bg-remover-sa` IAM:
- `roles/datastore.user`
- `roles/cloudtasks.enqueuer`
- `roles/cloudtasks.taskRunner`
- `roles/cloudtasks.queueAdmin` (pause/resume `bg-remover-queue` on rembg circuit open/close)
- `roles/monitoring.metricWriter` (custom gauges/counters from probe and worker)
- `roles/iam.serviceAccountUser` **on itself** (`iam.serviceAccounts.actAs`) so `create_task` can attach an OIDC token for `bg-remover-sa`
- Secret accessor on `SHOPIFY_WEBHOOK_SECRET`, `SHOPIFY_ADMIN_API_ACCESS_TOKEN`, `REMBG_API_KEY`

The Cloud Tasks service agent (`service-{PROJECT_NUMBER}@gcp-sa-cloudtasks.iam.gserviceaccount.com`) gets `roles/iam.serviceAccountTokenCreator` on `bg-remover-sa` so OIDC-authenticated worker invocations succeed.

The Cloud Scheduler service agent is created with `google_project_service_identity` (`service-{PROJECT_NUMBER}@gcp-sa-cloudscheduler.iam.gserviceaccount.com`; enabling the API alone does not always create it) and gets `roles/iam.serviceAccountUser` on `bg-remover-sa` so the 5-minute probe can mint an OIDC token.

Terraform also creates log-based metric `bg_remover_circuit_open` (`[CIRCUIT OPEN]` / `[CIRCUIT STILL OPEN]`). When `alert_sms` and/or `alert_email` is set, a **metric** alert fires on open and closes after ~5 minutes with no matching logs (queue resumed; probe no longer logs STILL OPEN). SMS uses E.164 (`alert_sms = "+1…"`); GCP sends a verification text. Manual resume: `gcloud tasks queues resume bg-remover-queue --location=us-central1`.

#### Cloud Monitoring dashboard (`terraform/dashboard.tf`)

After `terraform apply`, open **Monitoring → Dashboards → BG Remover** (or `terraform output bg_remover_dashboard_id`). Tiles are **time series** (dashboard time picker: 1h / 6h / 1d / 1w). Custom log metrics are typically retained ~6 weeks.

**Hybrid metrics:** platform Cloud Run / Cloud Tasks series first; **log-based DELTA counters** for sparse print tags already used by the circuit alert; **custom Monitoring metrics** (`src/queue/custom_metrics.py`, fail-open, no OTel collector) only for values that are not “a log line appeared.” Circuit SMS/email stays log-based on `bg_remover_circuit_open`. Rembg vs Shopify latency histograms are not instrumented (worker p95 is enough).

| Tile | Source | How to read |
| :--- | :--- | :--- |
| Circuit state | `custom.googleapis.com/bg_remover/circuit_open` | **1** = queue paused, **0** = running. Written on pause/resume and each probe. SMS still uses the log-based `bg_remover_circuit_open` events. |
| Queue depth | `cloudtasks.googleapis.com/queue/depth` | Rises while paused or the worker is slow; receiver can still enqueue. |
| Task attempts | `cloudtasks.googleapis.com/queue/task_attempt_count` | Worker invocations / retries (Shopify 503 vs rembg pause). |
| Probe HTTP | Cloud Run `request_count` on `rembg-circuit-probe` | 200 = credits OK and (queue running, or paused canary succeeded). 503 = membership-usage failed, no credits, canary failed, or canary hold. |
| Worker HTTP | Cloud Run `request_count` on `bg-remover-worker` | 200 success/skip; 400 poison; 503 circuit or Shopify retry. |
| Receiver HTTP | Cloud Run `request_count` on `shopify-webhook-receiver` | 401 HMAC; 200 includes success, ignore, and dedup. |
| Enqueue vs dedup | `bg_remover_task_enqueued` / `bg_remover_task_deduped` | `[TASK ENQUEUED]` vs `[TASK DEDUPED]` / `[200 DEDUPED]`. |
| Webhook-id vs lock skip | `bg_remover_webhook_id_skip` / `bg_remover_lock_skip` | Layer-1 Shopify retries vs Layer-3 product lock. |
| Worker latency p50/p95 | Cloud Run `request_latencies` | Watch vs the 120s worker timeout. |
| Rembg credits remaining | `custom.googleapis.com/bg_remover/rembg_credits` and `.../rembg_prepaid_credits` | Gauges written by `rembg_circuit_probe` from membership-usage JSON (including zeros). |
| Images processed | `custom.googleapis.com/bg_remover/images_processed` | Worker GAUGE of `processed_count` per successful batch (custom metrics cannot be DELTA; chart uses ALIGN_SUM). |
| Logs: circuit, warnings, and errors | Logs panel (`logsPanel`) | WARNING+ plus `[CIRCUIT]` / `[FAULT]` on worker, probe, and receiver. Follows the dashboard time picker. |
| Logs: bg-remover-worker | Logs panel | App lines only (request access logs excluded). |
| Logs: rembg-circuit-probe | Logs panel | App lines only (request access logs excluded). |

#### 3. Token Refresh / Expiration Behavior
- The `GITHUB_TOKEN` PAT is **ONLY used locally when running `terraform apply`**.
- **Existing GitHub Actions workflows and Cloud Functions are NOT affected when the GitHub PAT expires.**
- When modifying infrastructure in the future (e.g. changing Firestore TTLs or Cloud Tasks rate limits), regenerate the GitHub PAT, run `export GITHUB_TOKEN="..."`, and execute `terraform apply`.

---

### B. Phase 2: GitHub Actions Workflows (`.github/workflows/`)

To protect this monorepo, testing is automated while deployment is strictly **manual on-demand**:

#### 1. Continuous Integration Unit Testing (`.github/workflows/shopify-bg-remover-test.yml`)
- **Trigger:** Automatic on `push` or `pull_request` to any branch **only when files inside `shopify-tools/bg-remover/**` or workflow files change**.
- **Action:** Runs `pytest shopify-tools/bg-remover/tests` on Python 3.11.

#### 2. Manual Production Deployment (`.github/workflows/shopify-bg-remover-deploy.yml`)
- **Trigger:** Strictly **manual** (`workflow_dispatch`).
- **How to Trigger:**
  1. Go to GitHub $\rightarrow$ **Actions** tab.
  2. Select **Deploy Shopify Background Remover to GCP** on the left.
  3. Click **Run workflow** $\rightarrow$ select branch `main` $\rightarrow$ click **Run workflow**.
- **Action:** Authenticates via `GCP_SA_KEY` secret and executes `shopify-tools/bg-remover/deploy_gcp.sh`. That script verifies Terraform-managed resources exist, then deploys `bg_remover_worker` and `shopify_webhook_receiver` (entrypoints re-exported from `bg-remover/main.py`). It prints `Webhook Receiver Endpoint` for Shopify Admin. It does **not** call `gcloud services enable`.

---

## 🔄 12. Synchronization & Maintenance Instructions

> **ATTENTION AGENT / DEVELOPER:**
> Whenever you modify codebase files in `shopify-tools/bg-remover/`, verify whether your changes impact:
> 1. Function / method signatures in interfaces or clients.
> 2. New parameters or environment variables added to `config.py`.
> 3. Additional idempotency layers, storage backends, or queue behaviors.
> 4. Directory structures or test files.
>
> **Action:** Update the corresponding sections in this `ARCHITECTURE.md` file immediately as part of your task.
