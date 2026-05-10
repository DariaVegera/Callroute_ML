import time
from prometheus_client import Counter, Histogram, Gauge
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

http_requests_total = Counter(
    "http_requests_total", "Total HTTP requests",
    ["method", "endpoint", "status_code"]
)
http_request_duration_seconds = Histogram(
    "http_request_duration_seconds", "HTTP request duration",
    ["method", "endpoint"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0]
)
http_active_connections = Gauge("http_active_connections", "Active HTTP connections")
billing_credits_charged_total = Counter(
    "billing_credits_charged_total", "Credits charged",
    ["tier", "balance_type"]
)
ml_low_confidence_total = Counter(
    "ml_low_confidence_total", "Low confidence predictions", ["tier"]
)
hitl_completed_total = Counter("hitl_completed_total", "HITL tasks completed")


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        http_active_connections.inc()
        start = time.time()
        path = request.url.path
        # нормализуем UUID-сегменты
        parts = path.split("/")
        normalized = "/".join(
            "{id}" if (len(p) == 36 and p.count("-") == 4) else p
            for p in parts
        )
        try:
            response = await call_next(request)
            duration = time.time() - start
            http_requests_total.labels(
                method=request.method,
                endpoint=normalized,
                status_code=response.status_code
            ).inc()
            http_request_duration_seconds.labels(
                method=request.method, endpoint=normalized
            ).observe(duration)
            return response
        finally:
            http_active_connections.dec()
