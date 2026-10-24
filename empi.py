import jellyfish
from typing import Dict, Any, List, Tuple, Optional
import logging

logger = logging.getLogger("FHIR-Gatekeeper.EMPI")


class EMPIEngine:
    def __init__(self, match_threshold: float = 0.85, review_threshold: float = 0.60):
        self.match_threshold = match_threshold
        self.review_threshold = review_threshold

    @staticmethod
    def extract_identifiers(patient: Dict[str, Any]) -> Dict[str, str]:
        """Extracts standard Indian health identifiers (ABHA number, ABHA address)."""
        ids = {}
        for identifier in patient.get("identifier", []):
            system = identifier.get("system", "")
            value = identifier.get("value", "")
            if "ndhm" in system.lower() or "abha" in system.lower():
                ids["abha"] = value
            elif "mrn" in system.lower():
                ids["mrn"] = value
            elif "uidai" in system.lower() or "aadhaar" in system.lower():
                ids["aadhaar"] = value
        return ids

    @staticmethod
    def normalize_name(patient: Dict[str, Any]) -> Tuple[str, str]:
        """Normalizes first and last name from FHIR HumanName array."""
        names = patient.get("name", [])
        if not names:
            return ("", "")
        primary_name = names[0]
        family = primary_name.get("family", "").strip().lower()
        given_parts = primary_name.get("given", [])
        given = " ".join(given_parts).strip().lower() if given_parts else ""
        return (given, family)

    def calculate_probabilistic_score(
        self, incoming: Dict[str, Any], candidate: Dict[str, Any]
    ) -> float:
        """
        Computes Fellegi-Sunter agreement weight across demographic fields.
        Weights: Given Name (0.35), Family Name (0.25), DOB (0.25), Gender (0.15).
        """
        score = 0.0

        inc_given, inc_family = self.normalize_name(incoming)
        cand_given, cand_family = self.normalize_name(candidate)

        # 1. Given Name (Jaro-Winkler + Metaphone phonetic boost)
        if inc_given and cand_given:
            jw_given = jellyfish.jaro_winkler_similarity(inc_given, cand_given)
            # Phonetic match bonus
            if jellyfish.metaphone(inc_given) == jellyfish.metaphone(cand_given):
                jw_given = min(1.0, jw_given + 0.1)
            score += jw_given * 0.35

        # 2. Family Name (Jaro-Winkler)
        if inc_family and cand_family:
            jw_family = jellyfish.jaro_winkler_similarity(inc_family, cand_family)
            score += jw_family * 0.25

        # 3. Date of Birth (Exact match)
        inc_dob = incoming.get("birthDate", "")
        cand_dob = candidate.get("birthDate", "")
        if inc_dob and cand_dob:
            if inc_dob == cand_dob:
                score += 0.25
            elif inc_dob[:4] == cand_dob[:4]:  # Same birth year
                score += 0.10

        # 4. Gender (Exact match)
        inc_gender = incoming.get("gender", "")
        cand_gender = candidate.get("gender", "")
        if inc_gender and cand_gender and (inc_gender == cand_gender):
            score += 0.15

        return round(score, 4)

    def evaluate_candidate(
        self, incoming: Dict[str, Any], existing_patients: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Runs deterministic check first, falls back to probabilistic scoring.
        """
        incoming_ids = self.extract_identifiers(incoming)

        # Tier 1: Deterministic Check
        if "abha" in incoming_ids:
            for cand in existing_patients:
                cand_ids = self.extract_identifiers(cand)
                if cand_ids.get("abha") == incoming_ids["abha"]:
                    return {
                        "decision": "EXACT_MATCH",
                        "matched_patient_id": cand.get("id"),
                        "confidence": 1.0,
                        "rule": "DETERMINISTIC_ABHA",
                    }

        # Tier 2: Probabilistic Linkage Check
        best_match_id: Optional[str] = None
        highest_score = 0.0

        for cand in existing_patients:
            candidate_resource = cand.get("resource", cand)
            score = self.calculate_probabilistic_score(incoming, candidate_resource)
            if score > highest_score:
                highest_score = score
                best_match_id = candidate_resource.get("id")

        if highest_score >= self.match_threshold:
            return {
                "decision": "PROBABILISTIC_DUPLICATE",
                "matched_patient_id": best_match_id,
                "confidence": highest_score,
                "rule": "FELLEGI_SUNTER_AUTO_MATCH",
            }
        elif highest_score >= self.review_threshold:
            return {
                "decision": "SUSPECT_STEWARDSHIP_REQUIRED",
                "matched_patient_id": best_match_id,
                "confidence": highest_score,
                "rule": "AMBIGUOUS_MATCH_QUARANTINE",
            }

        return {
            "decision": "NEW_IDENTITY",
            "matched_patient_id": None,
            "confidence": highest_score,
            "rule": "INSUFFICIENT_SIMILARITY",
        }
