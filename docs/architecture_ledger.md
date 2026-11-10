# FHIR Gatekeeper: Architecture Ledger

## 1. System Overview
An asynchronous enterprise middleware and semantic interceptor built with FastAPI, Redis, and Python. Designed to enforce clinical-grade EMPI/MDM resolution and NRCES-compliant semantic rules at the ingress layer before data reaches the clinical data lake.

## 2. Core Modules
* **EMPI Identity Resolution:** Ensures longitudinal records remain intact regardless of ABHA token or institutional MRN variations.
* **Semantic Validation & Privacy Gate:** Enforces Stage 3.5 Privacy & Consent rules (yielding HTTP 451 Unavailable for Legal Reasons when consent is withheld).

## 3. Temporal Provenance & Conflict Resolver
Handles data collisions when multiple sources submit updates for the same clinical resource. Evaluates the lightweight `meta.source` URI embedded in the incoming FHIR payload against a hardcoded hierarchy.

### Trust Matrix Tiers
1. **Tier 1 (High Fidelity):** Diagnostic Laboratory (`https://abdm.gov.in/facility/core-lab`)
2. **Tier 2 (Manual/Clinical):** Retail Pharmacy (`https://abdm.gov.in/facility/pharmacy`)
3. **Tier 3 (Patient-Reported):** Mobile App (`https://abdm.gov.in/facility/patient-app`)

### Conflict Resolution Rules
* **Higher/Equal Tier Overwrite:** Allowed. If tiers are equal, the system uses `meta.lastUpdated` as a temporal tie-breaker (newer timestamp wins).
* **Lower Tier Rejection (Data Regression Prevention):** If a lower-tier source attempts to overwrite a higher-tier record, the proxy blocks the transaction.
* **Active Flagging:** Instead of silently dropping the payload, the interceptor returns an **HTTP 409 Conflict** accompanied by a FHIR `OperationOutcome` resource. This explicitly forces the downstream system to submit the data as a brand-new, distinct `Observation` rather than overwriting the authoritative record.

## 4. Local Testbench & Containerization
* Orchestrated via `docker-compose.yml` to run the local FHIR server backend (e.g., HAPI/Medplum) and PostgreSQL for quarantined payload logging without polluting the host machine.

## 5. Chaos Benchmarking & Evaluation
* **Resilience Testing:** `chaos_benchmarker.py` serves as the test suite to evaluate proxy throughput, latency, and stability under simulated API load and payload anomalies.
* **Isolated Mock Data:** Test payloads are strictly isolated in the `mock_data/` directory to prevent cluttering the core Python logic. Routing rules are validated via independent scripts like `test_provenance.py` rather than directly in the API.
* **Concurrency Optimization:** CPU-bound tasks (like probabilistic EMPI matching or heavy semantic validation) must be wrapped in `asyncio.to_thread()` to prevent freezing the FastAPI asynchronous event loop.
* **Connection Pooling:** TCP handshake bottlenecks are eliminated by instantiating a single, persistent `httpx.AsyncClient` globally on server startup. Reusing this connection pool across all asynchronous routes prevents socket exhaustion and sustains >100 req/sec with sub-second p99 latency.

## 6. Downstream Integration: OMOP CDM & ML Tokenization
* **The Three-Stage Clinical AI Engine:** Established the architectural pipeline required for zero-shot ML transfer: Ingress Firewall (FHIR Gatekeeper) -> Structural Warehouse (OMOP CDM) -> Downstream AI Tokenizer (MEDIATOR). Strict upstream physiological governance prevents downstream data poisoning in the model training layer.
* **OMOP Database Sandbox:** Orchestrated a local PostgreSQL 15 container (`omop-db`) on port 5433 and executed the official OHDSI v5.4 DDL to instantiate standard analytical tables (`person`, `measurement`).
* **ETL Engine (`src/fhir_to_omop.py`):** Engineered a Python parser to flatten nested FHIR `Observation` JSON payloads into strict, relational OMOP schemas, mapping LOINC and UCUM codes to standard OMOP Concept IDs.
* **Deterministic Hashing:** Implemented SHA-256 hashing with modulo compression to dynamically translate text-based FHIR identifiers (e.g., `ABHA-12345`) into OMOP-compliant integer primary keys, ensuring longitudinal patient history without requiring stateful lookup tables.
* **Strict Schema Enforcement:** Resolved OMOP relational constraints by engineering deterministic hashing for resource primary keys (`measurement_id`) and explicitly mapping standard OHDSI provenance integers (`measurement_type_concept_id: 32856` for Lab) to guarantee downstream models have exact context on data origins.
* **Pipeline Verification:** Successfully executed end-to-end local sandbox testing, extracting a nested FHIR `Observation`, flattening it via `psycopg2`, and confirming persistent relational storage in the PostgreSQL `measurement` table.
* **Governance in Action (Conflict Resolution):** Validated the active flagging mechanism against data regression. When a lower-tier pharmacy system attempted to overwrite a hemoglobin lab, the proxy returned an HTTP 409 Conflict. This forced the system to submit the embedded physiological data as a distinct `Observation` rather than a merge, preserving the authoritative core lab record while safely capturing clinical data drift.
* **Stage 3 MEDIATOR Tokenizer:** Engineered the final downstream sequence layer bridging relational storage and predictive modeling. The tokenizer queries the OMOP `measurement` table using deterministic `person_id` hashes and isolates physiological events strictly by patient.
* **Chronological Sequence Output:** Successfully extracted a longitudinal timeline for patient hash `2045113149`. The script ordered standard labs alongside the conflict-forced pharmacy observation into a model-ready numerical array (`[3000963:14.2] -> [3000963:12.8] -> [3000963:15.1]`), eliminating natural language parsing from the downstream inference layer.
* **Multi-Domain ETL Routing:** Expanded the pipeline beyond physiological observations to process `MedicationRequest` and `Condition` resources. Engineered explicit parsing rules to map RxNorm codes to the `drug_exposure` table, including fallback logic for mandatory end-date constraints, and routed ICD-10 diagnoses to the `condition_occurrence` table.
* **Structural Idempotency:** Eliminated duplicate batch ingestion vulnerabilities by enforcing `PRIMARY KEY` constraints directly within the containerized `OMOPCDM_postgresql_5.4_ddl.sql` initialization script. This architectural lock guarantees that the `ON CONFLICT DO NOTHING` logic triggers natively at the PostgreSQL engine layer across all fresh deployments.
* **Multimodal Token Sequence Finalization:** Upgraded the Stage 3 MEDIATOR tokenizer to execute cross-table database queries. The engine successfully merged continuous labs (LOINC) with discrete clinical events (RxNorm and ICD-10, mapped to a binary 1.0 indicator) into a single, chronologically ordered patient timeline (`[201826:1.0] -> [3000963:14.2] -> [3000963:12.8] -> [1112807:1.0] -> [3000963:15.1]`).
* **Clinical Plausibility Governance:** Engineered a declarative rules engine to intercept FHIR payloads violating hard physiological boundaries (e.g., Hemoglobin > 30 g/dL or UCUM unit mismatches), preventing impossible clinical data from entering the downstream AI pipeline.
* **JSONB Quarantine Logging:** Architected a `quarantine_log` table in PostgreSQL utilizing the native `JSONB` data type. The ETL router now safely redirects implausible resources out of the OMOP warehouse while preserving the exact raw payload for clinical stewardship review, ensuring zero silent data loss.