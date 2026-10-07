"""Validate complete program documents and evaluate their eligibility expressions."""
import hashlib
import json
import operator
from datetime import date
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from .evidence import ROOT, SNAPSHOTS, manifest, snapshot_path, snapshot_sidecars

PROGRAMS = ROOT / "data" / "curated" / "programs"
SCHEMA = ROOT / "schema" / "program.schema.json"
FAMILIES = {
    "social_security_retirement": "social_security",
    "social_security_spouse": "social_security",
    "social_security_survivor": "social_security",
    "ssi_federal": "ssi",
    "medicare_eligibility": "medicare",
    "medicare_part_d_extra_help": "extra_help",
    "va_veterans_pension": "va_pension",
    "va_survivors_pension": "va_pension",
}


def program_path(program_id):
    """Return an approved program document."""
    if program_id not in FAMILIES:
        raise ValueError(f"unknown program_id: {program_id}")
    path = PROGRAMS / f"{program_id}.json"
    if not path.is_file():
        raise ValueError(f"missing program document: {program_id}")
    return path


def _snapshots():
    records = {}
    for path in snapshot_sidecars(SNAPSHOTS):
        item = json.loads(path.read_text(encoding="utf-8"))
        records[item["source_id"]] = (item, path.relative_to(ROOT).as_posix())
    return records


def validate_program(path, snapshots=None):
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(document)
    if document["family"] != FAMILIES[document["program_id"]]:
        raise ValueError(f"wrong family for {document['program_id']}")

    snapshots = _snapshots() if snapshots is None else snapshots
    allowed_urls = {seed["url"] for seed in manifest().values()}
    allowed_urls.update(meta["url"] for meta, _ in snapshots.values())
    for ref, source in document["sources"].items():
        if source["url"] not in allowed_urls:
            raise ValueError(f"source URL is not in the manifest: {ref}")
        if "snapshot_source_id" not in source:
            continue
        source_id = source["snapshot_source_id"]
        record = snapshots.get(source_id)
        if not record:
            raise ValueError(f"unknown snapshot source: {source_id}")
        meta, sidecar = record
        if source["url"] != meta["url"] or source["sidecar_path"] != sidecar:
            raise ValueError(f"source reference does not match a snapshot: {source_id}")
        if source_id != f"{meta['seed_id']}-{meta['content_hash'][:16]}":
            raise ValueError(f"source ID does not match content hash: {source_id}")
        raw = snapshot_path(meta)
        if (not raw.resolve().is_relative_to(SNAPSHOTS.resolve())
                or hashlib.sha256(raw.read_bytes()).hexdigest() != meta["content_hash"]):
            raise ValueError(f"snapshot hash mismatch: {source_id}")

    def check_evidence(items):
        for item in items:
            if item["source_ref"] not in document["sources"]:
                raise ValueError(f"broken source_ref: {item['source_ref']}")

    thresholds = document["thresholds"]
    for step in document.get("follow_up", []):
        check_evidence(step["evidence"])
    for key, threshold in thresholds.items():
        check_evidence(threshold["evidence"])
        start, end = threshold.get("effective_from"), threshold.get("effective_to")
        if start and end and date.fromisoformat(end) <= date.fromisoformat(start):
            raise ValueError(f"invalid effective period: {key}")
        selectors = [tuple(sorted(row["selectors"].items())) for row in threshold["rows"]]
        if len(selectors) != len(set(selectors)):
            raise ValueError(f"duplicate threshold selector: {key}")

    def visit(node, inherited=False):
        evidence = node.get("evidence", [])
        check_evidence(evidence)
        supported = inherited or bool(evidence)
        if "all" in node or "any" in node:
            for child in node.get("all", node.get("any", [])):
                visit(child, supported)
        elif "field" in node:
            if not supported:
                raise ValueError(f"condition lacks evidence: {node['field']}")
            if "threshold" in node:
                if node["threshold"] not in thresholds:
                    raise ValueError(f"missing threshold: {node['threshold']}")
                keys = set(node.get("selectors", {}))
                row_keys = {frozenset(row["selectors"]) for row in thresholds[node["threshold"]]["rows"]}
                if row_keys != {frozenset(keys)}:
                    raise ValueError(f"selector fields do not match threshold rows: {node['threshold']}")
        elif "unknown" in node and not supported:
            raise ValueError("unknown condition lacks evidence")

    visit(document["eligibility"])
    return document


def validate_all():
    snapshots = _snapshots()
    paths = sorted(PROGRAMS.glob("*.json"))
    documents = [validate_program(path, snapshots) for path in paths]
    ids = [document["program_id"] for document in documents]
    if len(ids) != len(set(ids)) or set(ids) != set(FAMILIES):
        raise ValueError("documents must contain each of the eight program IDs once")
    if any(path.stem != document["program_id"] for path, document in zip(paths, documents)):
        raise ValueError("program filename does not match program_id")
    return documents


def overview():
    """Summarize the validated eight-program catalog."""
    programs = []
    for document in validate_all():
        programs.append({
            "program_id": document["program_id"],
            "name": document["name"],
            "agency": document["agency"],
            "family": document["family"],
            "summary": document["summary"],
            "application_url": document["application_url"],
            "status": "reviewed",
        })
    return {"programs": sorted(programs, key=lambda item: item["program_id"])}


def _compare(left, op, right):
    if op == "in":
        return left in right if isinstance(right, list) else None
    if isinstance(left, bool) != isinstance(right, bool) or type(left) is not type(right):
        return None
    if op in ("<", "<=", ">", ">=") and (isinstance(left, bool) or not isinstance(left, (int, float))):
        return None
    comparisons = {"==": operator.eq, "!=": operator.ne,
                   "<": operator.lt, "<=": operator.le,
                   ">": operator.gt, ">=": operator.ge}
    return comparisons[op](left, right)


def evaluate(document, profile, on_date=None):
    """Evaluate a discovery screen; a positive result never confirms entitlement."""
    day = date.fromisoformat(on_date or document["as_of"])
    evidence_used = []

    calculation_names = {
        "ssi_applicable_monthly_federal_rate_cents": "SSI federal rate for this category and living arrangement",
        "ssi_countable_monthly_income_cents": "SSI monthly countable income after exclusions and deeming",
        "ssi_countable_resources_cents": "SSI countable resources after exclusions and deeming",
        "extra_help_countable_annual_income_cents": "Extra Help countable annual income",
        "extra_help_countable_resources_cents": "Extra Help countable resources",
        "extra_help_geography_supported": "whether the person's region is covered by the modeled Extra Help limits",
        "va_applicable_mapr_cents": "Veterans Pension MAPR including tier and dependents",
        "va_applicable_survivor_mapr_cents": "Survivors Pension MAPR including tier, children, and custody",
        "va_income_for_purposes_annual_cents": "VA-purpose annual income after allowed deductions",
        "va_survivor_income_for_purposes_annual_cents": "VA-purpose survivor annual income after allowed deductions",
        "va_net_worth_for_pension_cents": "VA pension net worth after exclusions",
        "va_survivor_net_worth_cents": "VA survivor net worth after exclusions",
    }

    def is_agency_check(field):
        return (field.startswith(("ssa_", "va_", "ssi_", "deceased_worker_", "deceased_veteran_")) or field in {
            "worker_entitled_to_retirement_or_disability", "worker_fully_insured_for_independent_divorced_spouse",
            "medicare_drug_coverage_eligible", "esrd_medicare_pathway_confirmed",
            "medicare_citizenship_or_residency_requirement_met",
            "remarriage_rule_met", "continuous_cohabitation_met",
            "full_benefit_medicaid", "state_pays_part_b_premium_msp", "receives_ssi_payment",
        })

    def check_name(field):
        if field in calculation_names:
            return f"unsupported calculation: {calculation_names[field]} ({field})"
        if is_agency_check(field):
            return f"agency determination needed: {field}"
        return f"profile input needed: {field}"

    def record_evidence(node):
        for item in node.get("evidence", []):
            source = document["sources"][item["source_ref"]]
            resolved = {"source_ref": item["source_ref"], "url": source["url"], "locator": item["locator"]}
            if "snapshot_source_id" in source:
                resolved["snapshot_source_id"] = source["snapshot_source_id"]
                resolved["sidecar_path"] = source["sidecar_path"]
            if resolved not in evidence_used:
                evidence_used.append(resolved)

    def node_result(node):
        record_evidence(node)
        if "unknown" in node:
            return None, [], [node["unknown"]], []
        if "all" in node:
            values = [node_result(child) for child in node["all"]]
            supported = [reason for value, good, _, _ in values if value is True for reason in good]
            if any(value is False for value, *_ in values):
                failed = [reason for value, _, _, bad in values if value is False for reason in bad]
                return False, supported, [], failed
            if any(value is None for value, *_ in values):
                unresolved = [reason for value, _, checks, _ in values if value is None for reason in checks]
                return None, supported, unresolved, []
            return True, supported, [], []
        if "any" in node:
            values = [node_result(child) for child in node["any"]]
            winner = next((item for item in values if item[0] is True), None)
            if winner:
                return winner
            if any(value is None for value, *_ in values):
                unresolved = [reason for value, _, checks, _ in values if value is None for reason in checks]
                return None, [], unresolved, []
            failed = [reason for _, _, _, bad in values for reason in bad]
            return False, [], [], failed
        field = node["field"]
        if field not in profile or profile[field] is None:
            return None, [], [check_name(field)], []
        target = node.get("value")
        if "threshold" in node:
            threshold = document["thresholds"][node["threshold"]]
            start, end = threshold.get("effective_from"), threshold.get("effective_to")
            if (start and day < date.fromisoformat(start)) or (end and day >= date.fromisoformat(end)):
                return None, [], [f"threshold outside effective period: {node['threshold']}"], []
            selector_values = {}
            for key, field_name in node.get("selectors", {}).items():
                if field_name not in profile or profile[field_name] is None:
                    return None, [], [check_name(field_name)], []
                selector_values[key] = profile[field_name]
            rows = [row for row in threshold["rows"] if row["selectors"] == selector_values]
            if len(rows) != 1:
                return None, [], [f"unsupported threshold selection: {node['threshold']} ({selector_values})"], []
            row = rows[0]
            if "input_field" in row:
                threshold_field = row["input_field"]
                if threshold_field not in profile or profile[threshold_field] is None:
                    return None, [], [check_name(threshold_field)], []
                target = profile[threshold_field]
                if type(target) is not int or target < 0:
                    return None, [], [f"invalid threshold input: {threshold_field}"], []
            else:
                target = row["value"]
        result = _compare(profile[field], node["operator"], target)
        if result is None:
            return None, [], [f"incompatible input: {field}"], []
        category = "calculated input" if field in calculation_names else "agency determination" if is_agency_check(field) else "profile fact"
        detail = f"{category}: {field} {node['operator']} {target}"
        return result, [detail] if result else [], [], [] if result else [detail]

    result, supported, unresolved, failed = node_result(document["eligibility"])
    return {"program_id": document["program_id"],
            "result": "unknown" if result is None else "potential_match" if result else "fails_documented_condition",
            "supported_reasons": list(dict.fromkeys(supported)),
            "unresolved_checks": list(dict.fromkeys(unresolved)),
            "failed_reasons": list(dict.fromkeys(failed)),
            "application_url": document["application_url"],
            "follow_up": document.get("follow_up", []),
            "evidence": evidence_used}


