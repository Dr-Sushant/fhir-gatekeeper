import psycopg2
import hashlib
import json
import os
import glob
from datetime import datetime
from rules_engine import validate_clinical_plausibility

# Vocabulary Mappings
LOINC_TO_CONCEPT_ID = {"718-7": 3000963}
UNIT_TO_CONCEPT_ID = {"g/dL": 8713}
RXNORM_TO_CONCEPT_ID = {"1191": 1112807}
ICD10_TO_CONCEPT_ID = {"E11.9": 201826}


def generate_person_id(identifier_string):
    hash_obj = hashlib.sha256(identifier_string.encode("utf-8"))
    hash_int = int(hash_obj.hexdigest(), 16)
    return hash_int % (2**31 - 1)


def convert_fhir_date(fhir_date_str):
    if not fhir_date_str:
        return datetime.now().strftime("%Y-%m-%d")
    dt = datetime.strptime(fhir_date_str, "%Y-%m-%dT%H:%M:%SZ")
    return dt.strftime("%Y-%m-%d")


def transform_observation_to_measurement(fhir_json):
    obs_id = fhir_json.get("id", "")
    measurement_id = generate_person_id(obs_id)
    abha_ref = fhir_json.get("subject", {}).get("reference", "").replace("Patient/", "")
    person_id = generate_person_id(abha_ref)
    last_updated = fhir_json.get("meta", {}).get("lastUpdated", "")
    measurement_date = convert_fhir_date(last_updated)
    loinc_code = fhir_json.get("code", {}).get("coding", [{}])[0].get("code", "")
    measurement_concept_id = LOINC_TO_CONCEPT_ID.get(loinc_code, 0)
    value = fhir_json.get("valueQuantity", {}).get("value")
    unit = fhir_json.get("valueQuantity", {}).get("unit")
    unit_concept_id = UNIT_TO_CONCEPT_ID.get(unit, 0)

    return {
        "measurement_id": measurement_id,
        "person_id": person_id,
        "measurement_concept_id": measurement_concept_id,
        "measurement_date": measurement_date,
        "value_as_number": value,
        "unit": unit,
        "unit_concept_id": unit_concept_id,
        "measurement_type_concept_id": 32856,
    }


def transform_medication_to_drug_exposure(fhir_json):
    # [Same as previous]
    med_id = fhir_json.get("id", "")
    drug_exposure_id = generate_person_id(med_id)
    abha_ref = fhir_json.get("subject", {}).get("reference", "").replace("Patient/", "")
    person_id = generate_person_id(abha_ref)
    authored_on = fhir_json.get(
        "authoredOn", fhir_json.get("meta", {}).get("lastUpdated", "")
    )
    drug_exposure_start_date = convert_fhir_date(authored_on)
    rxnorm_code = (
        fhir_json.get("medicationCodeableConcept", {})
        .get("coding", [{}])[0]
        .get("code", "")
    )
    drug_concept_id = RXNORM_TO_CONCEPT_ID.get(rxnorm_code, 0)

    return {
        "drug_exposure_id": drug_exposure_id,
        "person_id": person_id,
        "drug_concept_id": drug_concept_id,
        "drug_exposure_start_date": drug_exposure_start_date,
        "drug_exposure_end_date": drug_exposure_start_date,
        "drug_type_concept_id": 32838,
    }


def transform_condition_to_occurrence(fhir_json):
    # [Same as previous]
    cond_id = fhir_json.get("id", "")
    condition_occurrence_id = generate_person_id(cond_id)
    abha_ref = fhir_json.get("subject", {}).get("reference", "").replace("Patient/", "")
    person_id = generate_person_id(abha_ref)
    recorded_date = fhir_json.get(
        "recordedDate", fhir_json.get("meta", {}).get("lastUpdated", "")
    )
    condition_start_date = convert_fhir_date(recorded_date)
    icd_code = fhir_json.get("code", {}).get("coding", [{}])[0].get("code", "")
    condition_concept_id = ICD10_TO_CONCEPT_ID.get(icd_code, 0)

    return {
        "condition_occurrence_id": condition_occurrence_id,
        "person_id": person_id,
        "condition_concept_id": condition_concept_id,
        "condition_start_date": condition_start_date,
        "condition_type_concept_id": 32817,
    }


def process_and_route_payloads(mock_data_dir):
    conn = psycopg2.connect(
        host="localhost",
        port="5433",
        dbname="omop_cdm",
        user="omop_admin",
        password="omop_password",
    )
    cur = conn.cursor()
    json_files = glob.glob(os.path.join(mock_data_dir, "*.json"))
    success_count = {
        "measurement": 0,
        "drug_exposure": 0,
        "condition_occurrence": 0,
        "quarantined": 0,
    }

    for file_path in json_files:
        try:
            with open(file_path, "r") as file:
                payload = json.load(file)

            resource_type = payload.get("resourceType", "")

            if resource_type == "Observation":
                row = transform_observation_to_measurement(payload)

                # Apply Phase 3 Plausibility Rules
                is_valid, error_msg = validate_clinical_plausibility(
                    row["measurement_concept_id"], row["value_as_number"], row["unit"]
                )

                if not is_valid:
                    # Route to Quarantine
                    cur.execute(
                        """
                        INSERT INTO quarantine_log (resource_id, resource_type, person_id, rejection_reason, raw_payload)
                        VALUES (%s, %s, %s, %s, %s);
                    """,
                        (
                            payload.get("id"),
                            "Observation",
                            row["person_id"],
                            error_msg,
                            json.dumps(payload),
                        ),
                    )
                    success_count["quarantined"] += 1
                    continue  # Skip OMOP ingestion

                cur.execute(
                    """
                    INSERT INTO measurement (
                        measurement_id, person_id, measurement_concept_id, measurement_date, 
                        value_as_number, unit_concept_id, measurement_type_concept_id
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING;
                """,
                    (
                        row["measurement_id"],
                        row["person_id"],
                        row["measurement_concept_id"],
                        row["measurement_date"],
                        row["value_as_number"],
                        row["unit_concept_id"],
                        row["measurement_type_concept_id"],
                    ),
                )
                success_count["measurement"] += 1

            elif resource_type == "MedicationRequest":
                row = transform_medication_to_drug_exposure(payload)
                cur.execute(
                    """
                    INSERT INTO drug_exposure (
                        drug_exposure_id, person_id, drug_concept_id, drug_exposure_start_date, 
                        drug_exposure_end_date, drug_type_concept_id
                    ) VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING;
                """,
                    (
                        row["drug_exposure_id"],
                        row["person_id"],
                        row["drug_concept_id"],
                        row["drug_exposure_start_date"],
                        row["drug_exposure_end_date"],
                        row["drug_type_concept_id"],
                    ),
                )
                success_count["drug_exposure"] += 1

            elif resource_type == "Condition":
                row = transform_condition_to_occurrence(payload)
                cur.execute(
                    """
                    INSERT INTO condition_occurrence (
                        condition_occurrence_id, person_id, condition_concept_id, 
                        condition_start_date, condition_type_concept_id
                    ) VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING;
                """,
                    (
                        row["condition_occurrence_id"],
                        row["person_id"],
                        row["condition_concept_id"],
                        row["condition_start_date"],
                        row["condition_type_concept_id"],
                    ),
                )
                success_count["condition_occurrence"] += 1

            conn.commit()

        except Exception as e:
            conn.rollback()
            print(f"Failed to process {os.path.basename(file_path)}: {e}")

    cur.close()
    conn.close()
    return success_count


if __name__ == "__main__":
    print("Starting domain-routed batch ETL with plausibility governance...")
    counts = process_and_route_payloads("tests/mock_data")
    print(
        f"Batch processing complete. Inserted: {counts['measurement']} measurements, {counts['drug_exposure']} drug exposures, {counts['condition_occurrence']} conditions."
    )
    print(f"Quarantined payloads: {counts['quarantined']}")
