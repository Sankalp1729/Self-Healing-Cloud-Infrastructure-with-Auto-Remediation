import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
import requests
import re
import statistics

app = FastAPI()

CHAOS_BACKEND_URL = "http://localhost:8000/metrics"

def fetch_and_parse_metrics():
    try:
        response = requests.get(CHAOS_BACKEND_URL)
        response.raise_for_status()
        metrics_text = response.text
    except Exception as e:
        return {"error": str(e)}

    # Parse Histogram
    buckets = {}
    count = 0
    sum_val = 0
    
    for line in metrics_text.splitlines():
        if line.startswith("#"): continue
        
        if "readiness_failure_to_recovery_seconds_bucket" in line:
            match = re.search(r'le="([0-9.]+)"', line)
            if match:
                le = float(match.group(1))
                val = float(line.split()[-1])
                buckets[le] = val
            elif 'le="+Inf"' in line:
                val = float(line.split()[-1])
                buckets[float('inf')] = val
        elif "readiness_failure_to_recovery_seconds_count" in line:
            count = float(line.split()[-1])
        elif "readiness_failure_to_recovery_seconds_sum" in line:
            sum_val = float(line.split()[-1])

    # Calculate Stats
    avg = sum_val / count if count > 0 else 0
    
    # SLA (< 10s)
    sla_count = 0
    sorted_keys = sorted(buckets.keys())
    for le in sorted_keys:
        if le <= 10.0:
            sla_count = buckets[le]
        elif le > 10.0:
            if 10.0 in buckets:
                sla_count = buckets[10.0]
            break
            
    sla_percent = (sla_count / count * 100) if count > 0 else 0
    
    # Tail
    tail_count = 0
    if len(sorted_keys) >= 2:
        inf_val = buckets.get(float('inf'), 0)
        max_defined_val = buckets.get(sorted_keys[-2], 0)
        tail_count = inf_val - max_defined_val

    # Histogram Data Preparation
    buckets_list = [{"le": str(k), "count": int(v)} for k, v in buckets.items() if k != float('inf')]
    
    # Calculate Percentiles (Approximate from buckets)
    def calculate_percentile(target_percentile):
        if count == 0: return 0
        target_rank = count * target_percentile
        
        prev_count = 0
        prev_le = 0
        
        for le in sorted_keys:
            curr_count = buckets[le]
            if curr_count >= target_rank:
                # Linear interpolation
                # fraction of the bucket needed
                needed = target_rank - prev_count
                bucket_width = le - prev_le
                bucket_count = curr_count - prev_count
                
                if bucket_count == 0: return le
                
                fraction = needed / bucket_count
                # Handle +Inf
                if le == float('inf'):
                    return prev_le + 10 # Arbitrary fallback for +Inf
                
                return prev_le + (fraction * bucket_width)
            
            prev_count = curr_count
            prev_le = le
        return 0

    p50 = calculate_percentile(0.50)
    p95 = calculate_percentile(0.95)

    # Status Logic
    if sla_percent >= 95:
        status_color = "#4caf50" # Green
        status_text = "PASS"
    elif count < 10:
        status_color = "#9e9e9e" # Grey
        status_text = "INCONCLUSIVE (<10 samples)"
    else:
        status_color = "#f44336" # Red
        status_text = "WARNING"

    return {
        "total_recoveries": int(count),
        "avg_recovery_s": round(avg, 2),
        "p50_recovery_s": round(p50, 2),
        "p95_recovery_s": round(p95, 2),
        "sla_compliance_pct": round(sla_percent, 1),
        "tail_events": int(tail_count),
        "buckets": buckets_list,
        "status_text": status_text,
        "status_color": status_color
    }

@app.get("/api/stats")
def get_stats():
    return JSONResponse(content=fetch_and_parse_metrics())

@app.get("/", response_class=HTMLResponse)
def get_dashboard():
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Self-Healing Dashboard</title>
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <style>
            body { font-family: -apple-system, system-ui, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; background: #1a1a1a; color: #e0e0e0; margin: 0; padding: 20px; transition: all 0.3s; }
            .container { max-width: 1200px; margin: 0 auto; }
            .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 30px; border-bottom: 1px solid #333; padding-bottom: 20px; }
            .context-panel { background: #333; padding: 15px; border-radius: 6px; margin-bottom: 20px; font-size: 13px; color: #ccc; border-left: 4px solid #00bcd4; }
            .card-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin-bottom: 30px; }
            .card { background: #2d2d2d; padding: 20px; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }
            .card h3 { margin: 0 0 10px 0; color: #aaa; font-size: 14px; text-transform: uppercase; }
            .card .value { font-size: 32px; font-weight: bold; color: #fff; transition: color 0.5s; }
            .card .sub { font-size: 12px; color: #888; margin-top: 5px; }
            .chart-container { background: #2d2d2d; padding: 20px; border-radius: 8px; height: 400px; }
            .status-badge { padding: 5px 10px; border-radius: 4px; color: white; font-weight: bold; background: #444; transition: background 0.5s; }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>Self-Healing Recovery Dashboard</h1>
                <div>Status: <span id="status-badge" class="status-badge">LOADING...</span></div>
            </div>

            <div class="context-panel">
                <strong>Validation Context:</strong> Metrics reflect controlled chaos failure injections. 
                SLA Target: 95% < 10s. Tail latency analysis enabled.
            </div>

            <div class="card-grid">
                <div class="card">
                    <h3>Total Recoveries</h3>
                    <div id="val-total" class="value">--</div>
                    <div class="sub">Events</div>
                </div>
                <div class="card">
                    <h3>p50 Recovery</h3>
                    <div id="val-p50" class="value">--</div>
                    <div class="sub">Median Time</div>
                </div>
                <div class="card">
                    <h3>p95 Recovery</h3>
                    <div id="val-p95" class="value">--</div>
                    <div class="sub" style="border-top: 1px solid #444; padding-top:4px;">Target: < 10s</div>
                </div>
                <div class="card">
                    <h3>SLA Compliance</h3>
                    <div id="val-sla" class="value">--</div>
                    <div class="sub">Recoveries under 10s</div>
                </div>
                <div class="card">
                    <h3>Tail Outliers</h3>
                    <div id="val-tail" class="value">--</div>
                    <div class="sub">Events > Max Bucket</div>
                </div>
            </div>

            <div class="chart-container">
                <canvas id="histogramChart"></canvas>
            </div>
        </div>

        <script>
            let chartInstance = null;

            async function updateDashboard() {
                try {
                    const response = await fetch('/api/stats');
                    const data = await response.json();

                    if (data.error) return;

                    // Update Status
                    const badge = document.getElementById('status-badge');
                    badge.textContent = data.status_text;
                    badge.style.backgroundColor = data.status_color;

                    // Update Values
                    document.getElementById('val-total').textContent = data.total_recoveries;
                    document.getElementById('val-p50').textContent = data.p50_recovery_s + 's';
                    
                    const p95El = document.getElementById('val-p95');
                    p95El.textContent = data.p95_recovery_s + 's';
                    p95El.style.color = data.p95_recovery_s > 10 ? '#f44336' : '#4caf50';

                    const slaEl = document.getElementById('val-sla');
                    slaEl.textContent = data.sla_compliance_pct + '%';
                    slaEl.style.color = data.status_color;

                    document.getElementById('val-tail').textContent = data.tail_events;

                    // Update Chart
                    const labels = data.buckets.map(b => '<= ' + b.le + 's');
                    const rawCounts = data.buckets.map(b => b.count);
                    
                    const counts = [];
                    let prev = 0;
                    for (let c of rawCounts) {
                        counts.push(c - prev);
                        prev = c;
                    }

                    if (chartInstance) {
                        chartInstance.data.labels = labels;
                        chartInstance.data.datasets[0].data = counts;
                        chartInstance.update('none');
                    } else {
                        const ctx = document.getElementById('histogramChart').getContext('2d');
                        chartInstance = new Chart(ctx, {
                            type: 'bar',
                            data: {
                                labels: labels,
                                datasets: [{
                                    label: 'Recovery Events Distribution',
                                    data: counts,
                                    backgroundColor: 'rgba(54, 162, 235, 0.6)',
                                    borderColor: 'rgba(54, 162, 235, 1)',
                                    borderWidth: 1
                                }]
                            },
                            options: {
                                responsive: true,
                                maintainAspectRatio: false,
                                animation: { duration: 500 },
                                scales: {
                                    y: {
                                        beginAtZero: true,
                                        grid: { color: '#444' },
                                        ticks: { color: '#aaa' }
                                    },
                                    x: {
                                        grid: { display: false },
                                        ticks: { color: '#aaa' }
                                    }
                                },
                                plugins: {
                                    legend: { labels: { color: '#fff' } },
                                    annotation: {
                                        annotations: {
                                            line1: {
                                                type: 'line',
                                                yMin: 0,
                                                yMax: 100,
                                                borderColor: 'rgb(255, 99, 132)',
                                                borderWidth: 2,
                                            }
                                        }
                                    }
                                }
                            }
                        });
                    }

                } catch (e) {
                    console.error("Fetch error:", e);
                }
            }

            updateDashboard();
            setInterval(updateDashboard, 1000);
        </script>
    </body>
    </html>
    """
    return html_content

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=3000)
