# Tables for the SQL agent

This file goes into the SQL agent's prompt. It describes the three Postgres tables, their columns, the real values they contain, and the rules for querying them correctly. Every value list and count here comes from the loaded database (loaded 2026-11-18, data from **2025-01-01** to 2026-11-18).

Database: Postgres 16. The agent connects as the read-only `civic_reader` role (SELECT only, 15 s statement timeout).

## Rules for every query

1. **Data starts on 2025-01-01.** If a question asks about an earlier period, say the data doesn't cover it; don't answer from a partial range.
2. **Date ranges are half-open:** `created_date >= '2026-01-01' AND created_date < '2027-01-01'`. Date columns are `timestamp` (Chicago local time, no time zone).
3. **Return counts and aggregates, not raw rows,** unless the question asks for a list. Always `LIMIT` lists (50 or fewer).
4. **Say what you filtered.** The answer must mention filters that change the meaning: duplicates removed, city-generated requests removed, a date range.
5. **Refuse what the tables can't answer** (see "Not in these tables" at the end) instead of guessing.
6. **Data ends 2026-11-18** (311) and 2026-11-17 (violations, permits). Write dates as literals (`'2026-01-01'`), never `CURRENT_DATE` or `now()`: "today" is given with the question. If the period asked about runs past the end of the data, say so in the notes; if it lies entirely after it, refuse.

## Matching values and text

Checked on every value of every category column, and on the free-text columns (2026-11-25).

- **Request types: use codes, never word matches.**
  - **A specific type named in the question means that one code only:** "street light out complaints" = `SFD` alone, "stop sign repairs" = `PCB`, "alley potholes" = `PHB`.
  - **A general category** ("street light complaints", "sign repairs", "tree requests") means *every* matching type from the list below; name the codes in the notes:
  - signs = `PCE`, `PCB`, `PCC`, `PCD` (the 4 "Sign Repair Request" types);
  - trees = `SEF`, `SEL`, `SEC`, `SEE`, `SED`;
  - rats = `SGA` only;
  - street lights = `SFD`, `SFK`, `SFQ`, `SFN`;
  - potholes = `PHF` (Pothole in Street Complaint) only. Add `PHB` (Alley Pothole Complaint) only when the question mentions alleys.
- **Why not `ILIKE`:** a word inside another word matches too. On `sr_type`:

  | `ILIKE` | Also matches |
  | --- | --- |
  | `'%tree%'` | S**tree**t … (potholes, street lights, street cleaning) |
  | `'%rat%'` | Inacc**urat**e Fuel Pump, Inacc**urat**e Retail Scales |
  | `'%sign%'` | Traffic **Sign**al Out |
  | `'%cab%'` | **Cab**le TV |
  | `'%pet%'` | **Pet**coke Dust |
  | `'%cart%'` | Push**cart** Food Vendor |
  | `'%air%'` | Sign Rep**air** … |
  | `'%ice%'` | Submerged … Dev**ice** |

- **Non-ASCII characters in values:** `Snow – Uncleared Sidewalk Complaint` (`SWSNOREM`) uses an en dash, like the express permit type; `Sidewalk Café/Outdoor Dining Complaint` (`CAFE`) has an accented é, so `'%cafe%'` finds nothing. Use the codes.
- **Free-text columns** (`work_description`, `violation_description`, `violation_inspector_comments`): match words at the **start of a word** with a regular expression, `work_description ~* '\msolar'` (`\m` = start of a word; it still matches "solar" and "solar-powered"). Not `ILIKE '%…%'`:

  | Search on `building_permits.work_description` | `ILIKE '%…%'` | `~* '\m…'` |
  | --- | --- | --- |
  | rat | 10,578 (ope**rat**e, alte**rat**ion, deco**rat**ive …) | 91 |
  | tree | 207 | 23 |
  | heat | 742 | 694 |

  On `violation_description`, `'%roof%'` also matches "fire**proof**" (943 vs 724).
- **Quotes inside values are doubled** in SQL: `origin = 'Alderman''s Office'` (97,111 rows), `'Mayor''s Office'`, `'City Clerk''s Office'`.
- **Addresses:** `building_violations.address` and the permit street parts are all upper case, but 2,576 `service_requests_311.street_address` values aren't. Compare with `upper(street_address) = upper('6800 s dorchester ave')`, and upper-case addresses given in lower case for the other tables.

---

## `service_requests_311`

311 service requests: residents (and city staff) asking the city to fix something. **One row = one request.** Source: Chicago Data Portal [`v6vf-nfxy`](https://data.cityofchicago.org/d/v6vf-nfxy). **1,819,028 rows**, `created_date` 2025-01-01 to 2026-11-18.

**Not loaded:** `311 INFORMATION ONLY CALL` (calls that only asked for information) and `Aircraft Noise Complaint`. Together they were 2,036,231 rows, over half the dataset, and were left out to fit the free database tier. Questions about either must be refused: "aircraft noise complaints and information-only calls aren't in this dataset".

| Column | Type | Meaning | Values / notes |
| --- | --- | --- | --- |
| `sr_number` | text | Request id, unique | e.g. `SR25-02093421` |
| `sr_type` | enum | Request type, full name | 103 values, listed below. Exact match only |
| `sr_short_code` | enum | Short code for the type, one per `sr_type` | e.g. `PHF` = pothole. **Filter on this** (indexed) |
| `owner_department` | enum | City department handling it | 12 values, below |
| `status` | enum | `Completed` (1,618,958), `Open` (134,406), `Canceled` (65,664) | Only `Open` rows have no `closed_date` |
| `origin` | enum | How the request came in | 34 values; main ones below |
| `created_date` | timestamp | When the request was made | Indexed |
| `closed_date` | timestamp | When it was closed | NULL for open requests (7.4%) |
| `street_address` | text | Address of the problem | e.g. `6800 S DORCHESTER AVE` |
| `ward` | smallint | City Council ward, 1 to 50 | NULL in 0.2% |
| `community_area` | smallint | Community area number, 1 to 77 | Numbers only; no names table |
| `zip_code` | text | ZIP code | NULL in 27.7%: don't use for coverage claims |
| `duplicate` | boolean | Marked as a duplicate of another request | 159,688 rows (8.8%) |
| `parent_sr_number` | text | For duplicates and follow-ups, the original request | Set on 8.8% of rows |
| `latitude`, `longitude` | double precision | Location | NULL in 0.2% |

### 311 traps

- **Duplicates.** Several people report the same pothole; the city marks the extra reports `duplicate = true`. **Add `AND NOT duplicate` by default**, so counts mean "distinct problems". Include duplicates only if the question asks about reports, calls or duplicates. Duplicate rates differ a lot by type: 38% of pothole requests, 44% of open hydrant requests, 0% of abandoned vehicles. So leaving them in distorts comparisons between types.
- **City-generated requests.** `origin` `'Mass Entry'` (144,774 rows) and `'Generated In House'` (8,619) are created by city staff, not reported by residents.
  - **Keep them by default.** "How many pothole complaints / sign repair requests / tree requests" counts every request of that type, whoever entered it. The words "complaint" and "request" don't mean residents: many types are named "… Complaint" or "… Request".
  - **Exclude them only when the question is about residents** ("what do residents report", "where do residents complain most"): add `AND origin NOT IN ('Generated In House', 'Mass Entry')` and say so in the notes.
- **Enum columns** (`sr_type`, `sr_short_code`, `owner_department`, `status`, `origin`):
  - `=` and `IN` work with text, but **a value that isn't in the list is an error**, not 0 rows. Use only values from this file.
  - `LIKE` / `ILIKE` need a cast: `sr_type::text ILIKE '%tree%'`.
- **Prefer `sr_short_code`** to `sr_type`: shorter, indexed, no typos. Pick the codes from the table below rather than matching words (see "Matching values and text"): `sr_type::text ILIKE '%tree%'` gives 202,905 rows in 2025 instead of 123,441 for the 5 tree types. Tree trim requests (`SEF`) are labelled "NO LONGER BEING ACCEPTED" but still have 76,064 rows in the period.
- **Time to close:** `closed_date - created_date` is an interval; days = `extract(epoch FROM closed_date - created_date) / 86400`. Use only `status = 'Completed'`. Prefer the median (`percentile_cont(0.5) WITHIN GROUP (ORDER BY ...)`): a few slow requests pull the average up. One row has `closed_date` before `created_date`.

### Values

`owner_department`: Streets and Sanitation (1,008,638) · CDOT - Department of Transportation (370,915) · DWM - Department of Water Management (170,932) · DOB - Buildings (80,612) · Animal Care and Control (74,788) · Finance (41,969) · Outside Agencies (29,512) · BACP - Business Affairs and Consumer Protection (24,058) · City Clerk's Office (8,665) · Health (7,921) · Fire (707) · Department of Housing (311)

`origin` (main values): Phone Call (678,039) · Internet (447,719) · Mobile Device (392,329) · Mass Entry (144,774) · Alderman's Office (97,111) · Salesforce Mobile App (15,400) · DWM (14,848) · SPOTCSR (13,139) · Generated In House (8,619) · City Department (1,767) · E-Mail (1,009) · Walk-in (629). 22 more values have fewer than 1,600 rows each; 464 rows have an empty origin.

### All request types

`sr_short_code` → `sr_type`, department, rows (duplicates included), share that are duplicates. Ordered by rows.

| Code | Type (`sr_type`) | Department | Rows | Duplicates |
| --- | --- | --- | --- | --- |
| `GRAF` | Graffiti Removal Request | Streets and Sanitation | 181,092 | 4% |
| `PHF` | Pothole in Street Complaint | CDOT - Department of Transportation | 103,449 | 38% |
| `SKA` | Abandoned Vehicle Complaint | Streets and Sanitation | 100,609 | 0% |
| `SIE` | Garbage Cart Maintenance | Streets and Sanitation | 99,411 | 3% |
| `SGA` | Rodent Baiting/Rat Complaint | Streets and Sanitation | 86,214 | 3% |
| `SEF` | Tree Trim Request (NO LONGER BEING ACCEPTED) | Streets and Sanitation | 76,064 | 0% |
| `SEL` | Tree Debris Clean-Up Request | Streets and Sanitation | 71,523 | 4% |
| `SEC` | Tree Emergency | Streets and Sanitation | 71,163 | 3% |
| `SFD` | Street Light Out Complaint | CDOT - Department of Transportation | 68,561 | 13% |
| `SFB` | Traffic Signal Out Complaint | CDOT - Department of Transportation | 54,451 | 15% |
| `SRRC` | Blue Recycling Cart | Streets and Sanitation | 43,888 | 3% |
| `FPCE` | Finance Parking Code Enforcement Review | Finance | 41,969 | 0% |
| `BBA` | Building Violation | DOB - Buildings | 41,777 | 9% |
| `SEE` | Tree Removal Inspection | Streets and Sanitation | 41,333 | 9% |
| `SCQ` | Yard Waste Pick-Up Request | Streets and Sanitation | 34,642 | 2% |
| `SGQ` | Dead Animal Pick-Up Request | Streets and Sanitation | 33,356 | 14% |
| `SDR` | Fly Dumping Complaint | Streets and Sanitation | 33,260 | 5% |
| `WCA2` | Water Lead Test Kit Request | DWM - Department of Water Management | 31,732 | 0% |
| `SCB` | Sanitation Code Violation | Streets and Sanitation | 29,859 | 3% |
| `AAE` | Water On Street Complaint | DWM - Department of Water Management | 27,760 | 27% |
| `AAF` | Water in Basement Complaint | DWM - Department of Water Management | 26,726 | 4% |
| `PCE` | Sign Repair Request - All Other Signs | CDOT - Department of Transportation | 25,631 | 23% |
| `EAE` | Stray Animal Complaint | Animal Care and Control | 23,833 | 12% |
| `PBD` | Inspect Public Way Request | CDOT - Department of Transportation | 22,273 | 3% |
| `WM3` | Check for Leak | DWM - Department of Water Management | 21,424 | 25% |
| `PHB` | Alley Pothole Complaint | CDOT - Department of Transportation | 20,856 | 37% |
| `CHECKFOR` | Sewer Cleaning Inspection Request | DWM - Department of Water Management | 19,936 | 15% |
| `ESPC` | E-Scooter Parking Complaint | Outside Agencies | 19,189 | 19% |
| `SED` | Tree Planting Request | Streets and Sanitation | 19,095 | 13% |
| `SCC` | Missed Garbage Pick-Up Complaint | Streets and Sanitation | 18,212 | 2% |
| `EAQ` | Report an Injured Animal | Animal Care and Control | 17,512 | 0% |
| `PBS` | Sidewalk Inspection Request | CDOT - Department of Transportation | 16,904 | 24% |
| `BBC` | Buildings - Plumbing Violation | DOB - Buildings | 16,792 | 0% |
| `SCP` | Weed Removal Request | Streets and Sanitation | 16,747 | 9% |
| `SWSNOREM` | Snow – Uncleared Sidewalk Complaint | CDOT - Department of Transportation | 12,543 | 11% |
| `WBT` | Open Fire Hydrant Complaint | DWM - Department of Water Management | 11,831 | 44% |
| `EAB` | Nuisance Animal Complaint | Animal Care and Control | 11,759 | 12% |
| `SFA` | Alley Light Out Complaint | CDOT - Department of Transportation | 11,281 | 9% |
| `SDO` | Ice and Snow Removal Request | Streets and Sanitation | 10,741 | 11% |
| `SRRP` | Recycling Pick Up | Streets and Sanitation | 10,619 | 1% |
| `DBPC` | Divvy Bike Parking Complaint | Outside Agencies | 10,305 | 42% |
| `BBK` | Vacant/Abandoned Building Complaint | DOB - Buildings | 10,274 | 5% |
| `EAF` | Vicious Animal Complaint | Animal Care and Control | 10,257 | 1% |
| `BBD` | No Building Permit and Construction Violation | DOB - Buildings | 9,819 | 7% |
| `SDP` | Street Cleaning Request | Streets and Sanitation | 9,778 | 7% |
| `AAD` | Sewer Cave-In Inspection Request | DWM - Department of Water Management | 9,523 | 13% |
| `SCT` | Clean Vacant Lot Request | Streets and Sanitation | 9,470 | 2% |
| `PCB` | Sign Repair Request - Stop Sign | CDOT - Department of Transportation | 9,106 | 2% |
| `SFK` | Street Light Pole Damage Complaint | CDOT - Department of Transportation | 8,977 | 4% |
| `WBJ` | No Water Complaint | DWM - Department of Water Management | 8,737 | 9% |
| `QAC` | City Vehicle Sticker Violation | City Clerk's Office | 8,665 | 0% |
| `CSC` | Cab Feedback | BACP - Business Affairs and Consumer Protection | 8,306 | 0% |
| `HFB` | Restaurant Complaint | Health | 6,879 | 6% |
| `PET` | Pet Wellness Check Request | Animal Care and Control | 6,723 | 3% |
| `RBL` | Business Complaints | BACP - Business Affairs and Consumer Protection | 6,070 | 6% |
| `WCA3` | Water Lead Test Visit Request | DWM - Department of Water Management | 5,097 | 0% |
| `CIAC` | Coyote Interaction Complaint | Animal Care and Control | 4,326 | 0% |
| `SCSP` | Shared Cost Sidewalk Program Request | CDOT - Department of Transportation | 4,308 | 2% |
| `PCC` | Sign Repair Request - One Way Sign | CDOT - Department of Transportation | 4,064 | 1% |
| `WBK` | Low Water Pressure Complaint | DWM - Department of Water Management | 3,791 | 10% |
| `SDW` | Snow - Object/Dibs Removal Request | Streets and Sanitation | 3,727 | 5% |
| `AAI` | Alley Sewer Inspection Request | DWM - Department of Water Management | 3,040 | 16% |
| `SCS` | Wire Basket Request | Streets and Sanitation | 2,778 | 6% |
| `CSF` | Consumer Fraud Complaint | BACP - Business Affairs and Consumer Protection | 2,504 | 0% |
| `SGV` | Dead Bird | Streets and Sanitation | 2,365 | 3% |
| `SFQ` | Street Light Pole Door Missing Complaint | CDOT - Department of Transportation | 1,855 | 4% |
| `SGG` | Bee/Wasp Removal | Streets and Sanitation | 1,609 | 2% |
| `SFN` | Street Light On During Day Complaint | CDOT - Department of Transportation | 1,532 | 0% |
| `PCL` | Bicycle Request/Complaint | CDOT - Department of Transportation | 1,448 | 9% |
| `PCD` | Sign Repair Request - Do Not Enter Sign | CDOT - Department of Transportation | 1,351 | 1% |
| `CST` | Consumer Retail Business Complaint | BACP - Business Affairs and Consumer Protection | 1,344 | 0% |
| `WCA` | Water Quality Concern | DWM - Department of Water Management | 1,335 | 1% |
| `NAC` | No Air Conditioning | DOB - Buildings | 1,032 | 0% |
| `SHVR` | Shared Housing/Vacation Rental Complaint | BACP - Business Affairs and Consumer Protection | 988 | 0% |
| `PBLDR` | Protected Bike Lane - Debris Removal | CDOT - Department of Transportation | 957 | 29% |
| `CAFE` | Sidewalk Café/Outdoor Dining Complaint | BACP - Business Affairs and Consumer Protection | 935 | 8% |
| `BPI` | Porch Inspection Request | DOB - Buildings | 918 | 1% |
| `MWC` | Wage Complaint | BACP - Business Affairs and Consumer Protection | 760 | 0% |
| `FAC` | Commercial Fire Safety Inspection Request | Fire | 707 | 8% |
| `CSP` | Public Vehicle Complaint | BACP - Business Affairs and Consumer Protection | 706 | 0% |
| `SFC` | Viaduct Light Out Complaint | CDOT - Department of Transportation | 656 | 8% |
| `SNPBLBS` | Snow Removal - Protected Bike Lane or Bridge Sidewalk | CDOT - Department of Transportation | 572 | 24% |
| `HDF` | Lead Inspection Request | Health | 566 | 1% |
| `SCX` | Recycling Inspection Request | Streets and Sanitation | 557 | 3% |
| `NAA` | Clean and Green Program Request | Streets and Sanitation | 526 | 4% |
| `TNP` | Ridesharing Complaint | BACP - Business Affairs and Consumer Protection | 475 | 0% |
| `CORNVEND` | Pushcart Food Vendor Complaint | Health | 467 | 0% |
| `OCC` | Cable TV Complaint | BACP - Business Affairs and Consumer Protection | 403 | 0% |
| `PSL` | Paid Sick Leave Violation | BACP - Business Affairs and Consumer Protection | 392 | 0% |
| `EBD` | Animal In Trap Complaint | Animal Care and Control | 378 | 0% |
| `BAG` | Tobacco - General Complaint | BACP - Business Affairs and Consumer Protection | 338 | 3% |
| `BAM` | Tobacco - Sale to Minors Complaint | BACP - Business Affairs and Consumer Protection | 240 | 3% |
| `BUNGALOW` | Bungalow/Vintage Home Information Request | Department of Housing | 183 | 0% |
| `ODM` | Outdated Merchandise Complaint | BACP - Business Affairs and Consumer Protection | 183 | 0% |
| `FPC` | Inaccurate Fuel Pump Complaint | BACP - Business Affairs and Consumer Protection | 157 | 0% |
| `NOSOLCPP` | No Solicitation Complaint | BACP - Business Affairs and Consumer Protection | 156 | 0% |
| `HOP` | Home Buyer Program Info Request | Department of Housing | 128 | 0% |
| `RFC` | Renters and Foreclosure Complaint | BACP - Business Affairs and Consumer Protection | 89 | 0% |
| `DBES` | Submerged Divvy or Lime Device in the Lake/River | CDOT - Department of Transportation / Outside Agencies | 83 | 0% |
| `PBE` | Pavement Cave-In Inspection Request | CDOT - Department of Transportation | 75 | 0% |
| `INR` | Inaccurate Retail Scales Complaint | BACP - Business Affairs and Consumer Protection | 12 | 0% |
| `HFF` | Smokeless Tobacco at Sports Event Complaint | Health | 8 | 0% |
| `PETCO` | Petcoke Dust Complaint | Health | 1 | 0% |

Notes: `DBES` (submerged Divvy/Lime devices) is the only type with two departments. **No 311 type mentions heat**, so 311 can't answer "how many no-heat complaints". For heat, use the heat violations in `building_violations` (below) and say that's what was counted.

### Examples

```sql
-- How many pothole complaints in ward 25 in 2026? (distinct problems)
SELECT count(*) FROM service_requests_311
WHERE sr_short_code = 'PHF' AND ward = 25 AND NOT duplicate
  AND created_date >= '2026-01-01' AND created_date < '2027-01-01';
-- 721

-- Median days to close rat complaints, by month of 2026
SELECT date_trunc('month', created_date)::date AS month, count(*) AS requests,
       round((percentile_cont(0.5) WITHIN GROUP (
         ORDER BY extract(epoch FROM closed_date - created_date) / 86400))::numeric, 1) AS median_days
FROM service_requests_311
WHERE sr_short_code = 'SGA' AND NOT duplicate AND status = 'Completed'
  AND created_date >= '2026-01-01'
GROUP BY 1 ORDER BY 1;

-- In which wards do residents report the most graffiti? (residents only)
SELECT ward, count(*) AS requests FROM service_requests_311
WHERE sr_short_code = 'GRAF' AND NOT duplicate AND ward IS NOT NULL
  AND origin NOT IN ('Generated In House', 'Mass Entry')
GROUP BY ward ORDER BY requests DESC LIMIT 5;
-- wards 12, 1, 25, 14, 32
```

---

## `building_violations`

Violations written by Department of Buildings inspectors. **One row = one violation**; one inspection usually produces several (24,664 inspections, 90,738 violations, 18,187 addresses). Source: [`22u3-xenr`](https://data.cityofchicago.org/d/22u3-xenr). **90,738 rows**, `violation_date` 2025-01-01 to 2026-11-17.

| Column | Type | Meaning | Values / notes |
| --- | --- | --- | --- |
| `id` | text | Violation id, unique | |
| `violation_date` | timestamp | Date the violation was recorded | Indexed. Date only (time is 00:00) |
| `violation_code` | text | Code for the kind of violation | e.g. `CN061014` repair exterior wall, `EV1110` elevator maintenance |
| `violation_status` | text | `OPEN` (71,487), `COMPLIED` (19,137), `NO ENTRY` (114) | |
| `violation_status_date` | timestamp | When the status last changed | NULL in 78.9%: don't use for "time to fix" |
| `violation_description` | text | Short upper-case label | e.g. `REPAIR PORCH SYSTEM` |
| `violation_ordinance` | text | What the code requires, with the ordinance number in brackets | e.g. `... (13-196-410)` |
| `violation_inspector_comments` | text | Inspector's free-text notes | NULL in 6.3% |
| `inspection_number` | text | Inspection that found it; groups violations | |
| `inspection_status` | text | `FAILED` (75,883), `PASSED` (10,118), `CLOSED` (4,734), `HOLD` (3) | |
| `inspection_category` | text | `COMPLAINT` (62,916), `PERIODIC` (21,441), `PERMIT` (6,381) | Why the inspection happened |
| `department_bureau` | text | Inspecting bureau | CONSERVATION (63,115), ELEVATOR (12,456), PLUMBING, BOILER, SPECIAL INSPECTION PROGRAM, NEW CONSTRUCTION, ELECTRICAL, REFRIGERATION, VENTILATION, SPECIAL TASK FORCE, SIGNS, DEMOLITION, IRON |
| `address` | text | Building address, upper case | e.g. `6800 S DORCHESTER AVE` |
| `latitude`, `longitude` | double precision | Location | NULL in 0.1% |

### Violation traps

- **No `ward` or `community_area` column.** "Violations in ward 25" can't be answered from this table: say so. Don't join to 311 or permits by address to guess a ward.
- **A violation is a historical record, not the building's current condition.** `OPEN` means not yet marked complied in this data; it doesn't prove the problem still exists. Answers about a building should say "violations recorded since 2025" and give the dates.
- **Old ordinance numbers.** `violation_ordinance` uses the old Building Code numbering. **Heat violations cite `13-196-410`** ("Heat dwelling unit adequately from September 15th to June 1st"); no row cites the current `14X-8-802.2.2`. To *find* heat violations, filter `violation_ordinance LIKE '%(13-196-410)%'` (1,251 rows mention heat in the description). In the *answer*, cite the current rule, **14X-8-802.2.2**, and note the data uses the old number. (14X-8-803 is the cooling rule, not heat.)
- **Text columns are plain text** (not enums), stored in upper case: compare with `=` on exact upper-case values, or match words with `~* '\m…'`.
- **`violation_description` is cut off at 30 characters** (20,550 rows are exactly 30 long, e.g. `NOTIFY DOB,  USE OF VACANT LND`) and has double spaces and runs of `*`. Search `violation_ordinance` (the full requirement) or `violation_code` instead when you can.
- **210 different old ordinance numbers** are cited. Only one has been matched to the current code: heat, `13-196-410` → **14X-8-802.2.2**. The hot water rule (`13-196-430`, "minimum temperature of 120 degrees F", 263 rows) is **not** in the loaded code chapters. In answers, give the number the data cites and don't name a current section unless it's listed here.
- **No air conditioning:** 311 type `NAC` (1,032 rows) is the cooling complaint; the cooling rule is 14X-8-803.

### Examples

```sql
-- Heat violations by month
SELECT date_trunc('month', violation_date)::date AS month, count(*) AS violations
FROM building_violations
WHERE violation_ordinance LIKE '%(13-196-410)%'
GROUP BY 1 ORDER BY 1;

-- Open violations recorded at an address
SELECT violation_date::date, violation_code, violation_description, inspection_status
FROM building_violations
WHERE address = '6800 S DORCHESTER AVE' AND violation_status = 'OPEN'
ORDER BY violation_date DESC LIMIT 50;
```

---

## `building_permits`

Building permits issued by the Department of Buildings. **One row = one permit.** Source: [`ydr8-5enu`](https://data.cityofchicago.org/d/ydr8-5enu). The portal leaves out voided and revoked permits (2 rows still say REVOKED). **60,420 rows**, `issue_date` 2025-01-01 to 2026-11-17.

| Column | Type | Meaning | Values / notes |
| --- | --- | --- | --- |
| `id` | text | Row id, unique | |
| `permit_` | text | Permit number, unique. **Note the trailing underscore** | e.g. `B200411943` |
| `permit_type` | text | Kind of permit | 8 values, below. **Watch the dash** |
| `review_type` | text | How the plans were reviewed | 9 values, below |
| `permit_status` | text | ACTIVE (29,087), COMPLETE (18,120), SUSPENDED (5,989), PHASED PERMITTING (46), CANCELLED (9), REVOKED (2), EXPIRED (1) | NULL in 7,166 rows (12%) |
| `application_start_date` | timestamp | When the application started | |
| `issue_date` | timestamp | When the permit was issued | Indexed |
| `processing_time` | double precision | Days from application to issue | Median 6; 0 to 3,746 |
| `street_number`, `street_direction`, `street_name` | text | Address in three parts | e.g. `899`, `S`, `PLYMOUTH CT` |
| `work_description` | text | Free-text description of the work | Search with `ILIKE` |
| `reported_cost` | double precision | Cost reported by the applicant, dollars | NULL in 13.7%, 0 in 2.5%; median $15,507; max $730M |
| `total_fee` | double precision | Permit fees, dollars | |
| `community_area` | double precision | Community area number | Whole numbers stored as decimals. 6 rows have 0 (not a real area) |
| `ward` | double precision | Ward, 1 to 50 | Indexed. NULL in 0.8%. `ward = 25` works |
| `latitude`, `longitude` | double precision | Location | |

`permit_type`: `PERMIT – EXPRESS PERMIT PROGRAM` (38,772) · `PERMIT - RENOVATION/ALTERATION` (10,342) · `PERMIT - SIGNS` (4,251) · `PERMIT - NEW CONSTRUCTION` (2,885) · `PERMIT - ELEVATOR EQUIPMENT` (2,051) · `PERMIT - WRECKING/DEMOLITION` (1,280) · `PERMIT - REINSTATE REVOKED PMT` (835) · `PERMIT - EASY PERMIT PROCESS` (4)

`review_type`: EXPRESS PERMIT PROGRAM (38,772) · STANDARD PLAN REVIEW (6,865) · SELF CERT (5,772) · SIGN PERMIT (4,251) · CONVEYANCE DEVICE PERMIT (2,051) · DEMOLITION PERMIT (1,280) · EASY PERMIT (839) · DIRECT DEVELOPER SERVICES (577) · TRADITIONAL DEVELOPER SERVICES (13)

### Permit traps

- **The express permit type uses an en dash** (`–`), the others a hyphen (`-`). Copy the value exactly, or match it with `permit_type LIKE 'PERMIT _ EXPRESS%'`.
- **`reported_cost` is what the applicant reported**, not an audited cost, and is missing for 13.7% of permits. Say so when summing it; prefer the median for "typical cost".
- **Demolition** = `permit_type = 'PERMIT - WRECKING/DEMOLITION'`.

### Examples

```sql
-- New construction permits by ward, 2026
SELECT ward, count(*) AS permits FROM building_permits
WHERE permit_type = 'PERMIT - NEW CONSTRUCTION' AND issue_date >= '2026-01-01' AND ward IS NOT NULL
GROUP BY ward ORDER BY permits DESC LIMIT 5;
-- wards 42 and 27 (120 each), 32, 4, 28

-- How long does each kind of review take? (median days)
SELECT review_type, count(*) AS permits,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY processing_time) AS median_days
FROM building_permits GROUP BY review_type ORDER BY median_days DESC;
-- standard plan review 83 days, express 3
```

---

## Not in these tables

Refuse, and say what's missing:

- Anything before 2025-01-01.
- 311 information-only calls and aircraft noise complaints (not loaded). **No other 311 type is about noise**, so refuse noise questions.
- Anything after the end of the data (2026-11-18 for 311, 2026-11-17 for the others).
- Violations by ward or community area (no such column).
- Community area or ward **names** and boundaries, population, per-capita rates (no reference tables yet).
- Whether a building's problem is fixed *now* (violations are records of inspections).
- What the law says: that's the Municipal Code documents (RAG), not SQL. Budget figures: the 2027 budget document, which is **proposed, not adopted**.
