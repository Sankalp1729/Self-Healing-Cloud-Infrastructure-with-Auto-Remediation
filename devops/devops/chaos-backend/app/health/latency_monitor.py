import time
import collections
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from app.config import config

# Sliding window for p95 calculation
LATENCY_WINDOW_SIZE = 100
_latency_window = collections.deque(maxlen=LATENCY_WINDOW_SIZE)

class LatencyMonitorMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        response = await call_next(request)
        process_time = (time.time() - start_time) * 1000 # ms
        
        # Don't track metrics endpoint to avoid observer effect
        if "/metrics" not in request.url.path:
            _latency_window.append(process_time)
            
        return response

def get_p95_latency():
    if not _latency_window:
        return 0
    sorted_latencies = sorted(_latency_window)
    index = int(len(sorted_latencies) * 0.95)
    return sorted_latencies[index]

def is_latency_acceptable(threshold_ms: int = 500) -> bool:
    """
    Check if p95 latency is within acceptable limits.
    """
    p95 = get_p95_latency()
    return p95 < threshold_ms
