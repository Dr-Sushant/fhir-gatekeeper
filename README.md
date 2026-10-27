# FHIR Gatekeeper

A high-performance clinical data governance and semantic interceptor middleware built with FastAPI, Redis, and Python. This service acts as a reverse proxy in front of clinical data lakes (e.g., HAPI FHIR), intercepting payloads to enforce strict identity resolution, semantic provenance, and enterprise privacy consent before data persistence.

## Core Capabilities

* **Identity Governance (EMPI):** Probabilistic and deterministic patient matching (powered by DuckDB) that intercepts and rejects duplicate identities with HTTP 409 Conflicts.
* **Semantic Provenance Matrix:** Enforces authoritative data hierarchy (e.g., Core Lab > Pharmacy > Patient App) to prevent lower-tier systems from silently overwriting critical clinical observations.
* **Asynchronous Trickle Queue:** Uses Redis to buffer validated payloads, decoupling the high-speed proxy from the slower downstream FHIR database to prevent connection timeouts and Hibernate crashes.
* **High-Throughput Connection Pooling:** Optimized ASGI architecture utilizing global HTTP client pools and thread-offloaded CPU tasks to sustain >100 req/sec with sub-second p99 latency.

## Architecture & Performance

The middleware utilizes a "Sprint-and-Handoff" architecture. Incoming requests are synchronously validated against business rules and asynchronously dispatched to a Redis queue. 

**Benchmark Metrics (Local Hardware):**
* **Throughput:** ~127 requests/second
* **p50 Latency:** ~92 ms
* **p99 Latency:** ~256 ms
* **Error Rate:** 0.0% (Zero 50x errors under concurrent load)

## Getting Started

1. **Start the Infrastructure:** 
   Ensure your local Redis and HAPI FHIR instances are running.
   `docker-compose up -d`
2. **Launch the Proxy:**
   `python main.py`
3. **Run the Benchmark:**
   Execute the included test suite to verify concurrent routing and conflict rejection.
   `python chaos_benchmarker.py`

## Affiliations
Developed by Dr. Sushant (Steth2Tech / Independent Researcher) to bridge the gap between theoretical AI models and real-world hospital workflows by preventing upstream model failures and clinical alarm fatigue.
