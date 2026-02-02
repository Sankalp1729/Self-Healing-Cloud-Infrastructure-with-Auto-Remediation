import os
import logging

class Config:
    def __init__(self):
        self.CPU_LOAD_DURATION = int(os.getenv("CPU_LOAD_DURATION", 10))
        self.MEMORY_MB = int(os.getenv("MEMORY_MB", 100))
        self.RANDOM_CRASH_ENABLED = os.getenv("RANDOM_CRASH_ENABLED", "false").lower() == "true"
        self.MAX_MEMORY_MB_READY = int(os.getenv("MAX_MEMORY_MB_READY", 400)) # Threshold for readiness check
        self.MAX_CONCURRENT_CHAOS = int(os.getenv("MAX_CONCURRENT_CHAOS", 1)) # Max concurrent chaos actions
        self.CHAOS_COOLDOWN_SECONDS = int(os.getenv("CHAOS_COOLDOWN_SECONDS", 5)) # Cooldown between chaos actions
        self.MAX_LATENCY_MS = int(os.getenv("MAX_LATENCY_MS", 500)) # Max acceptable p95 latency
        
        # Validation
        if self.CPU_LOAD_DURATION < 0:
            raise ValueError("CPU_LOAD_DURATION must be positive")
        if self.MEMORY_MB < 0:
            raise ValueError("MEMORY_MB must be positive")

config = Config()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("chaos-backend")
