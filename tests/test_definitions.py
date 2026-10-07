import copy
import json

import pytest
from jsonschema import ValidationError

from pipeline.definitions import PROGRAMS, evaluate, program_path, validate_all, validate_program
from pipeline.adapters import ADAPTERS
from pipeline import cli
from pipeline.evidence import ROOT


def test_all_eight_definitions_validate_with_snapshot_references():
    definitions = validate_all()
    assert len(definitions) == 8
    assert all(d["eligibility"] and d["thresholds"] and d["tags"] for d in definitions)
    assert all(program_path(d["program_id"]).is_file() for d in definitions)
    assert all(all(key in d for key in ("name", "agency", "family", "summary", "application_url", "sources"))
               for d in definitions)
    assert all(d["application_url"].startswith("https://") for d in definitions)
    assert all("definition_revision" not in d and "scope" not in d for d in definitions)
    assert all(not any(key in definition for key in
                       ("review_questions", "financial_calculation_notes", "enrollment_timing_notes"))
               for definition in definitions)


def test_dated_snapshot_path_matches_source_id(tmp_path):
    definition = copy.deepcopy(validate_program(program_path("medicare_eligibility")))
    evidence = definition["eligibility"]["all"][0]["evidence"][0]
    source = definition["sources"][evidence["source_ref"]]
    assert source["snapshot_source_id"] == "medicare_start-f3a364c71f5d1449"
    assert source["sidecar_path"] == "data/raw/medicare_start/2026-10-06.json"
    source["sidecar_path"] = "data/raw/medicare_other_paths/2026-10-06.json"
    path = tmp_path / "wrong-sidecar.json"
    path.write_text(json.dumps(definition), encoding="utf-8")
    with pytest.raises(ValueError, match="source reference"):
        validate_program(path)


def test_missing_inputs_and_nested_alternatives_remain_unknown():
    definition = validate_program(program_path("social_security_spouse"))
    assert evaluate(definition, {})["result"] == "unknown"
    profile = {"worker_entitled_to_retirement_or_disability": True,
               "relationship_to_worker": "spouse", "marriage_duration_years": 1,
               "ssa_current_spouse_relationship_verified": True,
               "ssa_own_pia_below_half_worker_pia": True,
               "age_years": 62}
    assert evaluate(definition, profile)["result"] == "potential_match"
    profile["age_years"] = 61
    assert evaluate(definition, profile)["result"] == "unknown"


def test_exact_boundaries_selectors_and_effective_dates():
    definition = validate_program(program_path("medicare_part_d_extra_help"))
    definition = copy.deepcopy(definition)
    definition["eligibility"] = {"field": "extra_help_countable_annual_income_cents", "operator": "<",
                            "threshold": "income_limit_2026",
                            "selectors": {"household": "extra_help_household", "region": "extra_help_region"},
                            "evidence": definition["thresholds"]["income_limit_2026"]["evidence"]}
    profile = {"extra_help_countable_annual_income_cents": 2393999,
               "extra_help_household": "individual", "extra_help_region": "contiguous_us_dc"}
    assert evaluate(definition, profile, "2026-01-01")["result"] == "potential_match"
    profile["extra_help_countable_annual_income_cents"] = 2394000
    assert evaluate(definition, profile, "2026-12-31")["result"] == "fails_documented_condition"
    assert evaluate(definition, profile, "2027-01-01")["result"] == "unknown"
    profile["extra_help_region"] = "alaska"
    assert evaluate(definition, profile, "2026-06-01")["result"] == "unknown"


def test_source_reference_and_duplicate_selector_rejected(tmp_path):
    definition = copy.deepcopy(validate_program(program_path("medicare_eligibility")))
    definition["eligibility"]["all"][0]["evidence"][0]["source_ref"] = "made_up"
    path = tmp_path / "definition.json"
    path.write_text(json.dumps(definition), encoding="utf-8")
    with pytest.raises(ValueError, match="broken source_ref"):
        validate_program(path)
    definition = copy.deepcopy(validate_program(program_path("ssi_federal")))
    definition["thresholds"]["resource_limit"]["rows"].append(
        copy.deepcopy(definition["thresholds"]["resource_limit"]["rows"][0]))
    path.write_text(json.dumps(definition), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate threshold selector"):
        validate_program(path)


def test_follow_up_evidence_reference_is_checked(tmp_path):
    definition = copy.deepcopy(validate_program(program_path("ssi_federal")))
    definition["follow_up"][0]["evidence"][0]["source_ref"] = "missing_source"
    path = tmp_path / "broken-follow-up.json"
    path.write_text(json.dumps(definition), encoding="utf-8")
    with pytest.raises(ValueError, match="broken source_ref"):
        validate_program(path)


def test_required_metadata_and_snapshot_pair(tmp_path):
    document = copy.deepcopy(validate_program(program_path("medicare_eligibility")))
    path = tmp_path / "program.json"
    document.pop("agency")
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValidationError):
        validate_program(path)
    document = copy.deepcopy(validate_program(program_path("medicare_eligibility")))
    ref = next(ref for ref, source in document["sources"].items() if "snapshot_source_id" in source)
    document["sources"][ref].pop("sidecar_path")
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValidationError):
        validate_program(path)


def test_url_sources_and_match_requires_document(tmp_path, monkeypatch):
    document = validate_program(program_path("social_security_retirement"))
    assert any("snapshot_source_id" not in source for source in document["sources"].values())
    assert document["eligibility"]["all"][0]["evidence"]
    assert program_path("social_security_retirement") == PROGRAMS / "social_security_retirement.json"
    assert program_path("social_security_spouse") == PROGRAMS / "social_security_spouse.json"
    monkeypatch.setattr("pipeline.definitions.PROGRAMS", tmp_path)
    with pytest.raises(ValueError, match="missing program document"):
        program_path("social_security_spouse")
    with pytest.raises(SystemExit) as error:
        cli.main(["match", "social_security_spouse", str(ROOT / "tests" / "profiles" / "spouse_profile.json")])
    assert error.value.code == 2


@pytest.mark.parametrize("program_id,profile_name", [
    ("social_security_retirement", "retirement_profile.json"),
    ("medicare_eligibility", "medicare_profile.json"),
    ("medicare_part_d_extra_help", "extra_help_profile.json"),
])
def test_programs_match_profiles(program_id, profile_name):
    definition = validate_program(program_path(program_id))
    profile = json.loads((ROOT / "tests" / "profiles" / profile_name).read_text(encoding="utf-8"))
    result = evaluate(definition, profile)
    assert result["result"] == "potential_match"
    assert result["evidence"]


def test_va_adapter_keeps_rate_rows():
    html = b'<main><h2>MAPR</h2><va-table><va-table-row slot="headers"><span>Case</span><span>USD</span></va-table-row><va-table-row><span>Basic</span><span>17,441</span></va-table-row></va-table></main>'
    result = ADAPTERS["va"].extract(html, "https://www.va.gov/pension/veterans-pension-rates/")
    assert result["sections"][0]["content"][0]["table"] == [["Case", "USD"], ["Basic", "17,441"]]


def test_spouse_child_in_care_requires_entitled_child_and_divorced_route_is_independent():
    definition = validate_program(program_path("social_security_spouse"))
    child = {"worker_entitled_to_retirement_or_disability": True,
             "relationship_to_worker": "spouse", "marriage_duration_years": 1,
             "ssa_current_spouse_relationship_verified": True,
             "ssa_own_pia_below_half_worker_pia": True,
             "age_years": 40, "caring_for_workers_child": True, "child_age_years": 15,
             "caring_for_disabled_workers_child": False}
    assert evaluate(definition, child)["result"] == "unknown"
    child["child_entitled_on_worker_record"] = True
    assert evaluate(definition, child)["result"] == "unknown"
    child["child_age_years"] = 16
    assert evaluate(definition, child)["result"] == "fails_documented_condition"
    divorced = {"relationship_to_worker": "ex_spouse", "marriage_duration_years": 10,
                "age_years": 62, "worker_entitled_to_retirement_or_disability": False}
    assert evaluate(definition, divorced)["result"] == "unknown"


def test_independent_divorced_spouse_two_year_boundary():
    definition = validate_program(program_path("social_security_spouse"))
    profile = {"relationship_to_worker": "ex_spouse", "marriage_duration_years": 10,
               "ssa_divorced_spouse_relationship_verified": True,
               "worker_entitled_to_retirement_or_disability": False,
               "worker_fully_insured_for_independent_divorced_spouse": True,
               "worker_age_62_throughout_entitlement_month": True,
               "continuous_divorce_months": 24, "age_years": 62,
               "claimant_currently_unmarried_for_divorced_spouse": True,
               "ssa_own_pia_below_half_worker_pia": True}
    assert evaluate(definition, profile)["result"] == "potential_match"
    profile["continuous_divorce_months"] = 23
    assert evaluate(definition, profile)["result"] == "fails_documented_condition"


def test_survivor_student_ordinary_age_boundary():
    definition = copy.deepcopy(validate_program(program_path("social_security_survivor")))
    child = definition["eligibility"]["all"][1]["any"][2]["all"][-2]["any"]
    definition["eligibility"] = child[2]["all"][0]
    assert evaluate(definition, {"age_years": 18})["result"] == "potential_match"
    assert evaluate(definition, {"age_years": 19})["result"] == "fails_documented_condition"


def test_surviving_divorced_parent_child_in_care_has_no_ten_year_gate():
    definition = copy.deepcopy(validate_program(program_path("social_security_survivor")))
    definition["eligibility"] = definition["eligibility"]["all"][1]["any"][-1]
    profile = {"relationship_to_decedent": "ex_spouse",
               "ssa_surviving_divorced_parent_child_relationship_met": True,
               "deceased_worker_fully_or_currently_insured_for_mother_father": True,
               "ssa_mother_father_relationship_duration_met": True,
               "ssa_mother_father_remarriage_rule_met": True,
               "ssa_mother_father_not_entitled_to_widow_benefit": True,
               "ssa_mother_father_own_rib_below_unadjusted_benefit": True,
               "ssa_entitled_child_in_care_requirement_met": True}
    assert evaluate(definition, profile)["result"] == "unknown"


def test_post_1981_officer_requires_minimum_duty_or_exception():
    definition = copy.deepcopy(validate_program(program_path("va_veterans_pension")))
    definition["eligibility"] = definition["eligibility"]["all"][3]["any"][2]
    profile = {"service_entry_route": "after_1981_officer",
               "prior_24_month_active_service": False,
               "continuous_active_service_months": 23,
               "served_full_call_period": False}
    assert evaluate(definition, profile)["result"] == "fails_documented_condition"
    profile["continuous_active_service_months"] = 24
    assert evaluate(definition, profile)["result"] == "potential_match"


def test_va_surviving_child_separate_entitlement_and_custody_rate():
    definition = copy.deepcopy(validate_program(program_path("va_survivors_pension")))
    child = definition["eligibility"]["all"][3]["any"][1]
    definition["eligibility"] = child
    profile = {"relationship_to_veteran": "child", "va_survivor_case": "qualified_child",
               "va_child_not_in_custody_of_pension_eligible_surviving_spouse": False,
               "unmarried_child": True, "va_survivor_child_dependency_verified": True,
               "age_years": 17,
               "va_child_no_personal_custodian_or_institutional_custody": True}
    assert evaluate(definition, profile)["result"] == "fails_documented_condition"
    profile["va_child_not_in_custody_of_pension_eligible_surviving_spouse"] = True
    assert evaluate(definition, profile)["result"] == "unknown"
    profile["va_child_no_personal_custodian_or_institutional_custody"] = False
    profile["va_survivor_case"] = "qualified_child_custodian"
    assert evaluate(definition, profile)["result"] == "unknown"


def test_case_specific_threshold_input_is_required_and_has_exact_boundary():
    definition = copy.deepcopy(validate_program(program_path("ssi_federal")))
    definition["eligibility"] = next(n for n in definition["eligibility"]["all"]
                                if n.get("threshold") == "applicable_monthly_federal_rate")
    profile = {"ssi_countable_monthly_income_cents": 99399}
    assert evaluate(definition, profile)["result"] == "unknown"
    profile["ssi_applicable_monthly_federal_rate_cents"] = 99400
    assert evaluate(definition, profile)["result"] == "potential_match"
    profile["ssi_countable_monthly_income_cents"] = 99400
    assert evaluate(definition, profile)["result"] == "fails_documented_condition"
    profile["ssi_applicable_monthly_federal_rate_cents"] = "99400"
    assert evaluate(definition, profile)["result"] == "unknown"


def test_va_additional_dependent_mapr_input_and_period():
    definition = copy.deepcopy(validate_program(program_path("va_veterans_pension")))
    definition["eligibility"] = next(n for n in definition["eligibility"]["all"]
                                if n.get("threshold") == "mapr_2026")
    profile = {"va_income_for_purposes_annual_cents": 2500000,
               "va_dependents_case": "additional_dependents", "va_pension_tier": "basic"}
    assert evaluate(definition, profile, "2025-12-01")["result"] == "unknown"
    profile["va_applicable_mapr_cents"] = 2582300  # synthetic: 22,839 + 2,984
    assert evaluate(definition, profile, "2025-12-01")["result"] == "potential_match"
    assert evaluate(definition, profile, "2026-12-01")["result"] == "unknown"


def test_als_route_and_survivor_insurance_are_distinct():
    medicare = validate_program(program_path("medicare_eligibility"))
    profile = {"medicare_citizenship_or_residency_requirement_met": True,
               "age_years": 40, "social_security_disability_benefit_months": 0,
               "als_with_social_security_disability_benefits": True,
               "esrd_medicare_pathway_confirmed": False}
    result = evaluate(medicare, profile)
    assert result["result"] == "potential_match"
    assert result["evidence"]
    survivor = validate_program(program_path("social_security_survivor"))
    assert evaluate(survivor, {"deceased_worker_insured_for_survivors": False})["result"] == "fails_documented_condition"


@pytest.mark.parametrize("program,field,selectors", [
    ("va_veterans_pension", "va_income_for_purposes_annual_cents", {"va_dependents_case": "none", "va_pension_tier": "basic"}),
    ("va_survivors_pension", "va_survivor_income_for_purposes_annual_cents", {"va_survivor_case": "spouse_no_child", "va_survivor_tier": "basic"}),
])
def test_va_mapr_income_equality_has_no_positive_base_payment(program, field, selectors):
    definition = copy.deepcopy(validate_program(program_path(f"{program}")))
    amount = next(row["value"] for row in definition["thresholds"]["mapr_2026"]["rows"]
                  if row["selectors"] == ({"dependents": "none", "tier": "basic"} if program == "va_veterans_pension" else {"case": "spouse_no_child", "tier": "basic"}))
    definition["eligibility"] = next(n for n in definition["eligibility"]["all"] if n.get("threshold") == "mapr_2026")
    profile = {field: amount - 1, **selectors}
    assert evaluate(definition, profile, "2025-12-01")["result"] == "potential_match"
    profile[field] = amount
    assert evaluate(definition, profile, "2025-12-01")["result"] == "fails_documented_condition"
    profile[field] = amount + 1
    assert evaluate(definition, profile, "2026-11-30")["result"] == "fails_documented_condition"
    assert evaluate(definition, profile, "2026-12-01")["result"] == "unknown"
