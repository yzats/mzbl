variable "gcp_project_id" {
  type        = string
  description = "GCP Project ID"
}

variable "gcp_region" {
  type        = string
  description = "GCP Region"
  default     = "us-central1"
}

variable "queue_name" {
  type        = string
  description = "Cloud Tasks Queue Name"
  default     = "bg-remover-queue"
}

variable "shopify_webhook_secret" {
  type        = string
  description = "Shopify Webhook Signature Secret"
  sensitive   = true
}

variable "shopify_admin_access_token" {
  type        = string
  description = "Shopify Admin API Access Token"
  sensitive   = true
}

variable "rembg_api_key" {
  type        = string
  description = "Rembg Hosted API Key"
  sensitive   = true
}
