output "github_sa_key_json" {
  value       = google_service_account_key.github_deployer_key.private_key
  description = "Base64 encoded JSON key for GitHub Actions GCP_SA_KEY secret"
  sensitive   = true
}

output "cloud_tasks_queue_id" {
  value       = google_cloud_tasks_queue.bg_remover_queue.id
  description = "Full ID of the provisioned Cloud Tasks Queue"
}

output "firestore_database_id" {
  value       = google_firestore_database.database.id
  description = "ID of the provisioned Firestore Native database"
}

output "bg_remover_dashboard_id" {
  value       = google_monitoring_dashboard.bg_remover.id
  description = "Cloud Monitoring dashboard resource name (projects/.../dashboards/...)"
}

output "circuit_email_channel_id" {
  value       = try(google_monitoring_notification_channel.circuit_email[0].name, "")
  description = "Monitoring email notification channel (empty if alert_email unset)"
}

output "circuit_sms_channel_id" {
  value       = try(google_monitoring_notification_channel.circuit_sms[0].name, "")
  description = "Monitoring SMS notification channel (empty if alert_sms unset)"
}
