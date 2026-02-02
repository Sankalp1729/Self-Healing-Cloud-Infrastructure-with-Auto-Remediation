import time
from prometheus_client import Histogram

"""
Metric Semantics

These metrics measure **recovery latency** (Time to Recovery - TTR), not the duration of the failure itself.
They answer the question: "Once we detected a failure, how fast did the system heal?"

We use Histograms instead of Counters to capture the **distribution** of recovery times (p50, p95, p99),
which is critical for understanding tail latency in self-healing systems.
"""

# Prometheus Metrics
FAILURE_TO_READINESS_FAILURE_SECONDS = Histogram(
    "failure_to_readiness_failure_seconds",
    "Time from chaos trigger to readiness probe failure (503). Measures detection latency.",
    buckets=[1, 2, 5, 10, 30, 60]
)

READINESS_FAILURE_TO_RECOVERY_SECONDS = Histogram(
    "readiness_failure_to_recovery_seconds",
    "Time from readiness failure to recovery (200 OK). Measures self-healing speed.",
    buckets=[1, 5, 10, 30, 60, 120]
)

CRASH_TO_STARTUP_SECONDS = Histogram(
    "crash_to_startup_seconds",
    "Time from crash to application startup (approximate). Measures cold-start latency.",
    buckets=[5, 10, 30, 60, 120]
)

# Timer State
# We use simple global state here because the app is single-threaded (or used in a way where this approximation is sufficient for validation)
_chaos_start_time = {}
_readiness_failure_time = None

def start_chaos_timer(chaos_type: str):
    """
    Start timing when a chaos event is triggered.
    This marks the beginning of the "Failure Injection" phase.
    """
    global _chaos_start_time
    _chaos_start_time[chaos_type] = time.time()

def mark_readiness_failed(chaos_type: str = "unknown"):
    """
    Called when readiness probe first flips to 503.
    1. Records detection latency (Time from Injection -> Detection).
    2. Starts timing for recovery (Time from Detection -> Recovery).
    """
    global _readiness_failure_time, _chaos_start_time
    
    current_time = time.time()
    
    # If we have a start time for this chaos type, record how long it took to fail readiness
    start_time = _chaos_start_time.get(chaos_type)
    if start_time:
        duration = current_time - start_time
        FAILURE_TO_READINESS_FAILURE_SECONDS.observe(duration)
        # Reset start time so we don't double count
        del _chaos_start_time[chaos_type]
    
    # Set failure time if not already set (to track time to recovery)
    if _readiness_failure_time is None:
        _readiness_failure_time = current_time

def mark_readiness_recovered():
    """
    Called when readiness probe flips back to 200.
    Records readiness_failure_to_recovery_seconds (TTR).
    This confirms the self-healing cycle is complete.
    """
    global _readiness_failure_time
    
    if _readiness_failure_time:
        duration = time.time() - _readiness_failure_time
        READINESS_FAILURE_TO_RECOVERY_SECONDS.observe(duration)
        _readiness_failure_time = None

def record_startup_time(startup_time_seconds: float):
    """
    Record startup time (useful if we can persist crash time, but usually handled by external monitoring).
    For now, we just expose the histogram for external use.
    """
    CRASH_TO_STARTUP_SECONDS.observe(startup_time_seconds)
