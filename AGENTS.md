# Current MVP scope

The eight program IDs are `social_security_retirement`, `social_security_spouse`, `social_security_survivor`, `ssi_federal`, `medicare_eligibility`, `medicare_part_d_extra_help`, `va_veterans_pension`, and `va_survivors_pension`. Additional programs and a user-facing app are outside scope.

Each program is one complete JSON document validated by `schema/program.schema.json`. All eight preliminary definitions have the owner's approval for discovery screening and live in `data/curated/programs/<program_id>.json`. The approved Social Security retirement definition screens on age and fully insured status; application and first entitlement month remain follow-up checks. Source extractions in `data/core/` do not enter normal matching.

The complete document contains identity and descriptive metadata, nullable verified `application_url`, `as_of` assessment date, eligibility expression, thresholds, tags, and document-local `sources`. Git is the intended revision history. Do not add `definition_revision`, `scope`, `version_id`, review fields, whole-document effective dates, or a second catalog. Preserve `unknown` branches and threshold effective dates. Missing input or missing applicable threshold remains unknown. Tags never decide eligibility. Keep coverage gaps in `docs/coverage-gaps.md`.

Fetch only targets in `sources.yaml`; do not build a crawler. Keep original responses and sidecars in `data/raw/<seed_id>/`, unreviewed extraction in `data/core/<seed_id>/`, and source-check reports in `data/reports/<UTC YYYY-MM-DD>/`. Use UTC `YYYY-MM-DD` filenames for one saved snapshot or extraction on a date; when a second distinct item appears, rename the first to `_1` and number later items `_2`, `_3`, and so on. Preserve original bytes, snapshot IDs, paths, and hashes. A failed source check must not stop other checks or delete prior data.

`schema/schema.sql` is an unchanged, deferred PostgreSQL reference. The current MVP uses JSON files directly and has no database loader. Do not provision or modify a database for this milestone.

Do not fabricate legal rules, thresholds, dates, application URLs, or snapshot metadata. Do not commit personal profiles. Test profiles are fictional. Keep commands and limitations current in `README.md`.
