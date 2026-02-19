from prometheus_client import Counter, Histogram

REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["service", "endpoint"]
)

REQUEST_LATENCY = Histogram(
    "http_request_latency_seconds",
    "Latency per endpoint",
    ["service", "endpoint"]
)

ERROR_COUNT = Counter(
    "http_errors_total",
    "Total HTTP errors",
    ["service", "endpoint"]
)
