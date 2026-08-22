variable "github_owner" {
  type        = string
  description = "GitHub Repository Owner / Username (e.g. 'yzats')"
}

variable "github_repo_name" {
  type        = string
  description = "GitHub Repository Name (e.g. 'mzbl')"
}

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

variable "alert_email" {
  type        = string
  description = "Optional email for circuit alerts (open/close, no 24h nag). Empty string skips the email channel."
  default     = ""
}

variable "alert_sms" {
  type        = string
  description = "E.164 SMS number for circuit alerts (e.g. +15555550100). Empty string skips the SMS channel."
  default     = ""
}
