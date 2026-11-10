import psycopg2


def fetch_patient_timeline(person_id):
    """Extracts and merges sequences from measurements, drugs, and conditions."""
    try:
        conn = psycopg2.connect(
            host="localhost",
            port="5433",
            dbname="omop_cdm",
            user="omop_admin",
            password="omop_password",
        )
        cur = conn.cursor()

        # Pull physiological labs
        cur.execute(
            """
            SELECT measurement_concept_id, measurement_date, value_as_number 
            FROM measurement 
            WHERE person_id = %s;
        """,
            (person_id,),
        )
        labs = cur.fetchall()

        # Pull medications
        cur.execute(
            """
            SELECT drug_concept_id, drug_exposure_start_date, 1.0 
            FROM drug_exposure 
            WHERE person_id = %s;
        """,
            (person_id,),
        )
        drugs = cur.fetchall()

        # Pull conditions
        cur.execute(
            """
            SELECT condition_concept_id, condition_start_date, 1.0 
            FROM condition_occurrence 
            WHERE person_id = %s;
        """,
            (person_id,),
        )
        conditions = cur.fetchall()

        timeline = []
        for row in labs:
            timeline.append(
                {"concept_id": row[0], "date": str(row[1]), "value": row[2]}
            )

        for row in drugs:
            timeline.append(
                {"concept_id": row[0], "date": str(row[1]), "value": row[2]}
            )

        for row in conditions:
            timeline.append(
                {"concept_id": row[0], "date": str(row[1]), "value": row[2]}
            )

        # Sort the combined multi-domain timeline chronologically
        timeline.sort(key=lambda x: x["date"])

        cur.close()
        conn.close()
        return timeline

    except Exception as e:
        print(f"Extraction failed: {e}")
        return None


def tokenize_sequence(timeline):
    tokens = []
    for event in timeline:
        tokens.append(f"[{event['concept_id']}:{event['value']}]")
    return tokens


if __name__ == "__main__":
    target_person_id = 2045113149

    print(
        f"Extracting multi-domain longitudinal history for Person ID {target_person_id}..."
    )
    patient_timeline = fetch_patient_timeline(target_person_id)

    if patient_timeline:
        ml_tokens = tokenize_sequence(patient_timeline)
        print("\nMEDIATOR Token Sequence:")
        print(" -> ".join(ml_tokens))
