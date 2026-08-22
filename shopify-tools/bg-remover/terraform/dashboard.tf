# ==============================================================================
# 8. Ops dashboard (time-series) + extra log-based counters
# ==============================================================================

locals {
  bg_log_metrics = {
    circuit_closed = {
      name        = "bg_remover_circuit_closed"
      description = "Counts [CIRCUIT CLOSED] when bg-remover-queue is resumed"
      needles     = ["[CIRCUIT CLOSED]"]
    }
    task_enqueued = {
      name        = "bg_remover_task_enqueued"
      description = "Counts [TASK ENQUEUED] Cloud Tasks creates"
      needles     = ["[TASK ENQUEUED]"]
    }
    task_deduped = {
      name        = "bg_remover_task_deduped"
      description = "Counts named-task or webhook updated_at dedup"
      needles     = ["[TASK DEDUPED]", "[200 DEDUPED]"]
    }
    webhook_id_skip = {
      name        = "bg_remover_webhook_id_skip"
      description = "Counts Layer-1 duplicate X-Shopify-Webhook-Id skips"
      needles     = ["Duplicate Webhook ID"]
    }
    lock_skip = {
      name        = "bg_remover_lock_skip"
      description = "Counts worker skips while a product lock is held"
      needles     = ["Product lock active"]
    }
  }

  bg_log_metric_filters = {
    for key, spec in local.bg_log_metrics : key => join(" OR ", flatten([
      for needle in spec.needles : [
        "textPayload:\"${needle}\"",
        "jsonPayload.message:\"${needle}\"",
      ]
    ]))
  }
}

resource "google_logging_metric" "bg_dashboard" {
  for_each    = local.bg_log_metrics
  name        = each.value.name
  description = each.value.description
  filter      = local.bg_log_metric_filters[each.key]

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
  }

  depends_on = [google_project_service.required_services]
}

locals {
  bg_custom_metrics = {
    rembg_credits = {
      type         = "custom.googleapis.com/bg_remover/rembg_credits"
      display_name = "BG Remover rembg credits"
      description  = "Remaining rembg membership credits from rembg_circuit_probe"
      metric_kind  = "GAUGE"
    }
    rembg_prepaid_credits = {
      type         = "custom.googleapis.com/bg_remover/rembg_prepaid_credits"
      display_name = "BG Remover rembg prepaid credits"
      description  = "Remaining rembg prepaidCredits from rembg_circuit_probe"
      metric_kind  = "GAUGE"
    }
    images_processed = {
      type         = "custom.googleapis.com/bg_remover/images_processed"
      display_name = "BG Remover images processed"
      description  = "Images successfully processed by bg_remover_worker (gauge per batch; chart ALIGN_SUM)"
      metric_kind  = "GAUGE"
    }
  }
}

resource "google_monitoring_metric_descriptor" "bg_custom" {
  for_each     = local.bg_custom_metrics
  type         = each.value.type
  display_name = each.value.display_name
  description  = each.value.description
  metric_kind  = each.value.metric_kind
  value_type   = "INT64"
  unit         = "1"

  depends_on = [google_project_service.required_services]
}

resource "google_monitoring_dashboard" "bg_remover" {
  dashboard_json = jsonencode({
    displayName = "BG Remover"
    labels = {
      tool = "shopify-bg-remover"
    }
    mosaicLayout = {
      columns = 12
      tiles = [
        {
          xPos   = 0
          yPos   = 0
          width  = 6
          height = 4
          widget = {
            title = "Circuit open / still open (5m buckets)"
            xyChart = {
              chartOptions      = { mode = "COLOR" }
              timeshiftDuration = "0s"
              dataSets = [{
                plotType           = "LINE"
                minAlignmentPeriod = "60s"
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "metric.type=\"logging.googleapis.com/user/bg_remover_circuit_open\""
                    aggregation = {
                      alignmentPeriod  = "60s"
                      perSeriesAligner = "ALIGN_DELTA"
                    }
                  }
                }
              }]
              yAxis = { label = "events", scale = "LINEAR" }
            }
          }
        },
        {
          xPos   = 6
          yPos   = 0
          width  = 6
          height = 4
          widget = {
            title = "Circuit closed (queue resumed)"
            xyChart = {
              chartOptions = { mode = "COLOR" }
              dataSets = [{
                plotType           = "LINE"
                minAlignmentPeriod = "60s"
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "metric.type=\"logging.googleapis.com/user/bg_remover_circuit_closed\""
                    aggregation = {
                      alignmentPeriod  = "60s"
                      perSeriesAligner = "ALIGN_DELTA"
                    }
                  }
                }
              }]
              yAxis = { label = "events", scale = "LINEAR" }
            }
          }
        },
        {
          xPos   = 0
          yPos   = 4
          width  = 6
          height = 4
          widget = {
            title = "Cloud Tasks queue depth"
            xyChart = {
              chartOptions = { mode = "COLOR" }
              dataSets = [{
                plotType           = "LINE"
                minAlignmentPeriod = "60s"
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "metric.type=\"cloudtasks.googleapis.com/queue/depth\" AND resource.label.queue_id=\"${var.queue_name}\""
                    aggregation = {
                      alignmentPeriod    = "60s"
                      perSeriesAligner   = "ALIGN_MEAN"
                      crossSeriesReducer = "REDUCE_SUM"
                    }
                  }
                }
              }]
              yAxis = { label = "tasks", scale = "LINEAR" }
            }
          }
        },
        {
          xPos   = 6
          yPos   = 4
          width  = 6
          height = 4
          widget = {
            title = "Cloud Tasks task attempts"
            xyChart = {
              chartOptions = { mode = "COLOR" }
              dataSets = [{
                plotType           = "LINE"
                minAlignmentPeriod = "60s"
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "metric.type=\"cloudtasks.googleapis.com/queue/task_attempt_count\" AND resource.label.queue_id=\"${var.queue_name}\""
                    aggregation = {
                      alignmentPeriod    = "60s"
                      perSeriesAligner   = "ALIGN_DELTA"
                      crossSeriesReducer = "REDUCE_SUM"
                    }
                  }
                }
              }]
              yAxis = { label = "attempts", scale = "LINEAR" }
            }
          }
        },
        {
          xPos   = 0
          yPos   = 8
          width  = 6
          height = 4
          widget = {
            title = "Probe HTTP requests (rembg-circuit-probe)"
            xyChart = {
              chartOptions = { mode = "COLOR" }
              dataSets = [{
                plotType           = "STACKED_AREA"
                minAlignmentPeriod = "60s"
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "metric.type=\"run.googleapis.com/request_count\" AND resource.label.service_name=\"rembg-circuit-probe\""
                    aggregation = {
                      alignmentPeriod    = "60s"
                      perSeriesAligner   = "ALIGN_RATE"
                      crossSeriesReducer = "REDUCE_SUM"
                      groupByFields      = ["metric.label.response_code_class"]
                    }
                  }
                }
              }]
              yAxis = { label = "req/s", scale = "LINEAR" }
            }
          }
        },
        {
          xPos   = 6
          yPos   = 8
          width  = 6
          height = 4
          widget = {
            title = "Worker HTTP requests (bg-remover-worker)"
            xyChart = {
              chartOptions = { mode = "COLOR" }
              dataSets = [{
                plotType           = "STACKED_AREA"
                minAlignmentPeriod = "60s"
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "metric.type=\"run.googleapis.com/request_count\" AND resource.label.service_name=\"bg-remover-worker\""
                    aggregation = {
                      alignmentPeriod    = "60s"
                      perSeriesAligner   = "ALIGN_RATE"
                      crossSeriesReducer = "REDUCE_SUM"
                      groupByFields      = ["metric.label.response_code"]
                    }
                  }
                }
              }]
              yAxis = { label = "req/s", scale = "LINEAR" }
            }
          }
        },
        {
          xPos   = 0
          yPos   = 12
          width  = 6
          height = 4
          widget = {
            title = "Receiver HTTP requests (shopify-webhook-receiver)"
            xyChart = {
              chartOptions = { mode = "COLOR" }
              dataSets = [{
                plotType           = "STACKED_AREA"
                minAlignmentPeriod = "60s"
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "metric.type=\"run.googleapis.com/request_count\" AND resource.label.service_name=\"shopify-webhook-receiver\""
                    aggregation = {
                      alignmentPeriod    = "60s"
                      perSeriesAligner   = "ALIGN_RATE"
                      crossSeriesReducer = "REDUCE_SUM"
                      groupByFields      = ["metric.label.response_code"]
                    }
                  }
                }
              }]
              yAxis = { label = "req/s", scale = "LINEAR" }
            }
          }
        },
        {
          xPos   = 6
          yPos   = 12
          width  = 6
          height = 4
          widget = {
            title = "Enqueue vs named-task dedup"
            xyChart = {
              chartOptions = { mode = "COLOR" }
              dataSets = [
                {
                  plotType           = "LINE"
                  legendTemplate     = "enqueued"
                  minAlignmentPeriod = "60s"
                  timeSeriesQuery = {
                    timeSeriesFilter = {
                      filter = "metric.type=\"logging.googleapis.com/user/bg_remover_task_enqueued\""
                      aggregation = {
                        alignmentPeriod  = "60s"
                        perSeriesAligner = "ALIGN_DELTA"
                      }
                    }
                  }
                },
                {
                  plotType           = "LINE"
                  legendTemplate     = "deduped"
                  minAlignmentPeriod = "60s"
                  timeSeriesQuery = {
                    timeSeriesFilter = {
                      filter = "metric.type=\"logging.googleapis.com/user/bg_remover_task_deduped\""
                      aggregation = {
                        alignmentPeriod  = "60s"
                        perSeriesAligner = "ALIGN_DELTA"
                      }
                    }
                  }
                }
              ]
              yAxis = { label = "events", scale = "LINEAR" }
            }
          }
        },
        {
          xPos   = 0
          yPos   = 16
          width  = 6
          height = 4
          widget = {
            title = "Webhook-id skip vs product-lock skip"
            xyChart = {
              chartOptions = { mode = "COLOR" }
              dataSets = [
                {
                  plotType           = "LINE"
                  legendTemplate     = "webhook id skip"
                  minAlignmentPeriod = "60s"
                  timeSeriesQuery = {
                    timeSeriesFilter = {
                      filter = "metric.type=\"logging.googleapis.com/user/bg_remover_webhook_id_skip\""
                      aggregation = {
                        alignmentPeriod  = "60s"
                        perSeriesAligner = "ALIGN_DELTA"
                      }
                    }
                  }
                },
                {
                  plotType           = "LINE"
                  legendTemplate     = "lock skip"
                  minAlignmentPeriod = "60s"
                  timeSeriesQuery = {
                    timeSeriesFilter = {
                      filter = "metric.type=\"logging.googleapis.com/user/bg_remover_lock_skip\""
                      aggregation = {
                        alignmentPeriod  = "60s"
                        perSeriesAligner = "ALIGN_DELTA"
                      }
                    }
                  }
                }
              ]
              yAxis = { label = "events", scale = "LINEAR" }
            }
          }
        },
        {
          xPos   = 6
          yPos   = 16
          width  = 6
          height = 4
          widget = {
            title = "Worker request latency (p50 / p95)"
            xyChart = {
              chartOptions = { mode = "COLOR" }
              dataSets = [
                {
                  plotType           = "LINE"
                  legendTemplate     = "p50"
                  minAlignmentPeriod = "60s"
                  timeSeriesQuery = {
                    timeSeriesFilter = {
                      filter = "metric.type=\"run.googleapis.com/request_latencies\" AND resource.label.service_name=\"bg-remover-worker\""
                      aggregation = {
                        alignmentPeriod    = "60s"
                        perSeriesAligner   = "ALIGN_DELTA"
                        crossSeriesReducer = "REDUCE_PERCENTILE_50"
                      }
                    }
                  }
                },
                {
                  plotType           = "LINE"
                  legendTemplate     = "p95"
                  minAlignmentPeriod = "60s"
                  timeSeriesQuery = {
                    timeSeriesFilter = {
                      filter = "metric.type=\"run.googleapis.com/request_latencies\" AND resource.label.service_name=\"bg-remover-worker\""
                      aggregation = {
                        alignmentPeriod    = "60s"
                        perSeriesAligner   = "ALIGN_DELTA"
                        crossSeriesReducer = "REDUCE_PERCENTILE_95"
                      }
                    }
                  }
                }
              ]
              yAxis = { label = "ms", scale = "LINEAR" }
            }
          }
        },
        {
          xPos   = 0
          yPos   = 20
          width  = 6
          height = 4
          widget = {
            title = "Rembg credits remaining"
            xyChart = {
              chartOptions = { mode = "COLOR" }
              dataSets = [
                {
                  plotType           = "LINE"
                  legendTemplate     = "credits"
                  minAlignmentPeriod = "60s"
                  timeSeriesQuery = {
                    timeSeriesFilter = {
                      filter = "metric.type=\"custom.googleapis.com/bg_remover/rembg_credits\""
                      aggregation = {
                        alignmentPeriod  = "60s"
                        perSeriesAligner = "ALIGN_MEAN"
                      }
                    }
                  }
                },
                {
                  plotType           = "LINE"
                  legendTemplate     = "prepaid"
                  minAlignmentPeriod = "60s"
                  timeSeriesQuery = {
                    timeSeriesFilter = {
                      filter = "metric.type=\"custom.googleapis.com/bg_remover/rembg_prepaid_credits\""
                      aggregation = {
                        alignmentPeriod  = "60s"
                        perSeriesAligner = "ALIGN_MEAN"
                      }
                    }
                  }
                }
              ]
              yAxis = { label = "credits", scale = "LINEAR" }
            }
          }
        },
        {
          xPos   = 6
          yPos   = 20
          width  = 6
          height = 4
          widget = {
            title = "Images processed"
            xyChart = {
              chartOptions      = { mode = "COLOR" }
              timeshiftDuration = "0s"
              dataSets = [{
                plotType           = "LINE"
                minAlignmentPeriod = "60s"
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "metric.type=\"custom.googleapis.com/bg_remover/images_processed\""
                    aggregation = {
                      alignmentPeriod  = "60s"
                      perSeriesAligner = "ALIGN_SUM"
                    }
                  }
                }
              }]
              yAxis = { label = "images", scale = "LINEAR" }
            }
          }
        }
      ]
    }
  })

  depends_on = [
    google_logging_metric.circuit_open,
    google_logging_metric.bg_dashboard,
    google_monitoring_metric_descriptor.bg_custom,
  ]
}
