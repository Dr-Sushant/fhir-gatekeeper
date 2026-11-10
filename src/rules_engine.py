# Declarative clinical plausibility bounds mapping OMOP concept IDs to hard physiological limits
PLAUSIBILITY_RULES = {
    "3000963": {  # Hemoglobin
        "unit": "g/dL",
        "min_value": 2.0,  # Below this is generally incompatible with life
        "max_value": 30.0,  # Above this is physiologically impossible
    }
}


def validate_clinical_plausibility(concept_id, value, unit):
    """
    Evaluates incoming measurements against hard physiological bounds.
    Returns (True, None) if valid, or (False, error_message) if implausible.
    """
    rule = PLAUSIBILITY_RULES.get(str(concept_id))

    if not rule:
        # Pass through if no explicit rule exists for this concept yet
        return True, None

    if unit != rule["unit"]:
        return False, f"Unit mismatch: Expected {rule['unit']}, got {unit}"

    if not (rule["min_value"] <= value <= rule["max_value"]):
        return (
            False,
            f"Implausible value: {value} is outside physiological bounds ({rule['min_value']} - {rule['max_value']} {rule['unit']})",
        )

    return True, None


if __name__ == "__main__":
    # Test 1: A normal lab
    is_valid, msg = validate_clinical_plausibility(3000963, 14.2, "g/dL")
    print(f"Normal Lab - Valid: {is_valid}")

    # Test 2: A dangerous typo (e.g., missed decimal point)
    is_valid, msg = validate_clinical_plausibility(3000963, 142.0, "g/dL")
    print(f"Typo Lab   - Valid: {is_valid} | Reason: {msg}")

    # Test 3: Unit mismatch
    is_valid, msg = validate_clinical_plausibility(3000963, 14.2, "mg/dL")
    print(f"Wrong Unit - Valid: {is_valid} | Reason: {msg}")
