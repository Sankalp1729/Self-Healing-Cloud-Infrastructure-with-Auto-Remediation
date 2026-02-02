# Chaos Backend

**A Kubernetes-native chaos backend designed to validate self-healing behaviors including auto-restart, adaptive traffic shedding, and horizontal auto-scaling under controlled CPU, memory, and process failures.**

## Overview

This project is a minimal HTTP backend application that can **intentionally fail** in controlled ways. It is used to demonstrate how orchestrators like Kubernetes handle:
- **Auto-restart**: When the app crashes.
- **Auto-scaling**: When CPU load increases.
- **OOM (Out of Memory) Handling**: When memory usage spikes.
- **Unhealthy instances**: When liveness probes fail.
- **Graceful Degradation**: When readiness probes fail (removing traffic from stressed pods).

## Features

- **Language**: Python (FastAPI)
- **Container**: Dockerized with a minimal `python:3.11-slim` image.
- **Observability**: Prometheus metrics exposed at `/metrics`.
- **Chaos Guardrails**: Enforces cooldowns and concurrency limits to prevent accidental cluster meltdowns.
- **Self-Healing Metrics**: Dedicated histograms tracking TTR (Time to Recovery) and detection speed.
- **Endpoints**:
  - `GET /health`: Returns 200 OK (for Liveness Probes).
  - `GET /ready`: Returns 200 OK or 503 if overloaded. **Crucially, this signal protects users, not infrastructure.** It intentionally fails during high load to trigger Kubernetes traffic shedding, preventing cascading failures without restarting the pod.
  - `GET /metrics`: Prometheus metrics.
  - `POST /load/cpu`: Spikes CPU usage.
  - `POST /load/memory`: Leaks memory intentionally.
  - `POST /crash`: Kills the process immediately.

## Scope & Non-Goals

This system is a **production-grade validation lab** for application- and pod-level self-healing.

**In Scope:**
- Validating Kubernetes **Readiness Probes** for traffic shedding.
- Validating Kubernetes **Liveness Probes** for process recovery.
- Validating **HPA** (Horizontal Pod Autoscaler) reaction times.
- **Controlled fault injection** (CPU, Memory, Crash) to measure recovery metrics.

**Non-Goals (Out of Scope):**
- **Network Chaos**: We do not simulate network partitions or latency between services.
- **Distributed Consistency**: No testing of Raft logs, database transactions, or CAP theorem limits.
- **Control Plane Failure**: We assume the Kubernetes API server and etcd are healthy.
- **Random Production Chaos**: This is a deterministic validation tool, not a "Chaos Monkey" that randomly kills pods in production.

## Configuration

The service is configured via Environment Variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `CPU_LOAD_DURATION` | `10` | Duration (seconds) for CPU load simulation. |
| `MEMORY_MB` | `100` | Amount of memory (MB) to allocate per request. |
| `RANDOM_CRASH_ENABLED` | `false` | (Future) Enable random crashes for chaos engineering. |
| `MAX_MEMORY_MB_READY` | `400` | Memory threshold (MB) before marking pod unready. |
| `MAX_CONCURRENT_CHAOS` | `1` | Max concurrent chaos actions allowed. |
| `CHAOS_COOLDOWN_SECONDS` | `60` | Cooldown period between chaos actions. |
| `MAX_LATENCY_MS` | `500` | Max acceptable p95 latency before failing readiness. |

## Self-Healing Validation Model

See [docs/self_healing_flow.md](docs/self_healing_flow.md) for a detailed breakdown of the **Failure → Detection → Decision → Recovery → Verification** loop.

## Usage

### Prerequisites
- Docker
- Kubernetes Cluster (Minikube, Kind, or Cloud Provider)

### 1. Build Docker Image
```bash
docker build -t chaos-backend:latest .
```

### 2. Deploy to Kubernetes
```bash
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml
# Enable Auto-scaling
kubectl apply -f k8s/hpa.yaml
```

### 3. Validate Self-Healing (The "Engineering" Part)

Use this **Controlled Failure Matrix** to validate your cluster's resilience.

| Failure Type | Trigger | Expected Kubernetes Action | Proof Command |
|--------------|---------|----------------------------|---------------|
| **Process Crash** | `POST /crash` | Pod Restart | `kubectl get pods -w` (Restart count increases) |
| **CPU Saturation** | `POST /load/cpu` | HPA Scales Replicas | `kubectl get hpa` (Replicas increase) |
| **Memory Leak** | `POST /load/memory` | OOMKill + Restart | `kubectl get pods` (Status: OOMKilled) |
| **Degraded Pod** | CPU/Mem Load | Readiness = False | `kubectl get endpoints` (IP removed from service) |

### 4. Verification Commands

**Watch Pods & Events:**
```bash
kubectl get pods -w
kubectl describe pod <pod-name>
```

**Check HPA Scaling:**
```bash
kubectl get hpa
```

**Check Resource Usage:**
```bash
kubectl top pods
```

**Verify Recovery Metric:**
The app exposes `pod_recovery_count` which increments on startup and when recovering from a "Not Ready" state.
```bash
curl http://localhost:8080/metrics | grep pod_recovery_count
```

**Generate Controlled Chaos Events:**
Run the chaos generator to produce statistically significant recovery data:
```bash
# Run 20 iterations of CPU load with 10s cooldown
python chaos_generator.py --type cpu --iterations 20 --cooldown 10
```

**Analyze Recovery Performance:**
Run the analysis script to see Average, Worst-case, and SLA compliance stats:
```bash
python analyze_recovery.py
```

## Grafana Dashboard

A production-ready Grafana dashboard is provided in `grafana_dashboard.json`.

**To Import:**
1.  Open Grafana.
2.  Go to **Dashboards > New > Import**.
3.  Upload `grafana_dashboard.json` or paste the JSON content.
4.  Select your Prometheus data source.

**Visualized Metrics:**
*   **Self-Healing Overview**: Total recoveries, SLA compliance (%), and current readiness state.
*   **Recovery Performance**: Heatmap of recovery times and p50/p95 latency trends.
*   **Reliability Signals**: Tail latency outliers and correlation with CPU stress events.

## How NOT to Demo This Project

To maintain engineering maturity and senior-level defensibility:

1.  **Do NOT Spam Chaos Endpoints**: Real failures happen rarely. Hammering the API obscures the recovery metrics.
2.  **Do NOT Treat Failures as Random**: Every chaos action should have a hypothesis (e.g., "If I spike CPU, HPA should scale in 30s").
3.  **Do NOT Claim Production Chaos Coverage**: This tool validates *single-pod* and *scaling* mechanics. It does not validate multi-region failover or database corruption.

## Project Structure

```
chaos-backend/
├── app/
│   ├── main.py       # Entry point & Middleware
│   ├── api.py        # API endpoints, Chaos Logic & Guardrails
│   ├── config.py     # Configuration management
│   ├── chaos/        # Chaos implementation details
│   ├── health/       # Health checks & Latency monitoring
│   ├── logging/      # Structured recovery logging
│   └── metrics/      # Self-healing timing metrics
├── k8s/
│   ├── deployment.yaml # Kubernetes Deployment manifest
│   ├── service.yaml    # Kubernetes Service manifest
│   └── hpa.yaml        # Horizontal Pod Autoscaler manifest
├── ARCHITECTURE.md     # Detailed Theory & Architecture
├── Dockerfile        # Container definition
├── requirements.txt  # Python dependencies
├── chaos_generator.py # Controlled chaos event generator
├── analyze_recovery.py # Script to calculate recovery stats
├── grafana_dashboard.json # Grafana dashboard definition
└── README.md         # Documentation
```
