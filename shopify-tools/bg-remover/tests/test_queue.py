import time
from unittest.mock import MagicMock
import pytest

from src.queue.memory_stores import InMemoryLockStore, InMemoryDedupStore
from src.queue.local_dispatcher import LocalTaskDispatcher
from src.queue.gcp_dispatcher import GCPCloudTasksDispatcher
from src.queue.firestore_stores import GCPFirestoreLockStore, firestore_document_id
from src.queue.worker import execute_background_removal_job, bg_remover_worker


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

    assert "local-task-12345" in task_id
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

    task_name = dispatcher.dispatch_product_task(
        product_id="gid://shopify/Product/9999",
        shop_domain="test.myshopify.com",
    )

    assert "projects/my-gcp-project/locations/us-central1/queues/bg-remover-queue/tasks/task-product-9999" in task_name


def test_firestore_document_id_is_path_safe():
    lock_key = "lock:product:gid://shopify/Product/788032119674292922"
    doc_id = firestore_document_id(lock_key)
    assert "/" not in doc_id
    assert ":" not in doc_id
    assert len(doc_id) == 64
    assert firestore_document_id(lock_key) == doc_id


def test_firestore_lock_store_uses_hashed_document_id():
    store = GCPFirestoreLockStore()
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
