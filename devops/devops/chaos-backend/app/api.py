import time
import psutil
import os
import threading
from fastapi import APIRouter, HTTPException, Response, status
from prometheus_client import Counter, Gauge
from app.config import config, logger
from app.metrics import timing
from app.logging import recovery_logger
from app.health import latency_monitor

router = APIRouter()

# Global state
memory_leak = []
is_cpu_stressed = False
last_chaos_time = 0
active_chaos_count = 0
was_unready = False

# Prometheus Metrics
REQUEST_COUNT = Counter("http_requests_total", "Total count of HTTP requests", ["method", "endpoint"])
CPU_STRESS_ACTIVE = Gauge("cpu_stress_active", "Whether CPU stress is currently active (1 for yes, 0 for no)")
MEMORY_USAGE_BYTES = Gauge("memory_usage_bytes", "Current memory usage in bytes")
MEMORY_CHUNKS_COUNT = Gauge("memory_chunks_count", "Number of allocated memory chunks")
POD_RECOVERY_COUNT = Counter("pod_recovery_count", "Total count of pod recoveries (startup or readiness flip)")
POD_READY_STATUS = Gauge("pod_ready_status", "Current readiness status (1 for ready, 0 for not ready)")

# Increment recovery count on module import (simulates startup)
POD_RECOVERY_COUNT.inc()
recovery_logger.log_pod_restart()
logger.info("Pod started (Recovery Count Incremented)")

def check_chaos_limits():
    """
    Enforces chaos engineering guardrails:
    - Max concurrent chaos actions
    - Cooldown window
    """
    global active_chaos_count, last_chaos_time
    
    current_time = time.time()
    
    if active_chaos_count >= config.MAX_CONCURRENT_CHAOS:
        raise HTTPException(status_code=429, detail="Too many concurrent chaos actions")
    
    if (current_time - last_chaos_time) < config.CHAOS_COOLDOWN_SECONDS:
         raise HTTPException(status_code=429, detail=f"Chaos cooldown active. Wait {int(config.CHAOS_COOLDOWN_SECONDS - (current_time - last_chaos_time))}s")

    last_chaos_time = current_time

@router.get("/health")
def health():
    """
    Returns service health status.
    Used by Kubernetes liveness probes.
    Always returns 200 unless the app is completely broken.
    """
    REQUEST_COUNT.labels(method="GET", endpoint="/health").inc()
    return {"status": "healthy"}

@router.get("/ready")
def ready(response: Response):
    """
    Returns readiness status.
    Used by Kubernetes readiness probes.
    
    Why this exists:
    - Unlike liveness (which kills the pod), readiness simply pauses traffic.
    - This allows the pod to "cool down" (shed load) without a destructive restart.
    - If this returns 503, the load balancer removes this pod from rotation.
    
    Fails (503) if:
    - CPU stress is active (simulating overload)
    - Memory usage is above threshold (preventing OOM)
    - Latency (p95) is too high (protecting user experience)
    """
    REQUEST_COUNT.labels(method="GET", endpoint="/ready").inc()
    global was_unready
    
    is_ready = True
    reason = "ready"

    # Check CPU stress
    if is_cpu_stressed:
        is_ready = False
        reason = "CPU stress active"

    # Check Memory usage
    process = psutil.Process(os.getpid())
    mem_info = process.memory_info()
    usage_mb = mem_info.rss / (1024 * 1024)
    MEMORY_USAGE_BYTES.set(mem_info.rss)

    if usage_mb > config.MAX_MEMORY_MB_READY:
        is_ready = False
        reason = f"Memory usage too high: {usage_mb:.2f}MB"

    # Check Latency
    if not latency_monitor.is_latency_acceptable(config.MAX_LATENCY_MS):
        is_ready = False
        p95 = latency_monitor.get_p95_latency()
        reason = f"High latency: p95={p95:.2f}ms > {config.MAX_LATENCY_MS}ms"

    # Update Metrics & Recovery Logic
    if is_ready:
        POD_READY_STATUS.set(1)
        if was_unready:
            logger.info("Pod recovered! Readiness flipped from 503 -> 200")
            POD_RECOVERY_COUNT.inc()
            timing.mark_readiness_recovered()
            recovery_logger.log_readiness_recovered()
            was_unready = False
        return {"status": "ready"}
    else:
        POD_READY_STATUS.set(0)
        # Log transition to unready
        if not was_unready:
            recovery_logger.log_readiness_degraded(reason)
            timing.mark_readiness_failed(chaos_type="detected_failure") # We don't know exact trigger here, but we detect it
        
        was_unready = True
        logger.warning(f"Readiness probe failed: {reason}")
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "not ready", "reason": reason}

@router.post("/load/cpu")
def load_cpu(duration: int = None):
    """
    Artificially consume CPU for a configurable duration.
    Query param 'duration' overrides env var default.
    """
    REQUEST_COUNT.labels(method="POST", endpoint="/load/cpu").inc()
    check_chaos_limits()
    
    global is_cpu_stressed, active_chaos_count
    
    load_duration = duration if duration is not None else config.CPU_LOAD_DURATION
    logger.info(f"Starting CPU load for {load_duration} seconds")
    
    is_cpu_stressed = True
    active_chaos_count += 1
    CPU_STRESS_ACTIVE.set(1)
    
    # Start timing for self-healing metrics
    timing.start_chaos_timer("cpu_load")
    recovery_logger.log_chaos_start("cpu_load", {"duration": load_duration})

    try:
        end_time = time.time() + load_duration
        while time.time() < end_time:
            # Busy loop to consume CPU
            _ = [x * x for x in range(1000)]
    finally:
        is_cpu_stressed = False
        active_chaos_count -= 1
        CPU_STRESS_ACTIVE.set(0)
        recovery_logger.log_chaos_stop("cpu_load")
    
    logger.info("CPU load finished")
    return {"message": f"Consumed CPU for {load_duration} seconds"}

@router.post("/load/memory")
def load_memory(mb: int = None):
    """
    Allocate configurable memory to simulate memory pressure.
    Query param 'mb' overrides env var default.
    """
    REQUEST_COUNT.labels(method="POST", endpoint="/load/memory").inc()
    check_chaos_limits()

    mem_mb = mb if mb is not None else config.MEMORY_MB
    logger.info(f"Allocating {mem_mb} MB of memory")
    
    # Start timing
    timing.start_chaos_timer("memory_load")
    recovery_logger.log_chaos_start("memory_load", {"mb": mem_mb})

    try:
        # Allocate memory (1MB = 1024 * 1024 bytes)
        # Using a string to consume memory
        chunk = " " * (mem_mb * 1024 * 1024)
        memory_leak.append(chunk)
        MEMORY_CHUNKS_COUNT.set(len(memory_leak))
        
        current_process = psutil.Process(os.getpid())
        mem_info = current_process.memory_info()
        
        usage_mb = mem_info.rss / (1024 * 1024)
        MEMORY_USAGE_BYTES.set(mem_info.rss)
        logger.info(f"Current memory usage: {usage_mb:.2f} MB")

        return {
            "message": f"Allocated {mem_mb} MB",
            "current_usage_mb": usage_mb,
            "total_chunks": len(memory_leak)
        }
    except MemoryError:
        logger.error("Memory allocation failed: Out of memory")
        raise HTTPException(status_code=500, detail="Out of memory")

@router.post("/crash")
def crash():
    """
    Terminate the application intentionally.
    Simulates a fatal error or crash.
    """
    REQUEST_COUNT.labels(method="POST", endpoint="/crash").inc()
    # Crash doesn't need guardrails because it kills the pod anyway
    
    logger.critical("Crash requested! Terminating application...")
    
    timing.start_chaos_timer("crash")
    recovery_logger.log_chaos_start("crash", {})

    # Flush logs to ensure we capture the crash event
    for handler in logger.handlers:
        handler.flush()
    
    # Force exit with error code 1
    os._exit(1)
    return {"message": "Crashing..."}
