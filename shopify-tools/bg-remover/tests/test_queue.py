import time
from unittest.mock import MagicMock
import pytest

from src.queue.memory_stores import InMemoryLockStore, InMemoryDedupStore
from src.queue.local_dispatcher import LocalTaskDispatcher
from src.queue.gcp_dispatcher import GCPCloudTasksDispatcher, named_task_id
from src.queue.firestore_stores import GCPFirestoreLockStore, firestore_document_id
from src.removers import RembgUnavailableError, NonRetryableBackgroundRemoverError
from src.shopify import RetryableShopifyError
from src.queue.circuit_probe import probe_rembg_and_resume
from src.queue.worker import execute_background_removal_job


def test_in_memory_lock_store():
    lock_store = InMemoryLockStore()
    lock_key = "product:123"

    assert lock_store.acquire_lock(lock_key, ttl_seconds=10) is True
    assert lock_store.acquire_lock(lock_key, ttl_seconds=10) is False  # Conflict

    lock_store.release_lock(lock_key)
    assert lock_store.acquire_lock(lock_key, ttl_seconds=10) is True


def test_in_memory_dedup_store():
    dedup = InMemoryDedupStore()
    key = "webhook:evt123"

    assert dedup.is_duplicate(key, ttl_seconds=10) is False  # First time
    assert dedup.is_duplicate(key, ttl_seconds=10) is True   # Duplicate


def test_local_task_dispatcher(mocker):
    mock_worker = MagicMock()
    dispatcher = LocalTaskDispatcher(worker_func=mock_worker)

    task_id = dispatcher.dispatch_product_task(
        product_id="gid://shopify/Product/12345",
        shop_domain="test.myshopify.com",
    )

    assert "local-task-12345" in task_id.task_id
    assert task_id.outcome == "enqueued"
    time.sleep(0.1)  # Allow background thread execution
    mock_worker.assert_called_once()
    
    args, _ = mock_worker.call_args
    assert args[0]["product_id"] == "gid://shopify/Product/12345"


def test_gcp_cloud_tasks_dispatcher_named_task():
    dispatcher = GCPCloudTasksDispatcher(
        project_id="my-gcp-project",
        location="us-central1",
        queue_name="bg-remover-queue",
        worker_target_url="https://us-central1-my-gcp-project.cloudfunctions.net/bg_remover_worker",
    )
    dispatcher.client = None

    result = dispatcher.dispatch_product_task(
        product_id="gid://shopify/Product/9999",
        shop_domain="test.myshopify.com",
        metadata={"updated_at": "2026-08-20T06:00:00-04:00"},
    )

    expected_id = named_task_id(
        "gid://shopify/Product/9999",
        {"updated_at": "2026-08-20T06:00:00-04:00"},
    )
    assert expected_id in result.task_id
    assert result.outcome == "simulated"
    assert "task-product-9999-" in result.task_id


def test_gcp_cloud_tasks_dispatcher_logs_deduped_already_exists():
    dispatcher = GCPCloudTasksDispatcher(
        project_id="my-gcp-project",
        location="us-central1",
        queue_name="bg-remover-queue",
        worker_target_url="https://example.com/worker",
    )
    mock_client = MagicMock()
    mock_client.create_task.side_effect = Exception("409 ALREADY_EXISTS: task exists")
    dispatcher.client = mock_client
    dispatcher.queue_path = "projects/my-gcp-project/locations/us-central1/queues/bg-remover-queue"

    result = dispatcher.dispatch_product_task(
        product_id="gid://shopify/Product/9999",
        shop_domain="test.myshopify.com",
        metadata={"updated_at": "2026-08-20T06:00:00Z"},
    )

    assert result.outcome == "deduplicated"
    assert "task-product-9999-" in result.task_id


def test_named_task_id_changes_when_product_updated_at_changes():
    product_id = "gid://shopify/Product/9999"
    first = named_task_id(product_id, {"updated_at": "2026-08-20T06:00:00Z"})
    second = named_task_id(product_id, {"updated_at": "2026-08-20T07:00:00Z"})
    retry = named_task_id(product_id, {"updated_at": "2026-08-20T06:00:00Z"})

    assert first != second
    assert first == retry
    assert first.startswith("task-product-9999-")


def test_firestore_document_id_is_path_safe():
    lock_key = "lock:product:gid://shopify/Product/788032119674292922"
    doc_id = firestore_document_id(lock_key)
    assert "/" not in doc_id
    assert ":" not in doc_id
    assert len(doc_id) == 64
    assert firestore_document_id(lock_key) == doc_id


def test_firestore_lock_store_uses_hashed_document_id():
    store = GCPFirestoreLockStore.__new__(GCPFirestoreLockStore)
    store.collection_name = "product_locks"
    store.project_id = None
    mock_db = MagicMock()
    mock_doc = MagicMock()
    mock_doc.exists = False
    mock_db.collection.return_value.document.return_value.get.return_value = mock_doc
    store.db = mock_db

    lock_key = "lock:product:gid://shopify/Product/123"
    assert store.acquire_lock(lock_key, ttl_seconds=10) is True

    called_id = mock_db.collection.return_value.document.call_args[0][0]
    assert called_id == firestore_document_id(lock_key)
    assert "/" not in called_id


def test_firestore_lock_store_init_without_credentials():
    store = GCPFirestoreLockStore(project_id="ci-no-credentials")
    assert store.collection_name == "product_locks"


def test_worker_execute_no_images(mocker):
    mock_client = MagicMock()
    mock_client.get_unprocessed_images.return_value = []
    mocker.patch("src.queue.worker.ShopifyGraphQLClient", return_value=mock_client)
    mocker.patch("src.queue.worker.RembgHostedRemover")
    mocker.patch("src.queue.worker.SHOPIFY_STORE_URL", "test.myshopify.com")
    mocker.patch("src.queue.worker.SHOPIFY_ADMIN_API_ACCESS_TOKEN", "test-token")

    payload = {"product_id": "gid://shopify/Product/12345", "shop_domain": "test.myshopify.com"}
    res_dict, status_code = execute_background_removal_job(payload)

    assert status_code == 200
    assert res_dict["status"] == "success"
    assert res_dict["processed_count"] == 0


def test_worker_pauses_queue_on_rembg_unavailable(mocker):
    mocker.patch("src.queue.worker.SHOPIFY_STORE_URL", "test.myshopify.com")
    mocker.patch("src.queue.worker.SHOPIFY_ADMIN_API_ACCESS_TOKEN", "test-token")
    mock_client = MagicMock()
    mock_client.get_unprocessed_images.return_value = [
        {"media_id": "gid://shopify/MediaImage/1", "url": "https://cdn.example/x.jpg"}
    ]
    mocker.patch("src.queue.worker.ShopifyGraphQLClient", return_value=mock_client)
    mocker.patch("src.queue.worker.RembgHostedRemover")
    pause = mocker.patch("src.queue.worker.pause_product_queue", return_value=True)
    mocker.patch(
        "process_product.process_product_batch",
        side_effect=RembgUnavailableError("HTTP 401"),
    )

    payload = {"product_id": "gid://shopify/Product/12345", "shop_domain": "test.myshopify.com"}
    res_dict, status_code = execute_background_removal_job(payload)

    assert status_code == 503
    assert res_dict["circuit"] == "open"
    pause.assert_called_once()


def test_worker_does_not_pause_on_bad_image(mocker):
    mocker.patch("src.queue.worker.SHOPIFY_STORE_URL", "test.myshopify.com")
    mocker.patch("src.queue.worker.SHOPIFY_ADMIN_API_ACCESS_TOKEN", "test-token")
    mock_client = MagicMock()
    mock_client.get_unprocessed_images.return_value = [
        {"media_id": "gid://shopify/MediaImage/1", "url": "https://cdn.example/x.jpg"}
    ]
    mocker.patch("src.queue.worker.ShopifyGraphQLClient", return_value=mock_client)
    mocker.patch("src.queue.worker.RembgHostedRemover")
    pause = mocker.patch("src.queue.worker.pause_product_queue", return_value=True)
    mocker.patch(
        "process_product.process_product_batch",
        side_effect=NonRetryableBackgroundRemoverError("HTTP 400"),
    )

    payload = {"product_id": "gid://shopify/Product/12345", "shop_domain": "test.myshopify.com"}
    res_dict, status_code = execute_background_removal_job(payload)

    assert status_code == 400
    pause.assert_not_called()


def test_worker_does_not_pause_on_shopify_rate_limit(mocker):
    mocker.patch("src.queue.worker.SHOPIFY_STORE_URL", "test.myshopify.com")
    mocker.patch("src.queue.worker.SHOPIFY_ADMIN_API_ACCESS_TOKEN", "test-token")
    mock_client = MagicMock()
    mock_client.get_unprocessed_images.side_effect = RetryableShopifyError("HTTP 429")
    mocker.patch("src.queue.worker.ShopifyGraphQLClient", return_value=mock_client)
    mocker.patch("src.queue.worker.RembgHostedRemover")
    pause = mocker.patch("src.queue.worker.pause_product_queue", return_value=True)

    payload = {"product_id": "gid://shopify/Product/12345", "shop_domain": "test.myshopify.com"}
    res_dict, status_code = execute_background_removal_job(payload)

    assert status_code == 503
    assert "circuit" not in res_dict
    pause.assert_not_called()


def test_probe_resumes_queue_when_rembg_ok(mocker):
    mocker.patch(
        "src.queue.circuit_probe.RembgHostedRemover"
    ).return_value.check_account_ready.return_value = {
        "credits": 12,
        "prepaidCredits": 0,
    }
    resume = mocker.patch("src.queue.circuit_probe.resume_product_queue", return_value=True)

    result = probe_rembg_and_resume()
    assert result["status"] == "closed"
    assert result["resumed"] is True
    assert result["credits"] == 12
    resume.assert_called_once()


def test_probe_keeps_circuit_open_when_rembg_fails(mocker):
    mocker.patch(
        "src.queue.circuit_probe.RembgHostedRemover"
    ).return_value.check_account_ready.side_effect = RembgUnavailableError(
        "Rembg account has no usable credits (credits=0, prepaidCredits=0)"
    )
    resume = mocker.patch("src.queue.circuit_probe.resume_product_queue")
    pause = mocker.patch("src.queue.circuit_probe.pause_product_queue", return_value=False)
    mocker.patch("src.queue.circuit_probe.is_product_queue_paused", return_value=True)

    result = probe_rembg_and_resume()
    assert result["status"] == "open"
    resume.assert_not_called()
    pause.assert_called_once()
