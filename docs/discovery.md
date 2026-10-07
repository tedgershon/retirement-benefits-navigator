# Discovery screening coverage

Normal matching means **benefit discovery**. `potential_match` says that the documented screen is satisfied with the supplied facts; it does not say the agency has awarded, enrolled, or calculated a payment. A missing fact or unsupported route is `unknown`. The owner has approved all eight preliminary definitions for discovery screening; they are in `data/curated/programs/`.

## Input and rule boundaries across all eight programs

| Program | Ordinary profile facts evaluated | Existing agency determination or record needed | Calculation or pathway still unsupported |
| --- | --- | --- | --- |
| Social Security retirement | Age | Fully insured status | Exact first entitlement month and work-credit computation remain outside screening. Filing is follow-up. |
| Social Security spouse | Relationship category, marriage duration, age | Worker entitlement, legally qualifying relationship, own/worker PIA comparison | Relationship exceptions and detailed child-in-care route; precise entitlement timing is follow-up. |
| Social Security survivor | Widow/divorced-widow relationship, age, marriage duration | Deceased-worker insurance, remarriage-rule outcome, own/decedent PIA comparison | Disabled-widow, dependent-parent, child/student, and mother/father routes; payment timing is follow-up. |
| Federal SSI | Age and household category | Citizenship/noncitizen and residency outcomes; institutional, absence, transfer and legal-bar checks | Countable resources, countable income, deeming, and applicable federal rate need agency calculation or a separately verified input. Filing for other benefits and financial permission are follow-up actions, with evidence retained in JSON. |
| Medicare eligibility | Age and disability-benefit months | Citizenship/residency composite, ALS/disability status | ESRD and separate Part A/Part B paths; enrollment and coverage start are follow-up. |
| Part D Extra Help | Household and residence region | Part D eligibility, Medicaid/MSP/SSI automatic-qualification status | The current region-supported flag and countable income/resources need verified derivation; Alaska/Hawaii and exception routes remain unsupported. Part D enrollment is follow-up. |
| VA Veterans Pension | Wartime/service days, entry route, age, dependents | Discharge, wartime-service and minimum-duty exceptions, disability/tier checks | VA-purpose income/net worth, transfer penalties, and additional-dependent MAPR calculation. |
| VA Survivors Pension | Relationship, service days, remarriage fact, family case | Deceased Veteran service/discharge, cohabitation/remarriage exceptions, assistance tier | VA-purpose income/net worth, transfer penalties, additional-child MAPR and child-custodian formula. |

The evaluator labels supplied values as `profile fact`, `agency determination`, or `calculated input` in `supported_reasons`. When a calculation is absent, `unresolved_checks` names the calculation instead of presenting an unexplained boolean gate. Using an agency determination in a real profile still requires that determination to exist; owner approval of a preliminary screen does not supply it.

## Five program screens

All cases below are **synthetic tests of the reviewed JSON**. The five programs now enter normal CLI matching. Each passing case supplies the named agency outcomes or calculated amounts; it cannot substitute for an agency decision.

### `social_security_spouse`

- **Supported older-adult path:** current spouse aged 62 or older, worker entitled to retirement/disability, qualifying relationship and marriage duration, own PIA below half the worker's PIA. The divorced-spouse route remains modeled with its separate ten-year marriage and independent two-year divorce checks. Evidence: [SSA spouse requirements](https://secure.ssa.gov/poms.nsf/lnx/0300202001), [divorced-spouse requirements](https://secure.ssa.gov/apps10/poms.nsf/lnx/0300202005).
- **Still unknown:** legal/deemed relationship details and exact timing require SSA verification. Child-in-care branches now explicitly return `unknown` even when their preliminary facts are positive.
- **Test cases:** age 67, two-year marriage and positive worker/PIA determinations → `potential_match`; worker not entitled → `fails_documented_condition`; missing worker or relationship determination → `unknown`.

### `social_security_survivor`

- **Supported older-adult path:** widow or surviving divorced spouse, age 60 or older, qualifying marriage, deceased-worker insurance and remarriage/own-PIA outcomes. Evidence: [SSA widow requirements](https://secure.ssa.gov/poms.nsf/lnx/0300207001), [SSA survivor overview](https://www.ssa.gov/survivor).
- **Still unknown:** disability onset/prescribed periods, remarriage exceptions, child/student, dependent-parent, and mother/father routes. The latter three routes now have explicit unknown guards rather than positive matches from compressed booleans.
- **Test cases:** age 67 widow, 12-month marriage and positive insurance/remarriage/PIA outcomes → `potential_match`; deceased worker uninsured → `fails_documented_condition`; missing insured-status determination → `unknown`.

### `ssi_federal`

- **Supported older-adult path:** age 65 or older, resources within the documented household limit, positive residency/citizenship and monthly nonfinancial checks, countable income below the case-specific federal rate. Evidence: [SSA SSI eligibility](https://www.ssa.gov/ssi/eligibility), [SSA income calculation](https://www.ssa.gov/ssi/text-income-ussi.htm), [SSA resources](https://www.ssa.gov/ssi/text-resources-ussi.htm).
- **Still unknown:** no reusable countable-income, resource/deeming, or living-arrangement federal-rate calculator is implemented; a provided value must already be verified. Blindness/disability routes now explicitly stay unknown. Filing for other benefits after SSA's written notice and financial-record permission are retained as evidenced `follow_up` actions, not prior discovery gates. Evidence: [other-benefit filing](https://secure.ssa.gov/apps10/poms.nsf/lnx/0500510001), [financial permission](https://secure.ssa.gov/poms.nsf/lnx/0500515001).
- **Test cases:** age 67, individual resources $0, verified $994 federal rate and $0 countable income, other checks positive → `potential_match`; resources $2,000.01 → `fails_documented_condition`; missing applicable rate → `unknown` naming the unsupported calculation.

### `va_veterans_pension`

- **Supported older-adult path:** qualifying discharge and wartime service, documented minimum-duty route, age 65 or older, net worth within the 2025-12-01 to 2026-11-30 limit, and income below the selected MAPR for a potentially positive base payment. Evidence: [VA eligibility](https://www.va.gov/pension/eligibility/), [VA rates](https://www.va.gov/pension/veterans-pension-rates/).
- **Still unknown:** VA-purpose deductions/net worth, transfer penalties, service exceptions, and MAPR with additional dependents need agency calculations or verification. Under-65 disability/institutional routes now explicitly stay unknown.
- **Test cases:** age 67, 90-day pre-1980 service, one wartime day, positive VA outcomes and $0 income/net worth → `potential_match`; net worth $163,700 → `fails_documented_condition`; missing service-route or financial calculation → `unknown`.

### `va_survivors_pension`

- **Supported older-adult path:** surviving spouse of a qualifying wartime Veteran, positive remarriage/cohabitation outcomes, net worth within the limit and income below the selected MAPR. Evidence: [VA Survivors Pension](https://www.va.gov/family-and-caregiver-benefits/survivor-compensation/survivors-pension/), [VA survivor rates](https://www.va.gov/family-and-caregiver-benefits/survivor-compensation/survivors-pension/rates/).
- **Still unknown:** VA-purpose income/net worth, service and remarriage exceptions, transfer penalties and additional-child MAPR calculations. The separate surviving-child/custodian route now explicitly stays unknown.
- **Test cases:** surviving spouse, one wartime service day, positive VA determinations and $0 income/net worth → `potential_match`; net worth $163,700 → `fails_documented_condition`; missing service determination or case-specific MAPR → `unknown`.

The executable cases are in `tests/test_discovery.py`; broader gaps remain in [coverage gaps](coverage-gaps.md). These five definitions are approved for their current discovery scope.
