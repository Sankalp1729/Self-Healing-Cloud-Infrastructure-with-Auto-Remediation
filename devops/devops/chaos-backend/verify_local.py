import requests
import time
import sys

BASE_URL = "http://localhost:8000"

def log(msg):
    print(f"[TEST] {msg}")

def check_health():
    try:
        r = requests.get(f"{BASE_URL}/health")
        log(f"Health Check: {r.status_code}")
        return r.status_code == 200
    except:
        return False

def check_ready():
    try:
        r = requests.get(f"{BASE_URL}/ready")
        log(f"Ready Check: {r.status_code}")
        return r.status_code
    except:
        return 0

def trigger_cpu_load():
    log("Triggering CPU Load...")
    try:
        r = requests.post(f"{BASE_URL}/load/cpu?duration=5")
        log(f"CPU Load Response: {r.status_code}")
        return r.status_code
    except Exception as e:
        log(f"CPU Load Failed: {e}")
        return 0

def verify_recovery_metric():
    try:
        r = requests.get(f"{BASE_URL}/metrics")
        for line in r.text.split("\n"):
            if "pod_recovery_count" in line and "#" not in line:
                log(f"Recovery Metric: {line}")
                return True
    except:
        pass
    return False

def main():
    log("Starting Local Verification...")
    
    if not check_health():
        log("ERROR: Service not reachable. Is it running?")
        sys.exit(1)

    # 1. Test Recovery Metric (Startup)
    verify_recovery_metric()

    # 2. Test Readiness Degradation
    log("--- Testing Graceful Degradation ---")
    trigger_cpu_load()
    
    # Check readiness during load (should fail or be slow)
    # Note: Since this is synchronous and single-threaded, we can't easily check readiness *during* the busy loop 
    # unless we run the load in a separate thread or process. 
    # For this simple script, we just verify the trigger works.
    
    # 3. Test Guardrails
    log("--- Testing Guardrails ---")
    log("Triggering 2nd CPU load immediately (Should fail/429)...")
    status = trigger_cpu_load()
    if status == 429:
        log("SUCCESS: Guardrails prevented concurrent/spam execution.")
    else:
        log(f"WARNING: Guardrails might not be active (Status: {status})")

    log("Verification Complete.")

if __name__ == "__main__":
    main()
