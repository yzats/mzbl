#!/bin/bash
# ==============================================================================
# GCP Phase 2: Deploy Cloud Functions only.
# APIs, IAM, Firestore, queues, and secrets are provisioned by Terraform.
# ==============================================================================
set -euo pipefail

# Never prompt to enable APIs in CI (gcloud would hang on y/N).
export CLOUDSDK_CORE_DISABLE_PROMPTS=1

GCP_PROJECT_ID="${GCP_PROJECT_ID:-your-gcp-project-id}"
GCP_REGION="${GCP_REGION:-us-central1}"
QUEUE_NAME="${QUEUE_NAME:-bg-remover-queue}"
SERVICE_ACCOUNT_NAME="bg-remover-sa"
SERVICE_ACCOUNT_EMAIL="${SERVICE_ACCOUNT_NAME}@${GCP_PROJECT_ID}.iam.gserviceaccount.com"
DEPLOYER_SA_EMAIL="github-deployer@${GCP_PROJECT_ID}.iam.gserviceaccount.com"
BUILD_SERVICE_ACCOUNT="projects/${GCP_PROJECT_ID}/serviceAccounts/${DEPLOYER_SA_EMAIL}"

BG_REMOVER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "======================================================================"
echo "Deploying Shopify Background Remover to GCP"
echo "   Project ID: ${GCP_PROJECT_ID}"
echo "   Region:     ${GCP_REGION}"
echo "   Queue:      ${QUEUE_NAME}"
echo "======================================================================"

echo "1. Verifying Terraform-managed runtime service account..."
if ! gcloud iam service-accounts describe "${SERVICE_ACCOUNT_EMAIL}" --project="${GCP_PROJECT_ID}" &>/dev/null; then
  echo "ERROR: Service account ${SERVICE_ACCOUNT_EMAIL} not found." >&2
  echo "Run terraform apply in shopify-tools/bg-remover/terraform first." >&2
  exit 1
fi

echo "2. Verifying Terraform-managed Cloud Tasks queue..."
if ! gcloud tasks queues describe "${QUEUE_NAME}" --location="${GCP_REGION}" --project="${GCP_PROJECT_ID}" &>/dev/null; then
  echo "ERROR: Cloud Tasks queue ${QUEUE_NAME} not found in ${GCP_REGION}." >&2
  echo "Run terraform apply in shopify-tools/bg-remover/terraform first." >&2
  exit 1
fi

echo "3. Deploying 'bg_remover_worker' Cloud Function..."
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
  --project="${GCP_PROJECT_ID}" \
  --build-service-account="${BUILD_SERVICE_ACCOUNT}" \
  --set-env-vars="GCP_PROJECT_ID=${GCP_PROJECT_ID},GCP_REGION=${GCP_REGION}" \
  --set-secrets="SHOPIFY_ADMIN_API_ACCESS_TOKEN=SHOPIFY_ADMIN_API_ACCESS_TOKEN:latest,REMBG_API_KEY=REMBG_API_KEY:latest"

WORKER_URL=$(gcloud functions describe bg_remover_worker --gen2 --region="${GCP_REGION}" --project="${GCP_PROJECT_ID}" --format="value(serviceConfig.uri)")

echo "   Granting runtime SA invoker on worker..."
gcloud run services add-iam-policy-binding bg-remover-worker \
  --region="${GCP_REGION}" \
  --project="${GCP_PROJECT_ID}" \
  --member="serviceAccount:${SERVICE_ACCOUNT_EMAIL}" \
  --role="roles/run.invoker" \
  --quiet

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
  --project="${GCP_PROJECT_ID}" \
  --build-service-account="${BUILD_SERVICE_ACCOUNT}" \
  --set-env-vars="GCP_PROJECT_ID=${GCP_PROJECT_ID},GCP_REGION=${GCP_REGION},QUEUE_NAME=${QUEUE_NAME},WORKER_TARGET_URL=${WORKER_URL},FUNCTION_RUNTIME_SA=${SERVICE_ACCOUNT_EMAIL}" \
  --set-secrets="SHOPIFY_WEBHOOK_SECRET=SHOPIFY_WEBHOOK_SECRET:latest"

RECEIVER_URL=$(gcloud functions describe shopify_webhook_receiver --gen2 --region="${GCP_REGION}" --project="${GCP_PROJECT_ID}" --format="value(serviceConfig.uri)")

echo "======================================================================"
echo "GCP Deployment Completed Successfully!"
echo "   Webhook Receiver Endpoint: ${RECEIVER_URL}"
echo "   Worker Endpoint:           ${WORKER_URL}"
echo "Paste the Webhook Receiver Endpoint into Shopify Admin → Settings → Notifications → Webhooks (products/update)."
echo "======================================================================"
