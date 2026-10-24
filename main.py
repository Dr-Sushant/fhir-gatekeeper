import logging
import asyncio
import json
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
import httpx
from cachetools import TTLCache
import redis.asyncio as redis

from empi import EMPIEngine
from semantics import SemanticRulesEngine, violates_privacy_consent

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("FHIR-Gatekeeper")

app = FastAPI(
    title="FHIR Gatekeeper (Async Enterprise Edition)",
    description="Clinical Data Governance & Semantic Interceptor Middleware with Redis Queue",
    version="1.0.0",
)

TARGET_FHIR_SERVER = "http://localhost:8080/fhir"
empi = EMPIEngine(match_threshold=0.85, review_threshold=0.60)
semantics = SemanticRulesEngine()

# Connect to our new Dockerized Redis
redis_client = redis.Redis(host="localhost", port=6379, decode_responses=True)
patient_cache = TTLCache(maxsize=1, ttl=60.0)


async def fetch_existing_patients(client: httpx.AsyncClient) -> list:
    """Queries downstream HAPI FHIR with a 60-second TTL cache."""
    if "population" in patient_cache:
        return patient_cache["population"]
    try:
        res = await client.get(f"{TARGET_FHIR_SERVER}/Patient?_count=50")
        if res.status_code == 200:
            patients = [
                e.get("resource")
                for e in res.json().get("entry", [])
                if "resource" in e
            ]
            patient_cache["population"] = patients
            return patients
    except Exception as e:
        logger.warning(f"Could not retrieve existing patients: {e}")
    return []


async def redis_worker():
    """Background task that trickles validated payloads from Redis to HAPI FHIR."""
    logger.info(
        "🚀 Background Redis worker started. Listening for validated FHIR payloads..."
    )
    async with httpx.AsyncClient(timeout=30.0) as client:
        while True:
            try:
                # Block until a payload enters the queue (timeout 1s to allow graceful shutdown checks)
                result = await redis_client.blpop("fhir_write_queue", timeout=1)
                if result:
                    _, payload_str = result
                    task_data = json.loads(payload_str)
                    resource_type = task_data["resourceType"]
                    payload = task_data["payload"]

                    upstream_url = f"{TARGET_FHIR_SERVER}/{resource_type}"
                    await client.post(
                        upstream_url,
                        json=payload,
                        headers={"Content-Type": "application/fhir+json"},
                    )
                    # Add a 50ms buffer between database writes to prevent HAPI Hibernate crashes
                    await asyncio.sleep(0.05)
            except Exception as e:
                logger.error(f"Worker ingestion error: {e}")
                await asyncio.sleep(1)


@app.on_event("startup")
async def startup_event():
    """Launch the background worker when FastAPI starts."""
    asyncio.create_task(redis_worker())


@app.post("/{resource_type}")
async def intercept_fhir_post(resource_type: str, request: Request):
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    if payload.get("resourceType") != resource_type:
        raise HTTPException(status_code=400, detail="Resource type mismatch.")

    # =========================================================
    # STAGE 2: EMPI Identity Resolution (Patient Gate)
    # =========================================================
    if resource_type == "Patient":
        async with httpx.AsyncClient(timeout=10.0) as client:
            existing_records = await fetch_existing_patients(client)
            resolution = empi.evaluate_candidate(payload, existing_records)

            if resolution["decision"] in ["EXACT_MATCH", "PROBABILISTIC_DUPLICATE"]:
                return JSONResponse(
                    status_code=409,
                    content={
                        "resourceType": "OperationOutcome",
                        "issue": [
                            {
                                "severity": "error",
                                "code": "duplicate",
                                "diagnostics": "Identity Governance Rejection: Duplicate identity detected.",
                            }
                        ],
                    },
                )

    # =========================================================
    # STAGE 3: Semantic Plausibility & CDS (Observation Gate)
    # =========================================================
    if resource_type == "Observation":
        eval_result = semantics.evaluate_observation(payload)
        if not eval_result["valid"]:
            return JSONResponse(
                status_code=422,
                content={
                    "resourceType": "OperationOutcome",
                    "issue": [
                        {
                            "severity": "error",
                            "code": "business-rule",
                            "diagnostics": eval_result["diagnostics"],
                        }
                    ],
                },
            )

    # =========================================================
    # STAGE 3.5: Privacy & Consent Gate
    # =========================================================
    if violates_privacy_consent(payload, patient_consent_active=False):
        return JSONResponse(
            status_code=451,
            content={
                "resourceType": "OperationOutcome",
                "issue": [
                    {
                        "severity": "error",
                        "code": "security",
                        "diagnostics": "Payload quarantined: violates active enterprise privacy directives.",
                    }
                ],
            },
        )

    # =========================================================
    # STAGE 4: Asynchronous Dispatch via Redis
    # =========================================================
    task_data = {"resourceType": resource_type, "payload": payload}
    await redis_client.rpush("fhir_write_queue", json.dumps(task_data))

    return JSONResponse(
        status_code=202,
        content={
            "resourceType": "OperationOutcome",
            "issue": [
                {
                    "severity": "information",
                    "code": "informational",
                    "diagnostics": "Payload validated successfully. Queued in Redis for asynchronous persistence to HAPI FHIR.",
                }
            ],
        },
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
