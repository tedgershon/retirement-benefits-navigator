# Federal retirement benefits data

This MVP maintains eight approved, evidence-linked program documents and checks a bounded list of official sources. Matching screens for benefits worth exploring; it does not make agency eligibility, enrollment, or payment decisions. [Discovery](docs/discovery.md) and [coverage gaps](docs/coverage-gaps.md) describe its limits.

## Data layout

| Path | Contents |
| --- | --- |
| `data/raw/<seed_id>/` | Original downloaded bytes and JSON metadata sidecars (bronze) |
| `data/core/<seed_id>/` | Unreviewed source extractions (silver) |
| `data/curated/programs/<program_id>.json` | Eight approved program documents (gold) |
| `data/reports/<UTC YYYY-MM-DD>/` | Optional source-check reports grouped by check date |

Each program document follows [program.schema.json](schema/program.schema.json). It contains identity and summary metadata, a verified application or how-to-apply URL, an `as_of` assessment date, one nested discovery expression, thresholds, tags, and a local `sources` dictionary. Optional evidenced `follow_up` checks cover actions and timing outside screening. `all` requires every child, `any` requires one, and explicit `unknown` nodes preserve unresolved routes. Missing inputs and unavailable threshold rows return `unknown`. Rule and threshold evidence refers to entries in `sources`. Downloaded sources carry their existing snapshot ID and sidecar path; URL-only evidence is allowed. `as_of` is an assessment date, not a legal effective date; thresholds retain their own effective dates.

The [source manifest](sources.yaml) bounds network fetches. Snapshot and extraction filenames use UTC `YYYY-MM-DD`; distinct items on the same date use `_1`, `_2`, and so on, including the first item. A failed fetch is reported without stopping checks of other sources or deleting saved evidence. Source extractions never become reviewed programs automatically.

## Install and inspect

Use Python 3.11 or newer. On Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[test]'
.\.venv\Scripts\python.exe -m pipeline.cli definitions
.\.venv\Scripts\python.exe -m pipeline.cli catalog
.\.venv\Scripts\python.exe -m pytest -q --basetemp .pytest_tmp
```

If `python` is not on `PATH`, use the full path to your Python 3.11+ executable for the first command. On Unix, use `.venv/bin/python`. `definitions` validates all eight documents. `catalog` generates an overview from them.

The profiles under `tests/profiles/` describe fictional people. To match one against an approved program:

```powershell
.\.venv\Scripts\python.exe -m pipeline.cli match social_security_retirement tests/profiles/retirement_profile.json
.\.venv\Scripts\python.exe -m pipeline.cli match social_security_spouse tests/profiles/spouse_profile.json
.\.venv\Scripts\python.exe -m pipeline.cli match medicare_eligibility tests/profiles/medicare_profile.json
.\.venv\Scripts\python.exe -m pipeline.cli match medicare_part_d_extra_help tests/profiles/extra_help_profile.json
```

All eight program IDs can be used with `match`. The [older-adult cases](tests/test_discovery.py) cover the five recently approved definitions.

Use `--on-date YYYY-MM-DD` to choose the date for threshold checks; otherwise the document's `as_of` date is used. Results are `potential_match`, `fails_documented_condition`, or `unknown`. Output includes supported reasons, unresolved checks, failed reasons, evidence, follow-up actions, and an official application link. A potential match is a discovery result, not confirmed entitlement. Missing inputs, unsupported calculations or selectors, and out-of-period thresholds remain unknown. Retirement discovery screens on age 62 or older and SSA fully insured status; application and exact entitlement month are follow-up checks. Do not commit personal profiles.

To refresh selected official evidence (these commands write under `data/`):

```powershell
$reportDate = (Get-Date).ToUniversalTime().ToString('yyyy-MM-dd')
.\.venv\Scripts\python.exe -m pipeline.cli fetch ssa_retirement_entitlement va_veterans_pension_rates --report "data/reports/$reportDate/selected-fetch.json"
.\.venv\Scripts\python.exe -m pipeline.cli extract data/raw/ssa_retirement_entitlement/2026-10-06.json data/raw/va_veterans_pension_rates/2026-10-07.json
.\.venv\Scripts\python.exe -m pipeline.cli definitions
```

For later checks, find the selected sidecars under `data/raw/<seed_id>/`; the dates above are examples from the verified run. `extract` without paths processes all saved sidecars. `fetch <seed_id> ...` checks selected sources and reuses an identical saved response. The report includes per-source failures. GovInfo U.S. Code links resolve to the latest published edition, which may lag enacted changes. Some ordinary SSA guidance pages return 403 to the repository HTTP client; their agent-read source notes remain under `data/core/` without pretending to be raw snapshots. Fetch and extraction failures do not modify reviewed program documents.

The five other recently approved definitions focus on common older-adult pathways and mark peripheral routes unknown. The two VA pension definitions use a strict income-below-MAPR check for a potentially positive base payment. Their calculations and other [coverage gaps](docs/coverage-gaps.md) remain documented limits.

## Deferred database integration

[schema.sql](schema/schema.sql) remains the single-table PostgreSQL reference, unchanged for this milestone. The JSON workflow requires no database; there is no database loader or PostgreSQL dependency in the current pipeline.

Eligibility and financial calculations still have [coverage gaps](docs/coverage-gaps.md); a potential match is not a final benefit determination.
