from prometheus_client import Counter, Histogram

# Generic HTTP metrics
REQUEST_LATENCY = Histogram(
    "http_request_latency_seconds",
    "HTTP request latency",
    labelnames=("method", "path", "status"),
)
REQUEST_COUNT = Counter(
    "http_requests_total", "Total HTTP requests", labelnames=("method", "path", "status")
)

# Domain metrics
USAGE_RESERVE_TOTAL = Counter(
    "usage_reserve_total", "Reservations processed", labelnames=("status", "reason")
)
USAGE_COMMIT_TOTAL = Counter(
    "usage_commit_total", "Commits processed", labelnames=("status", "reason")
)
USAGE_ROLLBACK_TOTAL = Counter(
    "usage_rollback_total", "Rollbacks processed", labelnames=("status", "reason")
)



