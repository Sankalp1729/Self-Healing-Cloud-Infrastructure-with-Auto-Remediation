import signal
import sys
import uvicorn
from fastapi import FastAPI
from prometheus_client import make_asgi_app
from app.config import logger
from app.api import router
from app.health.latency_monitor import LatencyMonitorMiddleware

app = FastAPI(
    title="Chaos Backend", 
    description="Fault-prone backend service for DevOps self-healing demos"
)

# Add Latency Monitoring Middleware
app.add_middleware(LatencyMonitorMiddleware)

# Mount Prometheus metrics endpoint
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)

app.include_router(router)

@app.on_event("startup")
async def startup_event():
    logger.info("Application starting up...")
    logger.info("Configuration loaded successfully")

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Application shutting down...")

def handle_sigterm(signum, frame):
    """
    Handle SIGTERM signal for graceful shutdown.
    Kubernetes sends SIGTERM to stop a container.
    """
    logger.info("Received SIGTERM signal. Initiating graceful shutdown...")
    # In a real app, you might wait for active connections to drain here.
    # FastAPI/Uvicorn handles most of this, but we log it explicitly.
    sys.exit(0)

# Register signal handlers
signal.signal(signal.SIGTERM, handle_sigterm)
signal.signal(signal.SIGINT, handle_sigterm)

if __name__ == "__main__":
    # In production, we usually run via uvicorn command, but this allows python -m app.main
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=False)
