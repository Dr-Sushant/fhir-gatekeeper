import logging
from typing import Dict, Any

logger = logging.getLogger("FHIR-Gatekeeper.Semantics")


class SemanticRulesEngine:
    def __init__(self):
        # Define physiological boundaries and enforced UCUM units
        self.vital_thresholds = {
            "8867-4": {  # LOINC: Heart Rate
                "min": 30,
                "max": 250,
                "unit": "/min",
                "name": "Heart Rate",
            },
            "8310-5": {  # LOINC: Body Temperature
                "min": 30.0,
                "max": 43.0,
                "unit": "Cel",
                "name": "Body Temperature",
            },
            "9279-1": {  # LOINC: Respiratory Rate
                "min": 4,
                "max": 60,
                "unit": "/min",
                "name": "Respiratory Rate",
            },
        }

    def evaluate_observation(self, obs: Dict[str, Any]) -> Dict[str, Any]:
        """Evaluates an Observation against clinical semantic rules."""

        # 1. Extract LOINC code
        code_concept = obs.get("code", {})
        codings = code_concept.get("coding", [])
        loinc_code = next(
            (c.get("code") for c in codings if c.get("system") == "http://loinc.org"),
            None,
        )

        if not loinc_code or loinc_code not in self.vital_thresholds:
            return {
                "valid": True,
                "reason": "No applicable semantic rule for this LOINC.",
            }

        rule = self.vital_thresholds[loinc_code]

        # 2. Extract Value and Unit
        value_quantity = obs.get("valueQuantity", {})
        if not value_quantity:
            return {"valid": True, "reason": "No numeric valueQuantity to validate."}

        value = value_quantity.get("value")
        unit = value_quantity.get("code")  # UCUM code

        # 3. Enforce UCUM Unit Match
        if unit != rule["unit"]:
            return {
                "valid": False,
                "error_code": "unit_mismatch",
                "diagnostics": f"Semantic Violation: Expected UCUM unit '{rule['unit']}' for {rule['name']} (LOINC {loinc_code}), but got '{unit}'.",
            }

        # 4. Enforce Physiological Boundaries
        if value is not None and (value < rule["min"] or value > rule["max"]):
            return {
                "valid": False,
                "error_code": "implausible_value",
                "diagnostics": f"Semantic Violation: Value {value} {unit} is physiologically implausible for {rule['name']}. Accepted range: {rule['min']}-{rule['max']} {rule['unit']}.",
            }

        return {"valid": True, "reason": "Passed semantic boundary checks."}


SENSITIVE_REPRODUCTIVE_CODES = {"82810-3", "11636-8", "60934-7"}


def violates_privacy_consent(payload: dict, patient_consent_active: bool) -> bool:
    if patient_consent_active:
        return False

    # Example parsing for Observation codes
    if payload.get("resourceType") == "Observation":
        code_block = payload.get("code", {}).get("coding", [])
        return any(c.get("code") in SENSITIVE_REPRODUCTIVE_CODES for c in code_block)
    return False
