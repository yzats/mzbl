#!/bin/bash
# ==============================================================================
# GCP Production Deployment Script for Shopify Background Remover
# ==============================================================================
set -euo pipefail

# Configuration Defaults (Override via Environment Variables)
GCP_PROJECT_ID="${GCP_PROJECT_ID:-your-gcp-project-id}"
GCP_REGION="${GCP_REGION:-us-central1}"
QUEUE_NAME="${QUEUE_NAME:-bg-remover-queue}"
SERVICE_ACCOUNT_NAME="bg-remover-sa"
SERVICE_ACCOUNT_EMAIL="${SERVICE_ACCOUNT_NAME}@${GCP_PROJECT_ID}.iam.gserviceaccount.com"

BG_REMOVER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "======================================================================"
echo "🚀 Deploying Shopify Background Remover to GCP"
echo "   Project ID: ${GCP_PROJECT_ID}"
echo "   Region:     ${GCP_REGION}"
echo "   Queue:      ${QUEUE_NAME}"
echo "======================================================================"

# 1. Enable Required GCP APIs
echo "1. Enabling required GCP Service APIs..."
gcloud services enable \
  cloudfunctions.googleapis.com \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  cloudtasks.googleapis.com \
  firestore.googleapis.com \
  secretmanager.googleapis.com \
  --project="${GCP_PROJECT_ID}"

# 2. Create Service Account if not exists
echo "2. Ensuring Service Account '${SERVICE_ACCOUNT_EMAIL}' exists..."
if ! gcloud iam service-accounts describe "${SERVICE_ACCOUNT_EMAIL}" --project="${GCP_PROJECT_ID}" &>/dev/null; then
  gcloud iam service-accounts create "${SERVICE_ACCOUNT_NAME}" \
    --display-name="Shopify Background Remover Service Account" \
    --project="${GCP_PROJECT_ID}"
fi

# Grant Service Account necessary IAM roles
gcloud projects add-iam-policy-binding "${GCP_PROJECT_ID}" \
  --member="serviceAccount:${SERVICE_ACCOUNT_EMAIL}" \
  --role="roles/datastore.user" &>/dev/null || true

gcloud projects add-iam-policy-binding "${GCP_PROJECT_ID}" \
  --member="serviceAccount:${SERVICE_ACCOUNT_EMAIL}" \
  --role="roles/cloudtasks.enforcer" &>/dev/null || true

# 3. Create Cloud Tasks Queue
echo "3. Provisioning Cloud Tasks Queue '${QUEUE_NAME}'..."
if ! gcloud tasks queues describe "${QUEUE_NAME}" --location="${GCP_REGION}" --project="${GCP_PROJECT_ID}" &>/dev/null; then
  gcloud tasks queues create "${QUEUE_NAME}" \
    --location="${GCP_REGION}" \
    --max-dispatches-per-second=5.0 \
    --max-concurrent-dispatches=10 \
    --max-attempts=5 \
    --min-backoff=5s \
    --max-backoff=300s \
    --project="${GCP_PROJECT_ID}"
fi

# 4. Deploy Webhook Receiver Cloud Function
echo "4. Deploying 'shopify_webhook_receiver' Cloud Function..."
gcloud functions deploy shopify_webhook_receiver \
  --gen2 \
  --runtime=python311 \
  --region="${GCP_REGION}" \
  --source="${BG_REMOVER_DIR}" \
  --entry-point=shopify_webhook_receiver \
  --trigger-http \
  --allow-unauthenticated \
  --service-account="${SERVICE_ACCOUNT_EMAIL}" \
  --memory=256Mi \
  --timeout=10s \
  --project="${GCP_PROJECT_ID}"

RECEIVER_URL=$(gcloud functions describe shopify_webhook_receiver --gen2 --region="${GCP_REGION}" --project="${GCP_PROJECT_ID}" --format="value(serviceConfig.uri)")

# 5. Deploy Worker Cloud Function
echo "5. Deploying 'bg_remover_worker' Cloud Function..."
gcloud functions deploy bg_remover_worker \
  --gen2 \
  --runtime=python311 \
  --region="${GCP_REGION}" \
  --source="${BG_REMOVER_DIR}" \
  --entry-point=bg_remover_worker \
  --trigger-http \
  --no-allow-unauthenticated \
  --service-account="${SERVICE_ACCOUNT_EMAIL}" \
  --memory=512Mi \
  --timeout=120s \
  --project="${GCP_PROJECT_ID}"

WORKER_URL=$(gcloud functions describe bg_remover_worker --gen2 --region="${GCP_REGION}" --project="${GCP_PROJECT_ID}" --format="value(serviceConfig.uri)")

echo "======================================================================"
echo "✨ GCP Deployment Completed Successfully!"
echo "   Webhook Receiver Endpoint: ${RECEIVER_URL}"
echo "   Worker Endpoint:           ${WORKER_URL}"
echo "======================================================================"
