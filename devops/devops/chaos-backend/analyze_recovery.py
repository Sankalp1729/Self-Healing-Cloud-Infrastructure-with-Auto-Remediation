import requests
import re
import sys

METRICS_URL = "http://localhost:8000/metrics"
SLA_THRESHOLD_SECONDS = 10.0
MIN_SAMPLE_COUNT = 10

def fetch_metrics():
    try:
        response = requests.get(METRICS_URL)
        response.raise_for_status()
        return response.text
    except requests.exceptions.RequestException as e:
        print(f"Error fetching metrics: {e}")
        sys.exit(1)

def parse_histogram(metrics_text, metric_name):
    """
    Parses Prometheus histogram data for a specific metric.
    Returns:
        count (float): Total count of observations
        sum_val (float): Sum of all observation values
        buckets (dict): Dictionary mapping upper bound (float) to cumulative count (int)
    """
    count = 0.0
    sum_val = 0.0
    buckets = {}

    for line in metrics_text.splitlines():
        if line.startswith("#"):
            continue
        
        if metric_name + "_count" in line:
            # Example: readiness_failure_to_recovery_seconds_count 5.0
            count = float(line.split()[-1])
        elif metric_name + "_sum" in line:
            # Example: readiness_failure_to_recovery_seconds_sum 12.5
            sum_val = float(line.split()[-1])
        elif metric_name + "_bucket" in line:
            # Example: readiness_failure_to_recovery_seconds_bucket{le="10.0"} 5.0
            match = re.search(r'le="([0-9.]+)"', line)
            if match:
                le = float(match.group(1))
                val = float(line.split()[-1])
                buckets[le] = val
            elif 'le="+Inf"' in line:
                val = float(line.split()[-1])
                buckets[float('inf')] = val

    return count, sum_val, buckets

def analyze_recovery():
    print(f"--- Self-Healing Recovery Scorecard ---")
    print(f"Source: {METRICS_URL}")
    print("-" * 40)

    metrics_text = fetch_metrics()
    metric_name = "readiness_failure_to_recovery_seconds"
    
    count, sum_val, buckets = parse_histogram(metrics_text, metric_name)

    # 1. SAMPLE COUNT AWARENESS
    # Statistics are unreliable with insufficient data points.
    if count == 0:
        print("No recovery events recorded yet.")
        print("Trigger failures (e.g., POST /load/cpu) and wait for recovery to generate data.")
        return

    # 2. Basic Stats
    avg_recovery = sum_val / count
    print(f"Total Recoveries:       {int(count)}")
    print(f"Average Recovery Time:  {avg_recovery:.2f}s")

    # 3. HISTOGRAM SEMANTICS (Observed Upper Bound)
    # Prometheus histograms do not store exact maximums. We can only know that values 
    # fell into the highest populated bucket. The "upper bound" is the limit of that bucket.
    sorted_les = sorted(buckets.keys())
    
    prev_count = 0
    highest_populated_le = 0
    
    for le in sorted_les:
        curr_count = buckets[le]
        if curr_count > prev_count:
            highest_populated_le = le
        prev_count = curr_count
        
    if highest_populated_le == float('inf'):
        print(f"Observed Upper Bound:   > {sorted_les[-2]}s (outlier detected in +Inf bucket)")
    else:
        print(f"Observed Upper Bound:   <= {highest_populated_le}s (Histogram Bucket)")

    # 4. SLA CALCULATION RULES
    # Calculate percentage under threshold regardless of sample count for informational purposes,
    # but reserve judgment/status for sufficient samples.
    sla_count = buckets.get(SLA_THRESHOLD_SECONDS, 0)
    
    # Fallback if exact bucket missing (should match bucket config in timing.py)
    if SLA_THRESHOLD_SECONDS not in buckets:
        for le in sorted_les:
            if le >= SLA_THRESHOLD_SECONDS:
                sla_count = buckets[le]
                break
    
    sla_percentage = (sla_count / count) * 100
    print(f"Recoveries under {SLA_THRESHOLD_SECONDS}s:  {sla_percentage:.1f}%")

    print("-" * 40)

    # 5. STATUS LOGIC
    if count < MIN_SAMPLE_COUNT:
        print("STATUS: INCONCLUSIVE")
        print(f"  Note: Insufficient samples ({int(count)}/{MIN_SAMPLE_COUNT}) for reliable SLA evaluation.")
        print("  Recommendation: Generate more load/failure events.")
    else:
        if sla_percentage >= 95.0:
            print("STATUS: PASS (>= 95% under SLA)")
        else:
            print("STATUS: WARNING (< 95% under SLA)")
            print("\nINTERPRETATION:")
            print("  The system failed to meet the 95% SLA target due to tail latency events.")
            print("  While average performance may be acceptable, outliers (slow recoveries)")
            print("  are impacting overall reliability score. Investigate resource contention")
            print("  or deep outliers in the > 10s histogram buckets.")

if __name__ == "__main__":
    analyze_recovery()
