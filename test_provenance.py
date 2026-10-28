import json
import os
from datetime import datetime

TRUST_MATRIX = {
    "https://abdm.gov.in/facility/core-lab": 1,
    "https://abdm.gov.in/facility/pharmacy": 2,
    "https://abdm.gov.in/facility/patient-app": 3,
}


def evaluate_provenance(incoming_payload: dict, existing_record: dict) -> dict:
    in_source = incoming_payload.get("meta", {}).get("source", "unknown")
    ex_source = existing_record.get("meta", {}).get("source", "unknown")

    in_tier = TRUST_MATRIX.get(in_source, 99)
    ex_tier = TRUST_MATRIX.get(ex_source, 99)

    if in_tier > ex_tier:
        # Incoming payload is lower authority (higher tier number)
        return {
            "status_code": 409,
            "response": {
                "resourceType": "OperationOutcome",
                "issue": [
                    {
                        "severity": "error",
                        "code": "conflict",
                        "diagnostics": f"Data regression prevented. Incoming source '{in_source}' (Tier {in_tier}) cannot overwrite existing authoritative record from '{ex_source}' (Tier {ex_tier}). Submit as a distinct new Observation.",
                    }
                ],
            },
        }

    return {
        "status_code": 202,
        "response": "Accepted: Payload authorized to update record.",
    }


if __name__ == "__main__":
    # Load the mock payloads
    base_path = os.path.join(os.path.dirname(__file__), "mock_data")
    with open(os.path.join(base_path, "mock_lab_payload.json"), "r") as f:
        lab_data = json.load(f)
    with open(os.path.join(base_path, "mock_pharmacy_payload.json"), "r") as f:
        pharmacy_data = json.load(f)

    # Test: Pharmacy attempting to overwrite Lab
    result = evaluate_provenance(
        incoming_payload=pharmacy_data, existing_record=lab_data
    )
    print(json.dumps(result, indent=2))
