import asyncio
import httpx
import time
import random
import uuid
import statistics
from typing import List, Dict, Any

GATEKEEPER_URL = "http://127.0.0.1:8000"
TOTAL_REQUESTS = 200
CONCURRENCY_LIMIT = 20

# Synthetic base data to mutate
BASE_NAMES = [
    ("Ravi", "Kumar"),
    ("Priya", "Sharma"),
    ("Amit", "Patel"),
    ("Neha", "Gupta"),
]
BASE_GENDERS = ["male", "female", "other"]
SENSITIVE_CODES = ["82810-3", "11636-8", "60934-7"]


class ChaosGenerator:
    @staticmethod
    def generate_valid_patient() -> Dict[str, Any]:
        first, last = random.choice(BASE_NAMES)
        return {
            "resourceType": "Patient",
            "identifier": [
                {
                    "system": "https://healthid.ndhm.gov.in",
                    "value": f"{random.randint(1000, 9999)}-{random.randint(1000, 9999)}-{random.randint(1000, 9999)}",
                }
            ],
            "name": [{"use": "official", "family": last, "given": [first]}],
            "gender": random.choice(BASE_GENDERS),
            "birthDate": f"{random.randint(1960, 2000)}-01-01",
        }

    @staticmethod
    def generate_fuzzy_duplicate(base_patient: Dict[str, Any]) -> Dict[str, Any]:
        """Injects typographical noise to test Fellegi-Sunter probabilistic linkage."""
        mutated = base_patient.copy()
        mutated["identifier"] = []
        current_given = mutated["name"][0]["given"][0]
        mutated["name"][0]["given"] = [current_given + current_given[-1]]
        return mutated

    @staticmethod
    def generate_semantic_anomaly() -> Dict[str, Any]:
        """Generates an Observation that violates physiological boundaries."""
        loinc_codes = [
            ("8867-4", "Heart rate", "/min", random.randint(300, 500)),
            ("8310-5", "Body Temperature", "Cel", random.randint(10, 20)),
        ]
        code, display, unit, bad_value = random.choice(loinc_codes)
        return {
            "resourceType": "Observation",
            "status": "final",
            "code": {
                "coding": [
                    {"system": "http://loinc.org", "code": code, "display": display}
                ]
            },
            "subject": {"reference": f"Patient/{random.randint(1, 100)}"},
            "valueQuantity": {
                "value": bad_value,
                "unit": unit,
                "system": "http://unitsofmeasure.org",
                "code": unit,
            },
        }

    @staticmethod
    def generate_privacy_anomaly() -> Dict[str, Any]:
        """Generates an Observation containing restricted reproductive/privacy codes."""
        code = random.choice(SENSITIVE_CODES)
        return {
            "resourceType": "Observation",
            "status": "final",
            "code": {
                "coding": [
                    {
                        "system": "http://loinc.org",
                        "code": code,
                        "display": "Restricted Privacy Data",
                    }
                ]
            },
            "subject": {"reference": f"Patient/{random.randint(1, 100)}"},
            "valueString": "Patient reports sensitive symptoms.",
        }


async def fire_request(
    client: httpx.AsyncClient, semaphore: asyncio.Semaphore, payload: Dict[str, Any]
) -> Dict[str, Any]:
    """Sends a single request through the proxy and measures latency."""
    resource_type = payload["resourceType"]
    url = f"{GATEKEEPER_URL}/{resource_type}"

    async with semaphore:
        start_time = time.perf_counter()
        try:
            response = await client.post(
                url, json=payload, headers={"Content-Type": "application/fhir+json"}
            )
            status = response.status_code
        except Exception as e:
            status = 500

        latency = (time.perf_counter() - start_time) * 1000  # Convert to milliseconds
        return {"status": status, "latency": latency, "type": resource_type}


async def run_benchmark():
    print(f"🚀 Starting Chaos Benchmark against FHIR Gatekeeper")
    print(
        f"Targeting: {GATEKEEPER_URL} | Total Requests: {TOTAL_REQUESTS} | Concurrency: {CONCURRENCY_LIMIT}"
    )

    # 1. Generate Test Data Distribution
    # 40% Valid Patients, 20% Fuzzy Duplicates, 20% Semantic Anomalies, 20% Privacy Anomalies
    payloads = []
    base_patients = [
        ChaosGenerator.generate_valid_patient() for _ in range(TOTAL_REQUESTS // 5 * 2)
    ]
    payloads.extend(base_patients)
    payloads.extend(
        [
            ChaosGenerator.generate_fuzzy_duplicate(random.choice(base_patients))
            for _ in range(TOTAL_REQUESTS // 5)
        ]
    )
    payloads.extend(
        [ChaosGenerator.generate_semantic_anomaly() for _ in range(TOTAL_REQUESTS // 5)]
    )
    payloads.extend(
        [ChaosGenerator.generate_privacy_anomaly() for _ in range(TOTAL_REQUESTS // 5)]
    )

    random.shuffle(payloads)

    # 2. Execute Requests Concurrently
    semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)
    results = []

    start_time = time.perf_counter()
    async with httpx.AsyncClient(timeout=30.0) as client:
        tasks = [fire_request(client, semaphore, p) for p in payloads]
        results = await asyncio.gather(*tasks)

    total_time = time.perf_counter() - start_time

    # 3. Compute Metrics
    latencies = [r["latency"] for r in results if r["status"] != 500]
    latencies.sort()

    status_counts = {}
    for r in results:
        status_counts[r["status"]] = status_counts.get(r["status"], 0) + 1

    print("\n" + "=" * 50)
    print("📊 BENCHMARK RESULTS")
    print("=" * 50)
    print(f"Total Execution Time:  {total_time:.2f} seconds")
    print(f"Throughput:            {TOTAL_REQUESTS / total_time:.2f} req/sec")
    print("\n--- Latency Distribution ---")
    if latencies:
        print(f"p50 (Median):          {statistics.median(latencies):.2f} ms")
        print(f"p95:                   {latencies[int(len(latencies)*0.95)]:.2f} ms")
        print(f"p99:                   {latencies[int(len(latencies)*0.99)]:.2f} ms")

    print("\n--- HTTP Status Breakdown ---")
    print(f"202 Accepted (Redis Queued):           {status_counts.get(202, 0)}")
    print(f"409 Conflict (EMPI Rejections):        {status_counts.get(409, 0)}")
    print(f"422 Unprocessable (Semantic Fails):    {status_counts.get(422, 0)}")
    print(f"451 Unavailable (Privacy Blocked):     {status_counts.get(451, 0)}")
    print(
        f"50x Errors (Proxy/Target Fails):       {status_counts.get(500, 0) + status_counts.get(502, 0)}"
    )
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(run_benchmark())
