from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import make_asgi_app

from api.core.config import settings
from api.routers import auth, predict, billing, admin
from api.middleware.metrics_middleware import MetricsMiddleware

app = FastAPI(
    title="CallRoute ML",
    description="Scalable ML routing service for call centers",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Prometheus metrics middleware
app.add_middleware(MetricsMiddleware)

# Routers
app.include_router(auth.router, prefix=settings.api_v1_prefix)
app.include_router(predict.router, prefix=settings.api_v1_prefix)
app.include_router(billing.router, prefix=settings.api_v1_prefix)
app.include_router(admin.router, prefix=settings.api_v1_prefix)

# Prometheus metrics endpoint
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)


@app.get("/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}
