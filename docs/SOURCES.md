# Data sources

Chosen on 2026-11-17. Downloads go in `data/` (git-ignored); this file records what was used and where it came from.

## Tables (Chicago Data Portal)

| Table | Dataset id | Postgres table | Date filter | Notes |
| --- | --- | --- | --- | --- |
| [311 Service Requests](https://data.cityofchicago.org/d/v6vf-nfxy) | `v6vf-nfxy` | `service_requests_311` | `created_date` | Exclude `duplicate = true` for "unique problems". `origin` = Generated In House / Mass Entry are city-generated, not resident reports |
| [Building Violations](https://data.cityofchicago.org/d/22u3-xenr) | `22u3-xenr` | `building_violations` | `violation_date` | Department of Buildings violations, 2006 to present. Historical record, not current building condition |
| [Building Permits](https://data.cityofchicago.org/d/ydr8-5enu) | `ydr8-5enu` | `building_permits` | `issue_date` | Permits issued 2006 to present, excluding voided or revoked permits. `permit_condition` column added Oct 2025 |

Load with `python -m ingest.load_tables --since 2025-01-01`. Run `--check` first: the violations and permits column lists are unconfirmed.

## Documents

### Municipal Code of Chicago (housing and buildings)

Source: [American Legal Publishing](https://codelibrary.amlegal.com/codes/chicago/latest/chicago_il), an informational copy (not the official version). Download each chapter with the page's **Download** or **Print to PDF** button into `data/docs/code/`. Download by hand; don't crawl the site.

| Chapter | Why it's in scope | Save as |
| --- | --- | --- |
| **14X-8** Mechanical (Minimum Requirements for Existing Buildings) | The Heat Ordinance: 14X-8-802 / 14X-8-803. Minimum indoor temperatures and the heating season | `14X-8.pdf` |
| **5-12** Residential Landlord and Tenant Ordinance (RLTO) | Landlord and tenant duties; tenant remedies, including for no heat (5-12-110) | `5-12.pdf` |
| **5-16** Disclosure of Utility Costs to Tenants | Heating cost disclosure for individually metered units | `5-16.pdf` |
| Optional: **14X-3** General / property maintenance | Broader "is this a violation?" questions | `14X-3.pdf` |

**Trap worth an eval question:** many websites still cite the heat rule as **13-196-410**, an older section number. The city now cites **14X-8-803**. Good answers cite the current section; the old number is a known way for a model to cite from memory instead of from retrieval.

The heat rule also has season details beyond "68°F day / 66°F night" (for example, different requirements early and late in the heating season). That makes it good material for faithfulness checks.

### Budget PDF

| Document | Status | Save as |
| --- | --- | --- |
| **2027 Budget Recommendations / Budget Overview** ([OBM budget page](https://www.chicago.gov/city/en/depts/obm/provdrs/budget.html)) | **Proposed** by the Mayor on 2026-10-21; under City Council debate | `data/docs/budget/2027-budget-overview.pdf` |
| Fallback: 2026 budget as passed ([City Clerk](https://www.chicityclerk.com/node/11197)) | Adopted Dec 2025, including Council amendments | `data/docs/budget/2026-budget-passed.pdf` |

**Trap worth an eval question:** a *proposed* budget is not the *adopted* budget. In 2026, the Council passed its own alternative to the Mayor's proposal. Answers from the 2027 book should say "proposed".

## Not used (yet)

- City Council ordinances (eLMS): out of scope for the 2-week build
- 311 historical datasets (pre-December 2018 system): replaced by `v6vf-nfxy`
