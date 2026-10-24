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