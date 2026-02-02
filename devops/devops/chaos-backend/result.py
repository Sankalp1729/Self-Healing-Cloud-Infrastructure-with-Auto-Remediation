--- Self-Healing Recovery Scorecard ---
Source: http://localhost:8000/metrics
----------------------------------------
Total Recoveries:       10
Average Recovery Time:  48.43s
Observed Upper Bound:   > 120.0s (outlier detected in +Inf bucket)
Recoveries under 10.0s:  90.0%
----------------------------------------
STATUS: WARNING (< 95% under SLA)

INTERPRETATION:
  The system failed to meet the 95% SLA target due to tail latency events.
  While average performance may be acceptable, outliers (slow recoveries)
  are impacting overall reliability score. Investigate resource contention
  or deep outliers in the > 10s histogram buckets.
