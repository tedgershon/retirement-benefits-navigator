import copy
import json

import pytest

from pipeline import cli
from pipeline.definitions import evaluate, program_path, validate_program


OLDER_PROFILES = {
    "social_security_spouse": {
        "relationship_to_worker": "spouse", "worker_entitled_to_retirement_or_disability": True,
        "ssa_current_spouse_relationship_verified": True, "marriage_duration_years": 2,
        "age_years": 67, "ssa_own_pia_below_half_worker_pia": True,
    },
    "social_security_survivor": {
        "deceased_worker_insured_for_survivors": True, "relationship_to_decedent": "spouse",
        "deceased_worker_fully_or_transitionally_insured_for_widow": True,
        "marriage_duration_months": 12, "age_years": 67,
        "remarriage_rule_met": True, "ssa_survivor_own_rib_below_decedent_pia": True,
    },
    "ssi_federal": {
        "age_years": 67, "ssi_countable_resources_cents": 0,
        "ssi_resource_household": "individual", "ssi_citizenship_or_noncitizen_eligibility_met": True,
        "ssi_residency_requirement_met": True, "ssi_absence_rule_met_for_month": True,
        "ssi_institution_rule_met_for_month": True, "ssi_countable_monthly_income_cents": 0,
        "ssi_applicable_monthly_federal_rate_cents": 99400,
        "ssi_resource_transfer_penalty_not_in_effect": True,
        "ssi_no_fugitive_felon_or_probation_parole_bar": True,
    },
    "va_veterans_pension": {
        "va_discharge_qualifies": True, "wartime_active_service_days": 1,
        "va_pension_wartime_service_requirement_met": True,
        "service_entry_route": "before_1980_09_08", "active_service_days": 90,
        "age_years": 67, "va_net_worth_for_pension_cents": 0,
        "va_mapr_case_and_tier_verified": True, "va_income_for_purposes_annual_cents": 0,
        "va_dependents_case": "none", "va_pension_tier": "basic",
        "va_asset_transfer_penalty_not_in_effect": True,
    },
    "va_survivors_pension": {
        "deceased_veteran_discharge_qualifies": True,
        "deceased_veteran_wartime_service_days": 1,
        "deceased_veteran_service_route_confirmed": True,
        "relationship_to_veteran": "surviving_spouse", "va_survivor_case": "spouse_no_child",
        "remarried_after_veteran_death": False, "continuous_cohabitation_met": True,
        "va_survivor_net_worth_cents": 0, "va_survivor_mapr_case_and_tier_verified": True,
        "va_survivor_income_for_purposes_annual_cents": 0,
        "va_survivor_tier": "basic", "va_survivor_asset_transfer_penalty_not_in_effect": True,
    },
}


@pytest.mark.parametrize("program_id", sorted(OLDER_PROFILES))
def test_reviewed_older_adult_pathway_pass_fail_unknown(program_id):
    document = validate_program(program_path(program_id))
    profile = copy.deepcopy(OLDER_PROFILES[program_id])
    assert evaluate(document, profile)["result"] == "potential_match"
    fail_field, fail_value = {
        "social_security_spouse": ("worker_entitled_to_retirement_or_disability", False),
        "social_security_survivor": ("deceased_worker_insured_for_survivors", False),
        "ssi_federal": ("ssi_countable_resources_cents", 200001),
        "va_veterans_pension": ("va_net_worth_for_pension_cents", 16370000),
        "va_survivors_pension": ("va_survivor_net_worth_cents", 16370000),
    }[program_id]
    profile[fail_field] = fail_value
    assert evaluate(document, profile)["result"] == "fails_documented_condition"
    assert evaluate(document, {})["result"] == "unknown"


@pytest.mark.parametrize("program_id", sorted(OLDER_PROFILES))
def test_normal_cli_matches_newly_reviewed_programs(program_id, tmp_path, capsys):
    profile_path = tmp_path / "synthetic-profile.json"
    profile_path.write_text(json.dumps(OLDER_PROFILES[program_id]), encoding="utf-8")
    cli.main(["match", program_id, str(profile_path)])
    result = json.loads(capsys.readouterr().out)
    assert result["result"] == "potential_match"
    assert result["application_url"]


@pytest.mark.parametrize("program_id,missing_field", [
    ("social_security_spouse", "worker_entitled_to_retirement_or_disability"),
    ("social_security_survivor", "deceased_worker_insured_for_survivors"),
    ("va_veterans_pension", "va_pension_wartime_service_requirement_met"),
    ("va_survivors_pension", "deceased_veteran_service_route_confirmed"),
])
def test_missing_agency_determination_stays_unknown(program_id, missing_field):
    document = validate_program(program_path(program_id))
    profile = copy.deepcopy(OLDER_PROFILES[program_id])
    profile.pop(missing_field)
    result = evaluate(document, profile)
    assert result["result"] == "unknown"
    assert any("agency determination needed" in check and missing_field in check
               for check in result["unresolved_checks"])


def test_missing_calculation_is_explained_and_ssi_filing_is_follow_up():
    document = validate_program(program_path("ssi_federal"))
    profile = copy.deepcopy(OLDER_PROFILES["ssi_federal"])
    profile.pop("ssi_applicable_monthly_federal_rate_cents")
    result = evaluate(document, profile)
    assert result["result"] == "unknown"
    assert any("unsupported calculation: SSI federal rate" in check for check in result["unresolved_checks"])
    assert len(result["follow_up"]) == 2
    assert "ssi_other_benefit_filing_requirement_met" not in str(document["eligibility"])


def test_retirement_discovery_does_not_require_application():
    document = validate_program(program_path("social_security_retirement"))
    profile = {"age_years": 67, "ssa_fully_insured_for_retirement": True}
    result = evaluate(document, profile)
    assert result["result"] == "potential_match"
    assert not result["unresolved_checks"]
    assert {step["kind"] for step in result["follow_up"]} == {"application", "entitlement_timing"}
    assert result["application_url"] == "https://www.ssa.gov/retirement"
