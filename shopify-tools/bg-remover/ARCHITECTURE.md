# Shopify Background Remover — System Architecture & Design Specification

> **IMPORTANT MAINTENANCE RULE FOR AGENTS & DEVELOPERS:**
> This document is the single source of truth for the Shopify Background Remover architecture, design decisions, data models, and component contracts.
> **Mandatory Rule:** Whenever any implementation detail, method signature, data structure, or infrastructure component is modified, added, or removed in the codebase, this document **MUST** be updated immediately in the same commit/change set to remain 100% in sync with the codebase.

---

## 📌 1. Executive Summary & Objectives

The **Shopify Background Remover** is a pluggable, serverless, rate-limited, and idempotent pipeline that automatically removes backgrounds from Shopify product images when products are created or updated, replacing them with clean PNGs (defaulting to a solid white background `#ffffff`).

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
                               │  1. Acquire ProductLock(product_id)                     │
                               │  2. Query get_unprocessed_images() via GraphQL          │
                               │  3. Download original CDN image bytes                   │
                               │  4. Send to RembgHostedRemover API (default sizing)     │
                               │  5. Upload staged file (stagedUploadsCreate)            │
                               │  6. Batch GraphQL: productCreateMedia                   │
                               │  7. Batch GraphQL: productReorderMedia                  │
                               │  8. Batch GraphQL: productUpdateMedia (alt="hide")      │
                               │  9. Release ProductLock(product_id)                     │
                               └─────────────────────────────────────────────────────────┘
```

---

## 🛡️ 3. 4-Layer Idempotency & Anti-Race Architecture

Because background removal takes 3–5 seconds per image and Shopify emits webhooks on every product/media change, we employ a **4-Layer Idempotency & Concurrency Defense**:

```
Layer 1: Webhook ID Guard (DedupStore)
  └── Drop retransmitted webhooks using X-Shopify-Webhook-Id header (5 min TTL).

Layer 2: Named Task Queue Guard (GCP Cloud Tasks / Local Task ID)
  └── Task Name = task-product-{product_id_hash}. Drops duplicate enqueued tasks per product.

Layer 3: Distributed Worker Lock (ProductLock)
  └── Acquires 2-minute lock per product_id before starting. Concurrent runs exit immediately.

Layer 4: Media-Level Alt Text Guard (get_unprocessed_images)
  └── Checks image alt text and CDN URL. Skips any image tagged 'hide' or 'bg-removed'.
```

### Layer Details:
1. **Layer 1 (Receiver Level):** Tracks `X-Shopify-Webhook-Id` headers. If Shopify re-sends an identical webhook event within 5 minutes, the receiver logs `[200 SKIPPED]` and returns `status: ignored`.
2. **Layer 2 (Queue Level):** In GCP, task names are formatted as `projects/.../tasks/task-product-{clean_pid}-{hash}`. Cloud Tasks enforces strict task name uniqueness and drops duplicate task creations.
3. **Layer 3 (Worker Level):** A distributed lock `lock:product:{product_id}` is acquired before worker processing begins. If another worker thread is actively processing the same product, the new worker logs `Product lock active` and terminates cleanly (HTTP 200).
4. **Layer 4 (Media State Level):** The worker queries Shopify GraphQL for live product media and skips any image where `alt` contains `hide` or `bg-removed`, or where the CDN URL contains `bg-removed`. When all images are tagged, the worker exits in `<100ms`.

---

## 🧩 4. Component Contracts & Interfaces

All major subsystems use abstract interfaces to support provider swapping (e.g. Local vs GCP vs AWS).

### A. Background Remover Interface (`src/removers/`)
- **`BaseBackgroundRemover` (`base.py`)**:
  ```python
  def remove_background(self, image_data: bytes, bg_color: Optional[str] = "#ffffff") -> bytes
  ```
- **`RembgHostedRemover` (`rembg_http.py`)**:
  - Sends raw image bytes to rembg API (`https://api.rembg.com/rmbg`).
  - **No `height` parameter is sent** — lets rembg perform default image processing and sizing.
  - Formats payloads with `format="png"` and `bg_color="#ffffff"`.
  - Classifies errors into `RetryableBackgroundRemoverError` (503, 429, timeouts) vs `NonRetryableBackgroundRemoverError` (400, 401).

### B. Task Dispatcher Interface (`src/queue/`)
- **`BaseTaskDispatcher` (`base.py`)**:
  ```python
  def dispatch_product_task(self, product_id: str, shop_domain: str, topic: str, metadata: Optional[dict]) -> str
  ```
- **`LocalTaskDispatcher` (`local_dispatcher.py`)**: Dispatches tasks in background Python daemon threads for local development.
- **`GCPCloudTasksDispatcher` (`gcp_dispatcher.py`)**: Constructs GCP Cloud Tasks HTTP POST requests using Named Tasks for queue deduplication.

### C. Lock & Deduplication Stores (`src/queue/`)
- **`BaseLockStore` (`base.py`)** & **`BaseDedupStore` (`base.py`)**: Abstract contracts for lock acquisition and key deduplication.
- **`InMemoryLockStore` & `InMemoryDedupStore` (`memory_stores.py`)**: In-memory dict-based stores with TTL expiration for local development.
- **`GCPFirestoreLockStore` & `GCPFirestoreDedupStore` (`firestore_stores.py`)**: GCP Cloud Firestore implementations (`product_locks` and `webhook_dedup` collections) with TTL policy support. Document IDs are `firestore_document_id(key)` (SHA-256 hex) because Shopify GIDs contain `/`. Client construction catches missing credentials / import errors so unit tests and local runs without ADC do not crash.

---

## ⚡ 5. Resiliency, Error Classification & Retry Strategies

To ensure zero lost tasks and prevent infinite retries on permanent failures, both external provider interfaces (`rembg` and `Shopify Admin API`) implement strict **Error Classification**, **Exponential Backoff Retries**, and **HTTP Status Code Mapping**.

---

### A. Background Remover Interface (`src/removers/`) Error Handling

The background remover client (`RembgHostedRemover`) categorizes external API responses into two custom exception hierarchies defined in `src/removers/base.py`:

```
                    ┌───────────────────────────────┐
                    │    BackgroundRemoverError     │
                    │        (Base Exception)       │
                    └──────────────┬────────────────┘
                                   │
            ┌──────────────────────┴──────────────────────┐
            ▼                                             ▼
┌───────────────────────────────────────┐   ┌───────────────────────────────────────────┐
│   RetryableBackgroundRemoverError     │   │   NonRetryableBackgroundRemoverError      │
│ (Transient errors: 429, 500, 502-504) │   │  (Fatal client errors: 400, 401, corrupted)│
└───────────────────────────────────────┘   └───────────────────────────────────────────┘
```

#### Status Code & Exception Mapping (`rembg_http.py`):
| HTTP Status / Condition | Exception Raised | Worker Response | Retry Strategy |
| :--- | :--- | :--- | :--- |
| **HTTP 200 OK** | None (Returns image bytes) | HTTP 200 Success | None |
| **HTTP 429 (Rate Limit)** | `RetryableBackgroundRemoverError` | **HTTP 503** | Exponential backoff (1s, 2s, 4s...) via `@retry_with_exponential_backoff`. If max retries exhausted, returns HTTP 503 to Cloud Tasks to schedule queue-level retry. |
| **HTTP 500, 502, 503, 504** | `RetryableBackgroundRemoverError` | **HTTP 503** | Retried via exponential backoff decorator. |
| **Network Timeout / Connection Error** | `RetryableBackgroundRemoverError` | **HTTP 503** | Retried via exponential backoff decorator. |
| **HTTP 400 (Bad Request / Corrupted)** | `NonRetryableBackgroundRemoverError` | **HTTP 400** | **NO RETRY.** Logged as fatal error and exited cleanly to drop task from queue. |
| **HTTP 401, 403 (Invalid API Key)** | `NonRetryableBackgroundRemoverError` | **HTTP 400** | **NO RETRY.** Exits cleanly to avoid queue hammer. |
| **Empty Input / Empty Response Bytes** | `NonRetryableBackgroundRemoverError` | **HTTP 400** | **NO RETRY.** Exits cleanly. |

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
- **Queue Level Escalation:** If all $N$ in-memory retries fail, the exception bubbles up to `worker.py`. `worker.py` maps `RetryableBackgroundRemoverError` or `RetryableShopifyError` to **HTTP 503**, causing GCP Cloud Tasks to reschedule the task according to its queue-level backoff rules.

---

## ⚡ 6. GraphQL Batching & Shopify API Optimizations

To minimize API costs and webhook cascades, processing is **batched per product**:

```text
1. Fetch live product media via GraphQL (get_unprocessed_images)
2. For each unprocessed image:
   ├── Download raw image bytes from Shopify CDN
   ├── Send bytes to rembg API
   └── Upload PNG via stagedUploadsCreate & upload_file_to_staged_target
3. Execute 3 Batched GraphQL Operations TOTAL for the entire product:
   ├── productCreateMediaBatch: Attaches all new staged PNGs with alt="bg-removed"
   ├── productReorderMedia: Moves all new media items to their original position indices
   └── productUpdateMediaBatch: Appends 'hide' to original media alt text (or deletes them)
```

### Key Benefits:
- **Reduces GraphQL API Calls:** Drops calls from $3 \times N$ images down to **3 calls total per product**.
- **Coalesces Webhooks:** Making 3 rapid GraphQL calls in 1 second causes Shopify to coalesce follow-up webhooks, preventing webhook storms.

---

## ☁️ 8. Production GCP Infrastructure Specification

The production deployment runs on a 100% serverless, zero-standing-cost Google Cloud Platform (GCP) architecture:

```
[Shopify Webhook] ──(HTTPS)──> [Receiver Cloud Function v2]
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
                                         ├─ Acquire Lock ──> [GCP Cloud Firestore] (product_locks)
                                         ├─ Image Rembg ───> [Rembg Hosted API]
                                         └─ GraphQL Admin ─> [Shopify CDN & API]
```

---

### A. GCP Cloud Functions (v2 Serverless Runtime)

| Function Name | Trigger Type | Runtime | Memory / CPU | Concurrency | Timeout | IAM Roles & Secret Access |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `shopify_webhook_receiver` | HTTP POST | Python 3.11/3.12 | 256 MB / 0.17 vCPU | 80 | 10 seconds | `roles/cloudtasks.enqueuer`, access to `SHOPIFY_WEBHOOK_SECRET` |
| `bg_remover_worker` | HTTP POST | Python 3.11/3.12 | 512 MB / 0.5 vCPU | 10 | 120 seconds | `roles/datastore.user`, `roles/cloudtasks.taskRunner`, access to `SHOPIFY_ADMIN_API_ACCESS_TOKEN`, `REMBG_API_KEY` |

---

### B. GCP Cloud Tasks Queue (`bg-remover-queue`)

- **Purpose:** Acts as a rate-limiting buffer, retry scheduler, and deduplication layer between incoming webhooks and background removal workers.
- **Deduplication Strategy:** Enqueued using Named Tasks: `task-product-{clean_pid}-{hash}`. Cloud Tasks enforces strict task-name uniqueness, automatically dropping duplicate task enqueue attempts while a task for that product is active/queued.
- **Queue Configuration Specification:**
  ```yaml
  name: projects/{PROJECT_ID}/locations/us-central1/queues/bg-remover-queue
  rateLimits:
    maxDispatchesPerSecond: 5.0
    maxBurstSize: 10
    maxConcurrentDispatches: 10
  retryConfig:
    maxAttempts: 5
    minBackoff: 5s
    maxBackoff: 300s
    maxDoublings: 3
  ```
- **Dead-Letter Queue (DLQ):** After 5 failed attempts (returning HTTP 503), tasks are routed to `bg-remover-dlq` topic for alerting and manual inspection.

---

### C. GCP Cloud Firestore (Native Serverless Storage)

- **Database Mode:** Native Mode.
- **Collections Specification:**
  1. **`webhook_dedup` Collection:**
     - **Document ID:** SHA-256 hex of the `X-Shopify-Webhook-Id` value (Firestore IDs cannot contain `/`).
     - **Fields:** `key` (original webhook id string), `created_at` (number, unix seconds), `expires_at` (number, unix seconds, set to `now + 300s`).
     - **TTL Policy:** Enabled on `expires_at` field to auto-delete expired webhook records.
  2. **`product_locks` Collection:**
     - **Document ID:** SHA-256 hex of `lock:product:{product_id}` (product_id is a Shopify GID containing `/`, which is illegal in a raw document name).
     - **Fields:** `lock_key` (original lock string), `created_at` (number, unix seconds), `expires_at` (number, unix seconds, set to `now + 120s`).
     - **TTL Policy:** Enabled on `expires_at` field for automatic lock auto-release on crashed workers.

---

### D. GCP Secret Manager & IAM Security

- **Secrets Managed:**
  - `SHOPIFY_WEBHOOK_SECRET`
  - `SHOPIFY_CLIENT_SECRET`
  - `SHOPIFY_ADMIN_API_ACCESS_TOKEN`
  - `REMBG_API_KEY`
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
    ├── requirements.txt                 # Project dependencies
    ├── src/
    │   ├── removers/
    │   │   ├── base.py                  # BaseBackgroundRemover interface & custom errors
    │   │   └── rembg_http.py            # RembgHostedRemover HTTP client implementation
    │   ├── shopify/
    │   │   ├── client.py                # ShopifyGraphQLClient (queries, mutations, batching)
    │   │   └── alt_helpers.py           # Alt text parsing & tag manipulation helpers
    │   ├── queue/
    │   │   ├── base.py                  # BaseTaskDispatcher, BaseLockStore, BaseDedupStore
    │   │   ├── memory_stores.py         # InMemoryLockStore & InMemoryDedupStore
    │   │   ├── firestore_stores.py      # GCPFirestoreLockStore & GCPFirestoreDedupStore
    │   │   ├── local_dispatcher.py      # LocalTaskDispatcher (thread-based)
    │   │   ├── gcp_dispatcher.py        # GCPCloudTasksDispatcher (Cloud Tasks Named Tasks)
    │   │   └── worker.py                # bg_remover_worker HTTP Cloud Function entrypoint
    │   └── webhooks/
    │       ├── hmac_verifier.py         # verify_shopify_hmac() signature verifier
    │       └── receiver.py              # shopify_webhook_receiver HTTP Cloud Function
    └── tests/
        ├── test_alt_helpers.py          # Alt tag parsing unit tests
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
- `roles/secretmanager.viewer` / `roles/secretmanager.secretAccessor` (bind Secret Manager secrets to functions)

Runtime service account `bg-remover-sa` IAM:
- `roles/datastore.user`
- `roles/cloudtasks.enqueuer`
- `roles/cloudtasks.taskRunner`
- `roles/iam.serviceAccountUser` **on itself** (`iam.serviceAccounts.actAs`) so `create_task` can attach an OIDC token for `bg-remover-sa`
- Secret accessor on `SHOPIFY_WEBHOOK_SECRET`, `SHOPIFY_ADMIN_API_ACCESS_TOKEN`, `REMBG_API_KEY`

The Cloud Tasks service agent (`service-{PROJECT_NUMBER}@gcp-sa-cloudtasks.iam.gserviceaccount.com`) gets `roles/iam.serviceAccountTokenCreator` on `bg-remover-sa` so OIDC-authenticated worker invocations succeed.

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
