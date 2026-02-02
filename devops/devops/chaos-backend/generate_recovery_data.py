import requests
import time
import threading

BASE_URL = "http://localhost:8000"

def poll_readiness(stop_event):
    while not stop_event.is_set():
        try:
            r = requests.get(f"{BASE_URL}/ready")
            if r.status_code == 503:
                print(".", end="", flush=True)
            elif r.status_code == 200:
                print("!", end="", flush=True)
        except:
            pass
        time.sleep(0.1)

def flush_latency_window():
    print("\nFlushing latency window...")
    for _ in range(120): # > 100 window size
        try:
            requests.get(f"{BASE_URL}/health")
        except:
            pass
    print("Window flushed.")

def main():
    print("Starting readiness poller...")
    stop_event = threading.Event()
    t = threading.Thread(target=poll_readiness, args=(stop_event,))
    t.start()

    print("Triggering CPU load (2s)...")
    try:
        r = requests.post(f"{BASE_URL}/load/cpu?duration=2")
        print(f"\nTrigger response: {r.status_code}")
    except Exception as e:
        print(f"Load failed: {e}")

    print("Waiting for load to finish...")
    time.sleep(3)
    
    # Flush window to ensure we recover from "High Latency" state
    flush_latency_window()

    print("Waiting for final recovery...")
    time.sleep(1)
    
    # One last check
    r = requests.get(f"{BASE_URL}/ready")
    print(f"\nFinal Readiness: {r.status_code}")
    
    stop_event.set()
    t.join()
    print("Data generation complete.")

if __name__ == "__main__":
    main()
