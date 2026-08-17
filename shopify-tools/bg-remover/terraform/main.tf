terraform {
  required_version = ">= 1.5.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

provider "google" {
  project = var.gcp_project_id
  region  = var.gcp_region
}

# ==============================================================================
# 1. Enable Required GCP APIs
# ==============================================================================
resource "google_project_service" "required_services" {
  for_each = toset([
    "cloudfunctions.googleapis.com",
    "run.googleapis.com",
    "cloudbuild.googleapis.com",
    "cloudtasks.googleapis.com",
    "firestore.googleapis.com",
    "secretmanager.googleapis.com",
    "iam.googleapis.com",
  ])

  project            = var.gcp_project_id
  service            = each.key
  disable_on_destroy = false
}

# ==============================================================================
# 2. Cloud Firestore Database (Native Mode)
# ==============================================================================
resource "google_firestore_database" "database" {
  project     = var.gcp_project_id
  name        = "(default)"
  location_id = var.gcp_region
  type        = "FIRESTORE_NATIVE"

  depends_on = [google_project_service.required_services]
}

# TTL Field Policy for webhook_dedup
resource "google_firestore_field" "webhook_dedup_ttl" {
  project    = var.gcp_project_id
  database   = google_firestore_database.database.name
  collection = "webhook_dedup"
  field      = "expires_at"

  ttl_config {}
}

# TTL Field Policy for product_locks
resource "google_firestore_field" "product_locks_ttl" {
  project    = var.gcp_project_id
  database   = google_firestore_database.database.name
  collection = "product_locks"
  field      = "expires_at"

  ttl_config {}
}

# ==============================================================================
# 3. Cloud Tasks Queue
# ==============================================================================
resource "google_cloud_tasks_queue" "bg_remover_queue" {
  project  = var.gcp_project_id
  location = var.gcp_region
  name     = var.queue_name

  rate_limits {
    max_dispatches_per_second = 5.0
    max_burst_size            = 10
    max_concurrent_dispatches = 10
  }

  retry_config {
    max_attempts = 5
    min_backoff  = "5s"
    max_backoff  = "300s"
    max_doublings = 3
  }

  depends_on = [google_project_service.required_services]
}

# ==============================================================================
# 4. Secret Manager Secrets
# ==============================================================================
resource "google_secret_manager_secret" "shopify_webhook_secret" {
  secret_id = "SHOPIFY_WEBHOOK_SECRET"
  replication {
    auto {}
  }
  depends_on = [google_project_service.required_services]
}

resource "google_secret_manager_secret_version" "shopify_webhook_secret_val" {
  secret      = google_secret_manager_secret.shopify_webhook_secret.id
  secret_data = var.shopify_webhook_secret
}

resource "google_secret_manager_secret" "shopify_admin_access_token" {
  secret_id = "SHOPIFY_ADMIN_API_ACCESS_TOKEN"
  replication {
    auto {}
  }
  depends_on = [google_project_service.required_services]
}

resource "google_secret_manager_secret_version" "shopify_admin_access_token_val" {
  secret      = google_secret_manager_secret.shopify_admin_access_token.id
  secret_data = var.shopify_admin_access_token
}

resource "google_secret_manager_secret" "rembg_api_key" {
  secret_id = "REMBG_API_KEY"
  replication {
    auto {}
  }
  depends_on = [google_project_service.required_services]
}

resource "google_secret_manager_secret_version" "rembg_api_key_val" {
  secret      = google_secret_manager_secret.rembg_api_key.id
  secret_data = var.rembg_api_key
}

# ==============================================================================
# 5. Service Accounts & IAM Permissions
# ==============================================================================

# A. Cloud Function Runtime Service Account
resource "google_service_account" "bg_remover_sa" {
  account_id   = "bg-remover-sa"
  display_name = "Shopify Background Remover Runtime SA"
}

resource "google_project_iam_member" "sa_datastore_user" {
  project = var.gcp_project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.bg_remover_sa.email}"
}

resource "google_project_iam_member" "sa_cloudtasks_enforcer" {
  project = var.gcp_project_id
  role    = "roles/cloudtasks.enforcer"
  member  = "serviceAccount:${google_service_account.bg_remover_sa.email}"
}

resource "google_secret_manager_secret_iam_member" "webhook_secret_access" {
  secret_id = google_secret_manager_secret.shopify_webhook_secret.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.bg_remover_sa.email}"
}

resource "google_secret_manager_secret_iam_member" "admin_token_access" {
  secret_id = google_secret_manager_secret.shopify_admin_access_token.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.bg_remover_sa.email}"
}

resource "google_secret_manager_secret_iam_member" "rembg_key_access" {
  secret_id = google_secret_manager_secret.rembg_api_key.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.bg_remover_sa.email}"
}

# B. GitHub Actions Deployment Service Account
resource "google_service_account" "github_deployer" {
  account_id   = "github-deployer"
  display_name = "GitHub Actions Deployment SA"
}

resource "google_project_iam_member" "deployer_functions_developer" {
  project = var.gcp_project_id
  role    = "roles/cloudfunctions.developer"
  member  = "serviceAccount:${google_service_account.github_deployer.email}"
}

resource "google_project_iam_member" "deployer_sa_user" {
  project = var.gcp_project_id
  role    = "roles/iam.serviceAccountUser"
  member  = "serviceAccount:${google_service_account.github_deployer.email}"
}

resource "google_project_iam_member" "deployer_cloudtasks_admin" {
  project = var.gcp_project_id
  role    = "roles/cloudtasks.admin"
  member  = "serviceAccount:${google_service_account.github_deployer.email}"
}

resource "google_service_account_key" "github_deployer_key" {
  service_account_id = google_service_account.github_deployer.name
}
