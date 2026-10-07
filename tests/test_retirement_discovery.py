import pytest

from pipeline.definitions import evaluate, program_path, validate_program


@pytest.mark.parametrize("age,expected", [
    (61, "fails_documented_condition"),
    (62, "potential_match"),
    (63, "potential_match"),
])
def test_retirement_age_boundary_without_prior_application(age, expected):
    document = validate_program(program_path("social_security_retirement"))
    profile = {"age_years": age, "ssa_fully_insured_for_retirement": True,
               "ssa_retirement_application_filed": False}
    assert evaluate(document, profile)["result"] == expected


def test_retirement_requires_insured_status_and_preserves_follow_up():
    document = validate_program(program_path("social_security_retirement"))
    assert evaluate(document, {"age_years": 63})["result"] == "unknown"
    assert evaluate(document, {"age_years": 63, "ssa_fully_insured_for_retirement": False})["result"] == "fails_documented_condition"
    assert {step["kind"] for step in document["follow_up"]} == {"application", "entitlement_timing"}
    assert "ssa_retirement_application_filed" not in str(document["eligibility"])
