# Chaos Backend - Architecture & Project Guide

This document provides a comprehensive deep-dive into the **Chaos Backend** project. It explains the purpose of the system, the theoretical foundations of self-healing, and the architectural proof of claims.

---

## 1. Project Purpose: Why does this exist?

This project is a **"Self-Healing Validation Laboratory"**.

In modern DevOps/SRE, we rely on orchestrators (like Kubernetes) to automatically fix problems:
*   If an app crashes -> **Restart it.**
*   If CPU spikes -> **Scale it out.**
*   If a service is overloaded -> **Stop sending traffic (Readiness Probe).**

**The Problem**: How do you *know* these mechanisms work? How do you measure *how fast* they work?

**The Solution**: This project provides:
1.  A **Target Application** that can break on demand (Chaos Backend).
2.  A **Stress Tester** that triggers these breaks (Chaos Generator).
3.  **Observability Tools** that measure the recovery time (Prometheus/Grafana/Scorecards).

---

## 2. High-Level Architecture Diagram

```mermaid
graph TD
    subgraph "Control Plane (User/CI)"
        User[User / CI Pipeline]
        Gen[Chaos Generator (chaos_generator.py)]
        Dash[Dashboard (simple_dashboard.py)]
    end

    subgraph "Target System (Chaos Backend)"
        API[FastAPI App (app/main.py)]
        Health[Health Checks (app/health)]
        Metrics[Prometheus Metrics (app/metrics)]
        Chaos[Chaos Logic (app/chaos)]
    end

    subgraph "Observability"
        Prom[Prometheus (Time Series DB)]
        Grafana[Grafana (Visualization)]
    end

    User -->|Runs| Gen
    User -->|Views| Dash
    Gen -->|1. Trigger Failure (POST /load)| API
    Gen -->|2. Poll Status (GET /ready)| API
    API -->|Uses| Chaos
    API -->|Updates| Metrics
    Metrics -->|Scraped by| Prom
    Prom -->|Query| Dash
    Prom -->|Query| Grafana
```

---

## 3. Self-Healing Taxonomy

This section defines the three distinct levels of self-healing validated by the system.

### Level 1: Traffic Self-Healing (Load Shedding)

The first line of defense. The application signals it is temporarily overwhelmed but still functional. Kubernetes stops sending new traffic until the application recovers.

*   **Trigger**: High CPU usage, High Memory usage (below OOM limit), or High Latency (p95 > threshold).
*   **Kubernetes Mechanism**: **Readiness Probe** (`readinessProbe`).
*   **Action**: Kubernetes removes the Pod IP from the Service's Endpoints list.
*   **Metric**: `readiness_failure_to_recovery_seconds` (Time from 503 -> 200).
*   **User Impact**: Reduced. Users are routed to other healthy pods; the stressed pod recovers faster without traffic.

### Level 2: Process Self-Healing (Restart)

The second line of defense. The application is broken, deadlocked, or in an unrecoverable state. The only fix is a restart.

*   **Trigger**: Deadlock, infinite loop, critical component failure, or explicit crash.
*   **Kubernetes Mechanism**: **Liveness Probe** (`livenessProbe`) or Container Exit.
*   **Action**: Kubelet kills the container and starts a new one (Restart Policy: Always).
*   **Metric**: `crash_to_startup_seconds` (Time from crash -> Application startup).
*   **User Impact**: Temporary error (503) until a new pod is ready, or no impact if other replicas exist.

### Level 3: Capacity Self-Healing (Scaling)

The third line of defense. The aggregate demand exceeds the aggregate capacity of the current replica set.

*   **Trigger**: Sustained high CPU or Memory usage across all pods.
*   **Kubernetes Mechanism**: **Horizontal Pod Autoscaler (HPA)**.
*   **Action**: HPA updates the `replicas` count in the Deployment.
*   **Metric**: `kube_hpa_spec_target_metric` (vs actual) / Replica count over time.
*   **User Impact**: Latency may increase temporarily until new pods join the load balancer.

---

## 4. Self-Healing Validation Model

This section outlines the **Failure → Detection → Decision → Recovery → Verification** loop implemented in the Chaos Backend.

### The Self-Healing Loop

For every failure mode, Kubernetes and the application work together to complete this cycle:

1.  **Failure**: A fault is injected (e.g., CPU spike, Crash).
2.  **Detection**: Probes (Liveness/Readiness) or Metrics identify the issue.
3.  **Decision**: Kubernetes Control Plane decides on an action (Restart, Scale, Isolate).
4.  **Recovery**: The system executes the action to restore health.
5.  **Verification**: Metrics confirm that the system is back to a healthy state.

### Failure Scenarios & Verification

#### 1. Process Crash (Auto-Restart)
*   **Trigger**: `POST /crash`
*   **Detection**: Kubelet sees container exit code `1`. Liveness probe fails.
*   **Decision**: Restart Policy `Always` triggers.
*   **Recovery**: Kubelet restarts the container.
*   **Verification**: `pod_recovery_count` metric increments.

#### 2. CPU Saturation (Auto-Scaling & Shedding)
*   **Trigger**: `POST /load/cpu`
*   **Detection**: App detects `is_cpu_stressed = True` (Internal) / Metric Server reports CPU > 60% (External).
*   **Decision**: Readiness Fails (503) -> Traffic Shedding. HPA -> Scale Up.
*   **Recovery**: Traffic stops flowing to the stressed pod. New pods spin up.
*   **Verification**: `failure_to_readiness_failure_seconds` records detection speed. `kubectl get hpa` shows replica increase.

#### 3. Memory Leak (OOM Kill)
*   **Trigger**: `POST /load/memory`
*   **Detection**: App detects usage > `MAX_MEMORY_MB_READY`. Kernel detects OOM.
*   **Decision**: Readiness: Isolate pod. OOM: Restart pod.
*   **Recovery**: Process restarts with fresh memory.
*   **Verification**: `kubectl get pods` status `OOMKilled`.

#### 4. High Latency (Performance Degradation)
*   **Trigger**: High traffic or resource contention.
*   **Detection**: `latency_monitor.py` detects p95 latency > `MAX_LATENCY_MS`.
*   **Decision**: Readiness probe fails (503).
*   **Recovery**: Traffic is routed to other healthy pods.
*   **Verification**: `readiness_failure_to_recovery_seconds` tracks duration of degradation.

---

## 5. Evidence Map: Claim vs. Proof

This table maps every architectural claim to its observable evidence, ensuring senior-level defensibility of the system.

| Claim | Observable Evidence | Verification Command / Metric |
| :--- | :--- | :--- |
| **Pod restarts on crash** | Kubernetes increments restart count; App increments internal recovery counter. | `kubectl get pods` (Restarts > 0)<br>`prom_http_requests_total{endpoint="/crash"}` |
| **Traffic removed under stress** | Readiness probe returns 503; Endpoints list shrinks. | `curl -v /ready` returns 503<br>`kubectl get endpoints chaos-backend` (IP removed) |
| **Recovery confirmed** | Readiness probe returns 200; Metric records TTR. | `readiness_failure_to_recovery_seconds_bucket`<br>Logs: "Readiness flipped from 503 -> 200" |
| **Auto-scaling works** | HPA increases replica count under load. | `kubectl get hpa`<br>`kubectl get deployment chaos-backend` |
| **Latency protection** | Readiness fails when p95 latency exceeds threshold. | Log: "High latency: p95=... > 500ms"<br>Grafana: "Readiness Status" panel drops to 0 |

---

## 6. Detailed File Breakdown

### A. The Core Application (`app/`)
This is the service we are trying to break. It's a Python FastAPI application.

| File | Role | Description |
| :--- | :--- | :--- |
| `app/main.py` | **Entry Point** | The heart of the app. Initializes FastAPI, loads config, and starts the server. |
| `app/api.py` | **Routes** | Defines the endpoints (`/health`, `/ready`, `/load/cpu`). Connects HTTP requests to chaos logic. |
| `app/config.py` | **Configuration** | Loads environment variables (e.g., `CPU_LOAD_DURATION`, `MAX_MEMORY`). Single source of truth for settings. |
| `app/chaos/__init__.py` | **Chaos Logic** | Contains the actual code that "breaks" things (e.g., infinite loops for CPU stress, memory allocators). |
| `app/health/latency_monitor.py` | **Self-Defense** | Tracks request latency. If the app gets too slow, this module tells the `/ready` endpoint to return 503 (fail). |
| `app/metrics/timing.py` | **Stopwatch** | Measuring "Time to Recovery" (TTR). It records when the app broke and when it recovered into Prometheus histograms. |
| `app/logging/recovery_logger.py` | **Audit Trail** | precise JSON logging for every recovery event, useful for debugging. |

### B. The Chaos Tools (Root Directory)
Scripts used to control the experiment.

| File | Role | Description |
| :--- | :--- | :--- |
| `chaos_generator.py` | **The Hammer** | The main tool you use. It loops through: Trigger Chaos -> Wait for Fail -> Wait for Fix -> Record Time. |
| `analyze_recovery.py` | **The Scorecard** | Reads metrics from the app and calculates the "SLA Score" (e.g., "95% of recoveries were < 10s"). |
| `simple_dashboard.py` | **The View** | A lightweight web dashboard (FastAPI + Chart.js) that visualizes metrics in real-time without needing Docker. |
| `generate_recovery_data.py` | **Helper** | A simpler script just to generate some dummy data for testing the analyzer. |

### C. Deployment & Infrastructure
Files for running the project in different environments.

| File | Role | Description |
| :--- | :--- | :--- |
| `Dockerfile` | **Packaging** | Instructions to build the app into a container image (`python:3.11-slim`). |
| `docker-compose.yml` | **Local Stack** | Defines the full stack (App + Prometheus + Grafana) for local testing with Docker. |
| `k8s/deployment.yaml` | **K8s Deploy** | How to run the app in Kubernetes (replicas, resource limits). |
| `k8s/service.yaml` | **Networking** | Exposes the app inside the cluster. |
| `k8s/hpa.yaml` | **Auto-Scaling** | Rules for Horizontal Pod Autoscaling (e.g., "If CPU > 50%, add pods"). |
| `requirements.txt` | **Deps** | Python libraries needed (fastapi, uvicorn, prometheus-client, etc.). |

### D. Documentation & Configs
| File | Role | Description |
| :--- | :--- | :--- |
| `README.md` | **Manual** | The main instruction manual for the project. |
| `ARCHITECTURE.md` | **Theory** | This document. Detailed theory and validation proofs. |
| `grafana_dashboard.json` | **Viz Config** | A pre-built dashboard layout that can be imported into Grafana. |
| `prometheus.yml` | **Scrape Config** | Tells Prometheus where to find the app's metrics (`localhost:8000`). |

---

## 7. The Data Flow: How it all connects

Let's trace a single "CPU Load" experiment:

1.  **Trigger**: You run `python chaos_generator.py`.
2.  **Request**: The script sends `POST /load/cpu` to `app/api.py`.
3.  **Action**: `app/chaos` starts a thread that burns CPU for 5 seconds.
4.  **Reaction**:
    *   The app becomes slow.
    *   `app/health/latency_monitor.py` detects high latency.
    *   `GET /ready` starts returning **503 Service Unavailable**.
5.  **Metric Recording**:
    *   `app/metrics/timing.py` notes the time the failure started.
6.  **Recovery**:
    *   The 5-second CPU task finishes.
    *   Latency drops.
    *   `GET /ready` returns **200 OK**.
7.  **Observation**:
    *   `chaos_generator.py` sees the 200 OK and calculates the duration.
    *   `app/metrics/timing.py` records the duration into a Prometheus Histogram.
8.  **Visualization**:
    *   `simple_dashboard.py` polls the metrics endpoint and updates the chart.
