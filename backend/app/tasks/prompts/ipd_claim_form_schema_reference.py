# Source: healthpay-ai@test-fhpl healthpay/backend/app/lang_graph/prompts/schema/claim_form_schema.py


CLAIM_FORM_SCHEMA = """

  {{
    "claim_form": {{
      "part_a": {{
        "policy_no": "string",
        "full_name": "string",
        "age_years": "numeric",
        "gender": "male|female|other|null",
        "address": "string",
        "city": "string",
        "pin_code": "string",
        "phone_no": "string",
        "state": "string",
        "email_id": "string",
        "diagnosis": "string",

        "date_of_admission": "YYYY-MM-DD format",
        "time_admission": "time",
        "date_of_discharge": "YYYY-MM-DD format", 
        "time_discharge": "time",

        "pre_hospitalization_expenses": "numeric",
        "hospitalization_expenses": "numeric",
        "post_hospitalization_expenses": "numeric",

        "total": "numeric",

      }},
      "part_b": {{

        "name_of_treating_doctor": "string",
        "registration_no_with_state_code": "string",
        "phone_no": "string",
        "name_of_the_patient": "string",




        
      }}
    }}
  }}
"""

CLAIM_FORM_OUTPUT_EXAMPLES = """

```json
{
  "claim_form": {
    "part_a": {
      "policy_no": "POL123456789",
      "full_name": "Aarav Doe",
      "age_years": 12,
      "gender": "male",
      "address": "John Doe, 123 Main Street, Apartment 4B",
      "city": "Mumbai",
      "pin_code": "400001",
      "phone_no": "9876543210",
      "state": "Maharashtra",
      "email_id": "john.smith@email.com",
      "diagnosis": "Appendicitis",
      "date_of_admission": "2024-01-12",
      "time_admission": "14:30:00",
      "date_of_discharge": "2024-01-15",
      "time_discharge": "10:00:00",
      "pre_hospitalization_expenses": 5000,
      "hospitalization_expenses": 75000,
      "post_hospitalization_expenses": 3000,
      "total": 83000
    },
    "part_b": {
      "name_of_treating_doctor": "Dr. Rajesh Kumar",
      "registration_no_with_state_code": "MH123456",
      "phone_no": "022-12345678",
      "name_of_the_patient": "Aarav Doe"
    }
  }
}
```

**Example 2: Partial Form with Missing Data**

Input: Claim form with some sections incomplete

Expected Output:
```json
{
  "claim_form": {
    "part_a": {
      "policy_no": "POL987654321",
      "full_name": "Mary Johnson",
      "age_years": 35,
      "gender": "female",
      "address": "456 Oak Avenue",
      "city": "Delhi",
      "pin_code": "110001",
      "phone_no": "9123456789",
      "state": "Delhi",
      "email_id": null,
      "date_of_admission": "2024-02-10",
      "date_of_discharge": "2024-02-12",
      "hospitalization_expenses": 45000,
      "total": 45000
    },
    "part_b": {
      "name_of_treating_doctor": "Dr. Priya Sharma",
      "name_of_the_patient": "Mary Johnson"
    }
  }
}
```

"""
