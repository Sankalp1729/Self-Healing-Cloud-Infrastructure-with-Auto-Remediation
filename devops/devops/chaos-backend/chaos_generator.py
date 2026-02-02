import requests
import time
import argparse
import sys
import datetime
from enum import Enum

# --- CONFIGURATION DEFAULTS ---
DEFAULT_BASE_URL = "http://localhost:8000"
DEFAULT_ITERATIONS = 20
DEFAULT_COOLDOWN_SECONDS = 5
DEFAULT_RECOVERY_TIMEOUT_SECONDS = 30
DEFAULT_CPU_DURATION_SECONDS = 5
DEFAULT_MEMORY_MB = 200

class ChaosType(str, Enum):
    CPU = "cpu"
    MEMORY = "memory"
    CRASH = "crash"

class ChaosGenerator:
    def __init__(self, base_url, iterations, cooldown, timeout, chaos_type):
        self.base_url = base_url.rstrip("/")
        self.iterations = iterations
        self.cooldown = cooldown
        self.timeout = timeout
        self.chaos_type = chaos_type
        
        # Stats
        self.successful_recoveries = 0
        self.failed_recoveries = 0
        self.total_recovery_time = 0.0

    def log(self, msg):
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        print(f"[{timestamp}] {msg}")

    def check_health(self):
        try:
            r = requests.get(f"{self.base_url}/health", timeout=2)
            return r.status_code == 200
        except:
            return False

    def check_readiness(self):
        try:
            r = requests.get(f"{self.base_url}/ready", timeout=2)
            return r.status_code
        except requests.exceptions.RequestException:
            # If the service is restarting (crash scenario), connection might fail
            return 0

    def trigger_chaos(self):
        """Triggers the configured chaos event."""
        try:
            if self.chaos_type == ChaosType.CPU:
                # Trigger CPU load
                url = f"{self.base_url}/load/cpu?duration={DEFAULT_CPU_DURATION_SECONDS}"
                self.log(f"Triggering CPU Load ({DEFAULT_CPU_DURATION_SECONDS}s)...")
                try:
                    requests.post(url, timeout=0.5)
                except requests.exceptions.ReadTimeout:
                    pass # Expected, as the server is busy
                
            elif self.chaos_type == ChaosType.MEMORY:
                # Trigger Memory Leak
                url = f"{self.base_url}/load/memory?mb={DEFAULT_MEMORY_MB}"
                self.log(f"Triggering Memory Leak ({DEFAULT_MEMORY_MB}MB)...")
                try:
                    requests.post(url, timeout=0.5)
                except requests.exceptions.ReadTimeout:
                    pass
                
            elif self.chaos_type == ChaosType.CRASH:
                # Trigger Crash
                url = f"{self.base_url}/crash"
                self.log("Triggering Crash...")
                try:
                    requests.post(url, timeout=2)
                except requests.exceptions.RequestException:
                    # Expected: Crash kills the connection
                    pass
            
            return True
        except Exception as e:
            self.log(f"Failed to trigger chaos: {e}")
            return False

    def wait_for_degradation(self):
        """
        Polls until readiness fails (503) or connection drops.
        Returns True if degradation detected, False if timeout.
        """
        start_time = time.time()
        # For crash, degradation is immediate (connection loss or 503)
        # For load, it might take a moment for metrics to update
        
        while time.time() - start_time < 10: # 10s max to detect degradation
            status = self.check_readiness()
            if status != 200:
                return True
            time.sleep(0.5)
            
        return False

    def flush_latency_window(self, stop_event):
        """Background thread to flush the latency window with fast requests."""
        while not stop_event.is_set():
            try:
                # Use a very short timeout and ignore errors
                requests.get(f"{self.base_url}/health", timeout=0.1)
            except:
                pass
            time.sleep(0.05)

    def wait_for_recovery(self):
        """
        Polls until readiness returns to 200 OK.
        Returns duration in seconds if recovered, None if timed out.
        """
        start_time = time.time()
        
        # Start background flusher to clear latency window
        import threading
        stop_flush = threading.Event()
        flusher = threading.Thread(target=self.flush_latency_window, args=(stop_flush,))
        flusher.start()
        
        try:
            while time.time() - start_time < self.timeout:
                status = self.check_readiness()
                if status == 200:
                    return time.time() - start_time
                time.sleep(0.5)
        finally:
            stop_flush.set()
            flusher.join()
            
        return None

    def run(self):
        self.log(f"--- Starting Chaos Generator ({self.chaos_type.upper()}) ---")
        self.log(f"Target: {self.base_url}")
        self.log(f"Iterations: {self.iterations}")
        
        if not self.check_health():
            self.log("ERROR: Target service is not reachable. Aborting.")
            return

        for i in range(1, self.iterations + 1):
            self.log(f"\n--- Iteration {i}/{self.iterations} ---")
            
            # 1. Trigger Chaos
            if not self.trigger_chaos():
                continue

            # 2. Detect Degradation
            # Note: For CPU load, we expect 503. For Crash, we expect connection error/503.
            if self.wait_for_degradation():
                self.log("Degradation detected (Service Unready/Down). Waiting for recovery...")
                
                # 3. Wait for Recovery
                recovery_duration = self.wait_for_recovery()
                
                if recovery_duration is not None:
                    self.log(f"RECOVERED in {recovery_duration:.2f}s")
                    self.successful_recoveries += 1
                    self.total_recovery_time += recovery_duration
                else:
                    self.log("TIMEOUT waiting for recovery.")
                    self.failed_recoveries += 1
            else:
                self.log("WARNING: No degradation detected. Did chaos trigger?")
                # If no degradation, we don't count it as a recovery event
            
            # 4. Cooldown
            self.log(f"Cooling down for {self.cooldown}s...")
            time.sleep(self.cooldown)

        self.print_summary()

    def print_summary(self):
        print("\n" + "="*40)
        print("CHAOS EXECUTION SUMMARY")
        print("="*40)
        print(f"Chaos Type:           {self.chaos_type.upper()}")
        print(f"Total Iterations:     {self.iterations}")
        print(f"Successful Recoveries: {self.successful_recoveries}")
        print(f"Failed Recoveries:    {self.failed_recoveries}")
        
        if self.successful_recoveries > 0:
            avg_time = self.total_recovery_time / self.successful_recoveries
            print(f"Avg Recovery Time:    {avg_time:.2f}s")
        else:
            print("Avg Recovery Time:    N/A")
        print("="*40)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Chaos Event Generator for Self-Healing Validation")
    parser.add_argument("--url", default=DEFAULT_BASE_URL, help="Target service base URL")
    parser.add_argument("--type", type=ChaosType, default=ChaosType.CPU, choices=list(ChaosType), help="Type of chaos to inject")
    parser.add_argument("--iterations", type=int, default=DEFAULT_ITERATIONS, help="Number of chaos iterations")
    parser.add_argument("--cooldown", type=int, default=DEFAULT_COOLDOWN_SECONDS, help="Cooldown seconds between iterations")
    parser.add_argument("--timeout", type=int, default=DEFAULT_RECOVERY_TIMEOUT_SECONDS, help="Recovery timeout seconds")
    
    args = parser.parse_args()
    
    generator = ChaosGenerator(
        base_url=args.url,
        iterations=args.iterations,
        cooldown=args.cooldown,
        timeout=args.timeout,
        chaos_type=args.type
    )
    
    generator.run()
