import json

from pipeline.definitions import FAMILIES, PROGRAMS, overview
from pipeline.evidence import ROOT


def test_generated_overview_has_all_eight_reviewed_programs():
    programs = overview()["programs"]
    assert {item["program_id"] for item in programs} == set(FAMILIES)
    assert all(item["status"] == "reviewed" for item in programs)
    assert len(list(PROGRAMS.glob("*.json"))) == 8
    assert all(item["name"] and item["summary"] for item in programs)


def test_agent_read_ssa_candidates_are_separate_and_source_linked():
    path = ROOT / "data" / "core" / "ssa_agent" / "2026-10-06.json"
    candidate = json.loads(path.read_text(encoding="utf-8"))
    assert candidate["review_required"] is True
    assert candidate["raw_ssa_snapshot_available"] is False
    assert {p["program_id"] for p in candidate["programs"]} == {
        "social_security_retirement", "social_security_spouse", "social_security_survivor", "ssi_federal"}
    assert all(fact["evidence"]["url"].startswith("https://www.ssa.gov/") and fact["evidence"]["locator"]
               for program in candidate["programs"] for fact in program["facts"])
