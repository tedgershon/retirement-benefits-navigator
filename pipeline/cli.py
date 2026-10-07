"""Fetch evidence, validate program documents, and match reviewed programs."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from .definitions import evaluate, overview, program_path, validate_all, validate_program
from .evidence import EXTRACTED, SNAPSHOTS, extract, fetch, manifest, snapshot_sidecars


def main(argv=None):
    parser = argparse.ArgumentParser(prog="benefits")
    commands = parser.add_subparsers(dest="command", required=True)
    fetch_cmd = commands.add_parser("fetch")
    fetch_cmd.add_argument("seed_ids", nargs="*")
    fetch_cmd.add_argument("--all", action="store_true", help="check every curated source")
    fetch_cmd.add_argument("--report", help="write a UTF-8 JSON check report to this path")
    extract_cmd = commands.add_parser("extract")
    extract_cmd.add_argument("sidecars", nargs="*", help="snapshot sidecar JSON paths; defaults to all snapshots")
    catalog_cmd = commands.add_parser("catalog")
    catalog_cmd.add_argument("--validate", action="store_true", help="validate and count all eight programs")
    commands.add_parser("definitions", help="validate all eight approved program documents")
    match_cmd = commands.add_parser("match", help="evaluate a reviewed program against a local JSON profile")
    match_cmd.add_argument("program_id")
    match_cmd.add_argument("profile", help="path to a local, non-sensitive JSON profile")
    match_cmd.add_argument("--on-date", help="YYYY-MM-DD; defaults to the definition's as_of date")
    args = parser.parse_args(argv)
    if args.command == "fetch":
        seeds = manifest()
        if args.all and args.seed_ids:
            parser.error("choose --all or explicit seed IDs")
        ids = list(seeds) if args.all else args.seed_ids
        if not ids:
            parser.error("fetch requires --all or at least one seed ID")
        unknown = set(ids) - set(seeds)
        if unknown:
            parser.error(f"unknown seed IDs: {', '.join(sorted(unknown))}")
        results = []
        checked_at = datetime.now(timezone.utc).isoformat()
        last_host = {}
        for seed_id in ids:
            try:
                snapshot = fetch([seed_id], seeds, last_host=last_host)[0]
                results.append({"seed_id": seed_id, "status": "saved", "source_id": snapshot["source_id"],
                                "fetched_at": snapshot["fetched_at"], "checked_at": checked_at})
            except Exception as error:
                results.append({"seed_id": seed_id, "status": "failed", "error": str(error), "checked_at": checked_at})
        report = json.dumps(results, indent=2) + "\n"
        if args.report:
            path = Path(args.report)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(report, encoding="utf-8")
        print(report, end="")
        if any(item["status"] == "failed" for item in results):
            raise SystemExit(1)
    elif args.command == "extract":
        paths = args.sidecars or [str(p) for p in snapshot_sidecars(SNAPSHOTS)]
        print(json.dumps([str(path) for path in extract(paths, EXTRACTED)], indent=2))
    elif args.command == "catalog":
        catalog = overview()
        print(f"valid: {len(catalog['programs'])} programs" if args.validate else json.dumps(catalog, indent=2))
    elif args.command == "definitions":
        print(f"valid: {len(validate_all())} programs")
    elif args.command == "match":
        try:
            path = program_path(args.program_id)
        except ValueError:
            parser.error(f"unknown or missing program: {args.program_id}")
        definition = validate_program(path)
        profile = json.loads(Path(args.profile).read_text(encoding="utf-8"))
        if not isinstance(profile, dict):
            parser.error("profile must be a JSON object")
        print(json.dumps(evaluate(definition, profile, args.on_date), indent=2))


if __name__ == "__main__":
    main()
