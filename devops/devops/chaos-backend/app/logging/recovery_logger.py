import json
import logging
import time
import os
import socket

# Configure logger
logger = logging.getLogger("chaos-backend-recovery")
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter('%(message)s'))
logger.addHandler(handler)
logger.setLevel(logging.INFO)

POD_ID = os.getenv("HOSTNAME", socket.gethostname())

def log_event(event_type: str, details: dict = None):
    """
    Emit a structured JSON log event.
    """
    payload = {
        "timestamp": time.time(),
        "timestamp_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "event_type": event_type,
        "pod_id": POD_ID,
        "details": details or {}
    }
    logger.info(json.dumps(payload))

def log_chaos_start(chaos_type: str, params: dict):
    log_event("CHAOS_START", {"type": chaos_type, "params": params})

def log_chaos_stop(chaos_type: str):
    log_event("CHAOS_STOP", {"type": chaos_type})

def log_readiness_degraded(reason: str):
    log_event("READINESS_DEGRADED", {"reason": reason})

def log_readiness_recovered():
    log_event("READINESS_RECOVERED", {})

def log_pod_restart():
    log_event("POD_RESTART", {"message": "Application started"})
