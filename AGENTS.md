# AGENT INSTRUCTIONS — SHOPIFY BACKGROUND REMOVER

> **ATTENTION AGENT / DEVELOPER:**
> This repository contains the **Shopify Background Remover** tool under `shopify-tools/bg-remover/`.
> Before making any changes or adding features, you **MUST** read and adhere to the project specifications documented in [`shopify-tools/bg-remover/ARCHITECTURE.md`](../shopify-tools/bg-remover/ARCHITECTURE.md).

---

## 📌 Core Architectural Principles

1. **Architecture Specification File:**
   - The master architecture document is located at: `shopify-tools/bg-remover/ARCHITECTURE.md`.
   - **MANDATORY RULE:** Whenever you modify function signatures, data models, error handling, queue parameters, infrastructure configs, or file structures in `shopify-tools/bg-remover/`, you **MUST** update `ARCHITECTURE.md` in the exact same commit/change set.

2. **Layered Anti-Race & Idempotency Strategy:**
   - **Layer 1 (Receiver):** `X-Shopify-Webhook-Id` de-duplication in `InMemoryDedupStore` / `GCPFirestoreDedupStore`.
   - **Layer 2 (Queue):** Named task `task-product-{id}-{pid_hash}-{update_hash}` in GCP Cloud Tasks (coalesces the same Shopify `updated_at`; does not block later edits).
   - **Layer 3 (Worker Lock):** Distributed product processing lock (`ProductLock(product_id)`) in `InMemoryLockStore` / `GCPFirestoreLockStore`.
   - **Layer 4 (Media Level):** Alt text inspection (`alt="hide"` / `alt="bg-removed"`) skips processed images.

3. **Per-Product GraphQL Batching:**
   - Processing operations are batched per product using `process_product_batch()` in `process_product.py`.
   - Executes only **3 GraphQL calls TOTAL per product run**: `productCreateMediaBatch`, `productReorderMedia`, and `productUpdateMediaBatch`.

4. **Error Classification & Retries:**
   - **Retryable Errors** (503, 429 rate limit, timeouts) raise `RetryableBackgroundRemoverError` / `RetryableShopifyError` $\rightarrow$ returns **HTTP 503** to trigger Cloud Tasks retry backoffs.
   - **Non-Retryable Errors** (400 bad payload, corrupted file, product 404) raise `NonRetryableBackgroundRemoverError` / `NonRetryableShopifyError` $\rightarrow$ returns **HTTP 400** to drop task cleanly without infinite queue loops.

---

## 🧪 Testing Requirement

Always verify that all 28 unit tests pass after any change:

```bash
PYTHONPATH=shopify-tools/bg-remover:shopify-tools uv run pytest shopify-tools/bg-remover/tests
```
