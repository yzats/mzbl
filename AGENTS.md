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
   - **Layer 2 (Queue):** Named task `task-product-{shop_hash}-{clean_pid}-{pid_hash}-{update_hash}` in GCP Cloud Tasks (coalesces the same shop + Shopify `updated_at`; does not block later edits).
   - **Layer 3 (Worker Lock):** Distributed product processing lock (`lock:product:{shop_domain}:{product_id}`) in `InMemoryLockStore` / `GCPFirestoreLockStore`.
   - **Layer 4 (Media Level):** MediaImage `$app.bg_state` (`source` / `result` skip; empty = process). Product tag `bg_skip` skips the product. Alt is copied, not used as a flag.

3. **Per-Product GraphQL Batching:**
   - Processing operations are batched per product using `process_product_batch()` in `process_product.py`.
   - Mutations per product run: `productCreateMedia`, `productReorderMedia`, and `metafieldsSet` (`$app.bg_state`, `$app.bg_source`). Originals are always kept.

4. **Error Classification & Retries:**
   - **Rembg unavailable** (401/402/403, monthly-limit 429 text, or HTTP 200 whose output fits the free API **460×460** box while the source longest side is **> 468**) raises `RembgUnavailableError` $\rightarrow$ pause `bg-remover-queue`, worker **HTTP 503**. A 2000→1000 shrink is **not** unavailable. Probe `rembg_circuit_probe` every 5 minutes writes credit gauges from `GET /api/membership-usage`. If the queue is paused and `credits > 0` or `prepaidCredits > 0`, it runs one `/rmbg` canary (32×32 PNG, no in-process retry) before resume. Consecutive canary failures hold the next canary 5/15/30/60 minutes (`circuit_state/rembg`). Log `[CIRCUIT OPEN]` / `[CIRCUIT STILL OPEN]`; metric alert SMS/email on open and close (no 24h nag).
   - **Retryable rembg** (429 short-term rate limit, 5xx, timeout) raises `RetryableBackgroundRemoverError` $\rightarrow$ in-process retries (honor rembg `Retry-After` on rate-limit 429; else 1/2/4s). Rate-limit 429 then **HTTP 503** without pausing the queue. 5xx/timeout still pause + **HTTP 503**. HTTP 429 whose `error` / `details[].message` contains `monthly limit` or `purchasing` is `RembgUnavailableError` instead (no extra membership-usage call).
   - **Retryable Shopify** raises `RetryableShopifyError` $\rightarrow$ **HTTP 503** without pausing the rembg queue.
   - **Non-Retryable Errors** (400 bad payload, corrupted file, product 404) raise `NonRetryableBackgroundRemoverError` / `NonRetryableShopifyError` $\rightarrow$ **HTTP 400**, queue stays running.

---

## 🧪 Testing Requirement

Always verify that the unit tests pass after any change:

```bash
PYTHONPATH=shopify-tools/bg-remover:shopify-tools uv run pytest shopify-tools/bg-remover/tests
```
