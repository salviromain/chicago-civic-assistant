"""Builds evals/questions.jsonl: the eval set, with every expected answer computed, not typed.

    .venv/bin/python -m evals.build_questions          # run every reference SQL, check every chunk, write the file
    .venv/bin/python -m evals.build_questions --check  # same, but only report differences with the file

- Table questions: the reference SQL runs as civic_reader; its result fills the
  reference answer and the words the answer must contain.
- Document questions: every expected chunk must exist, and `phrase` (the fact the
  answer depends on) must appear in one of them, so a chunk id can't silently be wrong.
- Unanswerable questions: expected route and answerable=false.

None of these questions were used while building the prompts (scripts/try_sql.py
and scripts/try_answer.py hold those), except q001-q004, which were in the file
before Day 8 and are tagged "seen-in-tuning". Today's date for every question is AS_OF.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

AS_OF = "2026-11-25"
OUT = Path(__file__).parent / "questions.jsonl"

NOT_DUP = "NOT duplicate"
Y2025 = "created_date >= '2025-01-01' AND created_date < '2026-01-01'"
Y2026 = "created_date >= '2026-01-01' AND created_date < '2027-01-01'"
HEAT = "violation_ordinance LIKE '%(13-196-410)%'"


# --- how numbers may appear in an answer ------------------------------------

def num(v) -> list[str]:
    return [f"{v:,}", str(v)]


def dec(v, places=1) -> list[str]:
    """0.4934 -> '0.5'; 83.0 -> '83'"""
    out = {f"{v:.{places}f}", f"{round(v)}"} if abs(v) >= 1 else {f"{v:.{places}f}", f"{v:.2f}"}
    return sorted(out)


def money(v) -> list[str]:
    v = float(v)
    out = {f"{v:,.0f}"}
    if v >= 1e9:
        out |= {f"{v / 1e9:.1f} billion", f"{v / 1e9:.2f} billion"}
    if v >= 1e6:
        out.add(f"{v / 1e6:.1f} million")
    if v >= 1e8:  # "171 million" is close enough for $171,058,072; "10 million" isn't for $9.5M
        out.add(f"{v / 1e6:,.0f} million")
    return sorted(out)


# --- the questions -------------------------------------------------------------
# sql:    reference SQL (its first row is r[0], first value r[0][0])
# answer: reference answer, a function of the rows
# must:   groups of strings; the answer must contain one string of each group
# chunks: relevant chunk ids (recall@k); phrase: must appear in one of them

Q: list[dict] = [
    # ---- before Day 8 (kept) ----
    dict(id="q001", q="How many no-heat complaints were filed in Ward 25 between November 2025 and February 2026, excluding duplicates?",
         route="sql", answerable=False, tags=["trap:no-heat-type", "trap:no-ward-in-violations", "seen-in-tuning"],
         answer="Can't be answered: 311 has no heat complaint type, and heat violations have no ward column."),
    dict(id="q002", q="What minimum indoor temperature does the city code require landlords to maintain during the day?",
         route="docs", tags=["seen-in-tuning"], chunks=["14X-8-802.2.2"], phrase="68°F (20°C) at 8:30 a.m.",
         answer="68°F (20°C) from 8:30 a.m. to 10:30 p.m., September 15 to June 1 (Section 14X-8-802.2.2).",
         must=[["68"]]),
    dict(id="q003", q="How many 311 complaints will Ward 25 get next winter?", route="sql", answerable=False,
         tags=["trap:forecast", "seen-in-tuning"], answer="Can't be answered: the tables record the past, not forecasts."),
    dict(id="q004", q="Which code section sets the minimum heat landlords must provide?", route="docs",
         tags=["seen-in-tuning"], chunks=["14X-8-802.2.2"], phrase="Heat to be provided", answer="Section 14X-8-802.2.2.",
         must=[["14X-8-802.2.2"]]),

    # ---- tables: 311 ----
    dict(id="q005", q="How many graffiti removal requests were made in ward 12 in 2025?", route="sql",
         sql=f"SELECT count(*) FROM service_requests_311 WHERE sr_short_code = 'GRAF' AND ward = 12 AND {NOT_DUP} AND {Y2025}",
         answer=lambda r: f"{r[0][0]:,} graffiti removal requests (duplicates excluded).", must=lambda r: [num(r[0][0])]),
    dict(id="q006", q="Which city department handled the most 311 requests in 2025?", route="sql",
         sql=f"SELECT owner_department::text, count(*) FROM service_requests_311 WHERE {NOT_DUP} AND {Y2025} GROUP BY 1 ORDER BY 2 DESC LIMIT 3",
         answer=lambda r: f"{r[0][0]}, with {r[0][1]:,} requests.", must=lambda r: [["Streets and Sanitation"]]),
    dict(id="q007", q="How many abandoned vehicle complaints were made in 2026?", route="sql",
         sql=f"SELECT count(*) FROM service_requests_311 WHERE sr_short_code = 'SKA' AND {NOT_DUP} AND {Y2026}",
         answer=lambda r: f"{r[0][0]:,} (2026 to date; the data ends 2026-11-18).", must=lambda r: [num(r[0][0])]),
    dict(id="q008", q="What share of pothole reports in 2025 were marked as duplicates?", route="sql", tags=["trap:duplicates"],
         sql=f"SELECT round(100.0 * count(*) FILTER (WHERE duplicate) / count(*), 1) FROM service_requests_311 WHERE sr_short_code = 'PHF' AND {Y2025}",
         answer=lambda r: f"About {r[0][0]}% of 2025 pothole reports were duplicates.", must=lambda r: [dec(float(r[0][0]))]),
    dict(id="q009", q="Which community area had the most rat complaints in 2025?", route="sql",
         sql=f"SELECT community_area, count(*) FROM service_requests_311 WHERE sr_short_code = 'SGA' AND {NOT_DUP} AND {Y2025} AND community_area IS NOT NULL GROUP BY 1 ORDER BY 2 DESC LIMIT 3",
         answer=lambda r: f"Community area {r[0][0]} ({r[0][1]:,} complaints). The data has area numbers only, no names.",
         must=lambda r: [[str(r[0][0])]]),
    dict(id="q010", q="How many 311 requests are still open?", route="sql",
         sql=f"SELECT count(*) FROM service_requests_311 WHERE status = 'Open' AND {NOT_DUP}",
         answer=lambda r: f"{r[0][0]:,} open requests (duplicates excluded), as of the data's end on 2026-11-18.",
         must=lambda r: [num(r[0][0])]),
    dict(id="q011", q="What was the median time to close a pothole complaint in 2025, in days?", route="sql",
         sql=f"SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM closed_date - created_date) / 86400) FROM service_requests_311 WHERE sr_short_code = 'PHF' AND status = 'Completed' AND {NOT_DUP} AND {Y2025}",
         answer=lambda r: f"About {r[0][0]:.1f} days (completed, duplicates excluded).", must=lambda r: [dec(r[0][0])]),
    dict(id="q012", q="In which month of 2025 were the most pothole complaints made?", route="sql",
         sql=f"SELECT to_char(date_trunc('month', created_date), 'FMMonth'), count(*) FROM service_requests_311 WHERE sr_short_code = 'PHF' AND {NOT_DUP} AND {Y2025} GROUP BY 1 ORDER BY 2 DESC LIMIT 3",
         answer=lambda r: f"{r[0][0]} 2025, with {r[0][1]:,} complaints.", must=lambda r: [[r[0][0]]]),
    dict(id="q013", q="How many dead animal pick-up requests were there in ward 10 in 2026?", route="sql",
         sql=f"SELECT count(*) FROM service_requests_311 WHERE sr_short_code = 'SGQ' AND ward = 10 AND {NOT_DUP} AND {Y2026}",
         answer=lambda r: f"{r[0][0]:,}.", must=lambda r: [num(r[0][0])]),
    dict(id="q014", q="How many open fire hydrant complaints were made in July 2025?", route="sql",
         sql=f"SELECT count(*) FROM service_requests_311 WHERE sr_short_code = 'WBT' AND {NOT_DUP} AND created_date >= '2025-07-01' AND created_date < '2025-08-01'",
         answer=lambda r: f"{r[0][0]:,} (duplicates excluded).", must=lambda r: [num(r[0][0])]),
    dict(id="q015", q="How many sewer cave-in inspection requests were made in 2025?", route="sql",
         sql=f"SELECT count(*) FROM service_requests_311 WHERE sr_short_code = 'AAD' AND {NOT_DUP} AND {Y2025}",
         answer=lambda r: f"{r[0][0]:,}.", must=lambda r: [num(r[0][0])]),
    dict(id="q016", q="How many tree emergency requests were made in 2026?", route="sql",
         sql=f"SELECT count(*) FROM service_requests_311 WHERE sr_short_code = 'SEC' AND {NOT_DUP} AND {Y2026}",
         answer=lambda r: f"{r[0][0]:,}.", must=lambda r: [num(r[0][0])]),
    dict(id="q017", q="How many restaurant complaints did residents file in 2025?", route="sql", tags=["trap:city-generated"],
         sql=f"SELECT count(*) FROM service_requests_311 WHERE sr_short_code = 'HFB' AND {NOT_DUP} AND origin NOT IN ('Generated In House', 'Mass Entry') AND {Y2025}",
         answer=lambda r: f"{r[0][0]:,} (city-generated requests and duplicates excluded).", must=lambda r: [num(r[0][0])]),
    dict(id="q018", q="How many vicious animal complaints were made in 2026?", route="sql",
         sql=f"SELECT count(*) FROM service_requests_311 WHERE sr_short_code = 'EAF' AND {NOT_DUP} AND {Y2026}",
         answer=lambda r: f"{r[0][0]:,}.", must=lambda r: [num(r[0][0])]),
    dict(id="q035", q="How many 311 requests were made in October 2026?", route="sql",
         sql=f"SELECT count(*) FROM service_requests_311 WHERE {NOT_DUP} AND created_date >= '2026-10-01' AND created_date < '2026-11-01'",
         answer=lambda r: f"{r[0][0]:,} (duplicates excluded).", must=lambda r: [num(r[0][0])]),
    dict(id="q036", q="How many no water complaints were there in 2026?", route="sql",
         sql=f"SELECT count(*) FROM service_requests_311 WHERE sr_short_code = 'WBJ' AND {NOT_DUP} AND {Y2026}",
         answer=lambda r: f"{r[0][0]:,}.", must=lambda r: [num(r[0][0])]),
    dict(id="q037", q="What was the average number of days to close street light out complaints in 2025?", route="sql",
         sql=f"SELECT avg(extract(epoch FROM closed_date - created_date) / 86400) FROM service_requests_311 WHERE sr_short_code = 'SFD' AND status = 'Completed' AND {NOT_DUP} AND {Y2025}",
         answer=lambda r: f"About {float(r[0][0]):.1f} days on average (completed, duplicates excluded).",
         must=lambda r: [dec(float(r[0][0]))]),

    # ---- tables: violations ----
    dict(id="q019", q="How many building violations were recorded in 2025?", route="sql",
         sql="SELECT count(*) FROM building_violations WHERE violation_date >= '2025-01-01' AND violation_date < '2026-01-01'",
         answer=lambda r: f"{r[0][0]:,} violations.", must=lambda r: [num(r[0][0])]),
    dict(id="q020", q="How many building violations are still marked open?", route="sql", tags=["trap:records-not-current"],
         sql="SELECT count(*) FROM building_violations WHERE violation_status = 'OPEN'",
         answer=lambda r: f"{r[0][0]:,} are marked OPEN (not yet recorded as complied; that doesn't prove the problem still exists).",
         must=lambda r: [num(r[0][0])]),
    dict(id="q021", q="Which address had the most heat violations recorded since 2025?", route="sql", tags=["trap:heat-ordinance", "tie"],
         sql=f"SELECT address, count(*) FROM building_violations WHERE {HEAT} GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT 3",
         answer=lambda r: f"{r[0][0]} and {r[1][0]} tie with {r[0][1]} heat violations each.",
         must=lambda r: [[r[0][0], r[1][0], "501 E 32nd", "5110 S Dr Martin"]]),
    dict(id="q022", q="How many violations did the elevator bureau record in 2026?", route="sql",
         sql="SELECT count(*) FROM building_violations WHERE department_bureau = 'ELEVATOR' AND violation_date >= '2026-01-01' AND violation_date < '2027-01-01'",
         answer=lambda r: f"{r[0][0]:,}.", must=lambda r: [num(r[0][0])]),
    dict(id="q023", q="What share of building inspections in 2025 failed?", route="sql", tags=["trap:rows-vs-inspections"],
         sql="SELECT round(100.0 * count(DISTINCT inspection_number) FILTER (WHERE inspection_status = 'FAILED') / count(DISTINCT inspection_number), 1) FROM building_violations WHERE violation_date >= '2025-01-01' AND violation_date < '2026-01-01'",
         answer=lambda r: f"About {r[0][0]}% of inspections (counted once each, not once per violation) failed.",
         must=lambda r: [dec(float(r[0][0]))]),
    dict(id="q024", q="How many violations came from inspections triggered by complaints in 2026?", route="sql",
         sql="SELECT count(*) FROM building_violations WHERE inspection_category = 'COMPLAINT' AND violation_date >= '2026-01-01' AND violation_date < '2027-01-01'",
         answer=lambda r: f"{r[0][0]:,}.", must=lambda r: [num(r[0][0])]),
    dict(id="q025", q="How many violations did the conservation bureau record in 2025?", route="sql",
         sql="SELECT count(*) FROM building_violations WHERE department_bureau = 'CONSERVATION' AND violation_date >= '2025-01-01' AND violation_date < '2026-01-01'",
         answer=lambda r: f"{r[0][0]:,}.", must=lambda r: [num(r[0][0])]),

    # ---- tables: permits ----
    dict(id="q026", q="How many building permits were issued in 2025?", route="sql",
         sql="SELECT count(*) FROM building_permits WHERE issue_date >= '2025-01-01' AND issue_date < '2026-01-01'",
         answer=lambda r: f"{r[0][0]:,} permits.", must=lambda r: [num(r[0][0])]),
    dict(id="q027", q="How many demolition permits were issued in 2026?", route="sql",
         sql="SELECT count(*) FROM building_permits WHERE permit_type = 'PERMIT - WRECKING/DEMOLITION' AND issue_date >= '2026-01-01' AND issue_date < '2027-01-01'",
         answer=lambda r: f"{r[0][0]:,}.", must=lambda r: [num(r[0][0])]),
    dict(id="q028", q="What was the total reported cost of new construction permits issued in 2025?", route="sql", tags=["trap:reported-cost"],
         sql="SELECT sum(reported_cost), count(*), count(reported_cost) FROM building_permits WHERE permit_type = 'PERMIT - NEW CONSTRUCTION' AND issue_date >= '2025-01-01' AND issue_date < '2026-01-01'",
         answer=lambda r: f"${r[0][0]:,.0f} as reported by applicants ({r[0][2]:,} of {r[0][1]:,} permits report a cost).",
         must=lambda r: [money(r[0][0])]),
    dict(id="q029", q="Which ward had the most demolition permits in 2025?", route="sql",
         sql="SELECT ward::int, count(*) FROM building_permits WHERE permit_type = 'PERMIT - WRECKING/DEMOLITION' AND issue_date >= '2025-01-01' AND issue_date < '2026-01-01' AND ward IS NOT NULL GROUP BY 1 ORDER BY 2 DESC LIMIT 3",
         answer=lambda r: f"Ward {r[0][0]}, with {r[0][1]} demolition permits.", must=lambda r: [[str(r[0][0])]]),
    dict(id="q030", q="What is the median processing time for express permits?", route="sql", tags=["trap:en-dash"],
         sql="SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY processing_time) FROM building_permits WHERE permit_type = 'PERMIT – EXPRESS PERMIT PROGRAM'",
         answer=lambda r: f"{r[0][0]:g} days.", must=lambda r: [dec(r[0][0])]),
    dict(id="q031", q="How many sign permits were issued in ward 42 in 2026?", route="sql",
         sql="SELECT count(*) FROM building_permits WHERE permit_type = 'PERMIT - SIGNS' AND ward = 42 AND issue_date >= '2026-01-01' AND issue_date < '2027-01-01'",
         answer=lambda r: f"{r[0][0]:,}.", must=lambda r: [num(r[0][0])]),
    dict(id="q032", q="How many permits issued in 2026 mention a garage in their work description?", route="sql", tags=["trap:free-text"],
         sql=r"SELECT count(*) FROM building_permits WHERE work_description ~* '\mgarage' AND issue_date >= '2026-01-01' AND issue_date < '2027-01-01'",
         answer=lambda r: f"{r[0][0]:,}.", must=lambda r: [num(r[0][0])]),
    dict(id="q033", q="How much did the city collect in building permit fees in 2025?", route="sql",
         sql="SELECT sum(total_fee) FROM building_permits WHERE issue_date >= '2025-01-01' AND issue_date < '2026-01-01'",
         answer=lambda r: f"${r[0][0]:,.0f} in permit fees.", must=lambda r: [money(r[0][0])]),
    dict(id="q034", q="How many building permits are currently suspended?", route="sql",
         sql="SELECT count(*) FROM building_permits WHERE permit_status = 'SUSPENDED'",
         answer=lambda r: f"{r[0][0]:,} have status SUSPENDED in the data.", must=lambda r: [num(r[0][0])]),

    # ---- documents: Municipal Code ----
    dict(id="q038", q="How much notice must my landlord give before entering my apartment?", route="docs",
         chunks=["5-12-050"], phrase="no less than two days", answer="At least two days' notice, except in emergencies (5-12-050).",
         must=[["two days", "2 days", "48 hours"]]),
    dict(id="q039", q="How long does my landlord have to return my security deposit after I move out?", route="docs",
         chunks=["5-12-080#2"], phrase="within 45 days after the date that the tenant vacates",
         answer="Within 45 days after the tenant moves out (5-12-080).", must=[["45"]]),
    dict(id="q040", q="Where must a landlord keep a tenant's security deposit?", route="docs",
         chunks=["5-12-080#1"], phrase="federally insured interest- bearing account",
         answer="In a federally insured, interest-bearing account at a bank or other financial institution in Illinois (5-12-080).",
         must=[["federally insured"], ["Illinois"]]),
    dict(id="q041", q="What is the maximum late fee a landlord can charge for rent?", route="docs",
         chunks=["5-12-140"], phrase="$10.00 per month for the first $500.00",
         answer="$10 a month for the first $500 of rent plus 5% of any rent above $500 (5-12-140).", must=[["10"], ["5%", "five percent"]]),
    dict(id="q042", q="If my landlord doesn't fix a minor defect, can I fix it myself and take the cost out of my rent?", route="docs",
         chunks=["5-12-110#2"], phrase="greater of $500.00 or one-half of the monthly rent",
         answer="Yes, after 14 days' written notice, if the cost is no more than $500 or half a month's rent, whichever is greater (5-12-110(c)).",
         must=[["500"], ["14"]]),
    dict(id="q043", q="What can I do if my landlord locks me out or shuts off my utilities?", route="docs",
         chunks=["5-12-160"], phrase="two months' rent or twice the actual damages",
         answer="It's prohibited (5-12-160): the landlord can be fined $200 to $500 a day, and the tenant can recover possession and up to two months' rent or twice the actual damages.",
         must=[["two months", "2 months"]]),
    dict(id="q044", q="Does the landlord-tenant ordinance cover an apartment in a six-unit building where the owner also lives?", route="docs",
         chunks=["5-12-020"], phrase="owner-occupied premises containing six units or fewer",
         answer="Mostly no: owner-occupied buildings with six or fewer units are excluded (5-12-020(a)), though 5-12-130(j) and 5-12-160 still apply.",
         must=[["owner-occupied", "owner occupied", "excluded", "not cover", "does not"]]),
    dict(id="q045", q="What must a landlord tell me about heating costs before I sign a lease?", route="docs",
         chunks=["5-16-010"], phrase="annual cost of service from the utility",
         answer="If heat is individually metered and paid by the tenant: that the tenant pays for heat, and the annual heating cost over the previous 12 months (5-16-010).",
         must=[["12 months", "twelve months", "annual", "previous year"]]),
    dict(id="q046", q="What is the minimum temperature a landlord must keep an apartment at overnight?", route="docs",
         chunks=["14X-8-802.2.2"], phrase="66°F (19°C) at 10:30 p.m.", answer="66°F (19°C) from 10:30 p.m. to 8:30 a.m. (14X-8-802.2.2).",
         must=[["66"]]),
    dict(id="q047", q="What temperature must cooling equipment maintain in residential buildings with more than 100 units?", route="docs",
         chunks=["14X-8-803.4"], phrase="more than 100 dwelling units",
         answer="75°F (24°C) and 50% humidity in at least one indoor common gathering space (14X-8-803.4).", must=[["75"]]),
    dict(id="q048", q="Which kinds of buildings are required to have cooling equipment?", route="docs",
         chunks=["14X-8-803.1", "14X-8-803.2", "14X-8-803.3", "14X-8-803.4"], phrase="Nursing homes must be provided",
         answer="Nursing homes, housing for older persons, and residential buildings with more than 100 units or that are high-rises (14X-8-803.2 to 803.4).",
         must=[["nursing"], ["older"]]),
    dict(id="q049", q="What minimum temperature must workplaces be heated to?", route="docs",
         chunks=["14X-8-802.3.2", "14X-8-802.3"], phrase="Indoor occupiable work spaces must be supplied with heat",
         answer="68°F (20°C) while the space is occupied, September 15 to June 1 (14X-8-802.3.2).", must=[["68"]]),
    dict(id="q050", q="Can my lease require me to pay my landlord's attorney fees if we go to court?", route="docs",
         chunks=["5-12-140"], phrase="tenant will pay the landlord's attorney's fees",
         answer="No: a lease clause making the tenant pay the landlord's attorney's fees is prohibited and unenforceable (5-12-140(f)), except as court rules, statute or ordinance provide.",
         must=[["prohibit", "not allowed", "unenforceable", "cannot", "can't", "may not"]]),
    dict(id="q051", q="What can I do if my apartment is damaged by a fire?", route="docs",
         chunks=["5-12-110#4"], phrase="the rental agreement terminates as of the date of the fire",
         answer="If the unit is substantially damaged, the tenant may move out and notify the landlord in writing within 14 days to end the lease (5-12-110(g)).",
         must=[["14"]]),
    dict(id="q052", q="Does my landlord have to tell me if the building is in foreclosure?", route="docs",
         chunks=["5-12-095"], phrase="Within seven (7) days of being served a foreclosure complaint",
         answer="Yes: within 7 days of being served a foreclosure complaint, in writing (5-12-095).", must=[["7", "seven"]]),
    dict(id="q053", q="What does a landlord have to give tenants about bed bugs?", route="docs",
         chunks=["5-12-101"], phrase="informational brochure on bed bug prevention",
         answer="The health department's brochure on bed bug prevention and treatment, before signing or renewing (5-12-101).",
         must=[["brochure"]]),
    dict(id="q054", q="Can I sublet my apartment?", route="docs",
         chunks=["5-12-120"], phrase="shall accept a reasonable sublease",
         answer="The landlord must accept a reasonable sublease proposed by the tenant, without extra fees (5-12-120).",
         must=[["reasonable"]]),
    dict(id="q055", q="What does a landlord have to disclose about code violations before I rent?", route="docs",
         chunks=["5-12-100"], phrase="during the previous 12 months",
         answer="Code violations cited by the city in the previous 12 months, and pending code enforcement cases (5-12-100).",
         must=[["12 months", "twelve months", "past year", "previous year"]]),
    dict(id="q056", q="How much notice must a landlord give before not renewing the lease of a tenant who has lived there for more than three years?", route="docs",
         chunks=["5-12-130#4"], phrase="at least 120 days prior to the stated termination date",
         answer="At least 120 days' written notice (5-12-130(j)).", must=[["120"]]),
    dict(id="q057", q="How many days does a tenant have to pay overdue rent after the landlord's written notice before the lease can be ended?", route="docs",
         chunks=["5-12-130#1"], phrase="within five days after written notice",
         answer="Five days (5-12-130(a)).", must=[["five", "5 days"]]),
    dict(id="q058", q="Does my landlord have to tell me who owns the building?", route="docs",
         chunks=["5-12-090"], phrase="name, address, and telephone number",
         answer="Yes: in writing, the name, address and phone number of the owner or manager, and of the agent for notices (5-12-090).",
         must=[["name"], ["address"]]),
    dict(id="q059", q="What are a tenant's responsibilities under the landlord-tenant ordinance?", route="docs",
         chunks=["5-12-040"], phrase="Dispose of all ashes, rubbish, garbage",
         answer="Keep their part of the premises safe, dispose of garbage properly, keep plumbing clean, use facilities reasonably, not damage the premises, and not disturb neighbors (5-12-040).",
         must=[["garbage", "rubbish", "waste"]]),
    dict(id="q060", q="Can I keep a hot plate in a rooming house unit?", route="docs",
         chunks=["14X-8-804.8"], phrase="cooking is not allowed in any rooming unit",
         answer="No, unless the certificate of occupancy allows it or the fire code official approves; coffee pots and microwaves don't count (14X-8-804.8).",
         must=[["not allowed", "no,", "not permitted", "prohibit", "cannot", "can't", "may not"]]),
    dict(id="q061", q="What has to be done with abandoned gas piping in a building?", route="docs",
         chunks=["14X-8-806.2"], phrase="must be removed",
         answer="Remove it where it can be reached without damage; piping left in place must have its ends clearly marked (14X-8-806.2).",
         must=[["remov"]]),
    dict(id="q069", q="What does section 14X-8-803.7 require?", route="docs",
         chunks=["14X-8-803.7"], phrase="maintained in a safe working condition",
         answer="Cooling and dehumidification equipment, where provided, must be properly installed and maintained in safe working condition (14X-8-803.7).",
         must=[["cooling"], ["maint"]]),

    # ---- documents: 2027 budget (proposed) ----
    dict(id="q062", q="How much does the 2027 budget propose for the Chicago Police Department?", route="docs", tags=["trap:proposed"],
         chunks=["budget-2027-p120-1"], phrase="Chicago Police Department | 2,121,127,600 | 2,243,691,824",
         answer="$2,243,691,824 (proposed, 2027).", must=[money(2243691824), ["propos"]]),
    dict(id="q063", q="What is the proposed 2027 budget for the Chicago Fire Department?", route="docs", tags=["trap:proposed"],
         chunks=["budget-2027-p120-1"], phrase="Chicago Fire Department | 907,646,972 | 914,383,396",
         answer="$914,383,396 (proposed).", must=[money(914383396), ["propos"]]),
    dict(id="q064", q="How much does the proposed 2027 budget give the Department of Streets and Sanitation?", route="docs", tags=["trap:proposed"],
         chunks=["budget-2027-p097-1"], phrase="Dept Total | 354,888,561 | 381,913,905",
         answer="$381,913,905 (proposed).", must=[money(381913905), ["propos"]]),
    dict(id="q065", q="How big was the forecasted budget gap for 2027?", route="docs",
         chunks=["budget-2027-p038-1"], phrase="$882.4 MILLION FORECASTED BUDGET GAP",
         answer="$882.4 million, closed in the proposed budget.", must=[["882.4"]]),
    dict(id="q066", q="What base property tax levy does the 2027 budget propose?", route="docs", tags=["trap:proposed"],
         chunks=["budget-2027-p064-1"], phrase="base property tax levy—before accounting for loss in collections—at $1.87 billion",
         answer="$1.87 billion, with no increase to the base levy (proposed).", must=[["1.87"]]),
    dict(id="q067", q="What does the 2027 budget say about police overtime?", route="docs",
         chunks=["budget-2027-p017-1"], phrase="Executive Order 2025-11, capping police overtime",
         answer="The mayor signed Executive Order 2025-11 in December 2025, capping police overtime; CPD reports monthly and joins quarterly City Council hearings. The budget also plans civilian hires (e.g. over 40 Detention Aides) to cut overtime.",
         # Widened after the baseline: the budget also ties civilian hiring to overtime (p. 125)
         must=[["2025-11", "executive order", "Detention Aides", "monthly reports"]]),
    dict(id="q068", q="What is the proposed 2027 budget for the Chicago Department of Public Health?", route="docs", tags=["trap:proposed"],
         chunks=["budget-2027-p138-1"], phrase="Chicago Department of Public Health | 347,937,660 | 333,468,767",
         answer="$333,468,767 (proposed), down from $347,937,660 in 2026.", must=[money(333468767), ["propos"]]),

    # ---- both ----
    dict(id="q070", q="How many heat violations were recorded in January 2026, and from what date each year must landlords supply heat?", route="both",
         sql=f"SELECT count(*) FROM building_violations WHERE {HEAT} AND violation_date >= '2026-01-01' AND violation_date < '2026-02-01'",
         chunks=["14X-8-802.2.2"], phrase="September 15th of each year",
         answer=lambda r: f"{r[0][0]:,} heat violations in January 2026; heat must be supplied from September 15 to June 1 (14X-8-802.2.2).",
         must=lambda r: [num(r[0][0]), ["September 15"]]),
    dict(id="q071", q="How many no air conditioning complaints were made from June through August 2026, and at what heat index must cooling equipment be run?", route="both",
         sql=f"SELECT count(*) FROM service_requests_311 WHERE sr_short_code = 'NAC' AND {NOT_DUP} AND created_date >= '2026-06-01' AND created_date < '2026-09-01'",
         chunks=["14X-8-803.6"], phrase="heat index exceeds 80°F",
         answer=lambda r: f"{r[0][0]:,} complaints; cooling must run when the heat index exceeds 80°F (14X-8-803.6).",
         must=lambda r: [num(r[0][0]), ["80"]]),
    dict(id="q072", q="How many rat complaints were made in ward 1 in 2025, and what can a tenant do if the landlord doesn't exterminate rodents?", route="both",
         sql=f"SELECT count(*) FROM service_requests_311 WHERE sr_short_code = 'SGA' AND ward = 1 AND {NOT_DUP} AND {Y2025}",
         chunks=["5-12-110#1", "5-12-110#2"], phrase="Failure to exterminate insects, rodents",
         answer=lambda r: f"{r[0][0]:,} rat complaints; failing to exterminate rodents is a material noncompliance, giving the tenant remedies under 5-12-110 (e.g. ending the lease after 14 days' notice).",
         must=lambda r: [num(r[0][0]), ["5-12-110"]]),
    dict(id="q073", q="How many heat violations recorded since 2025 are still marked open, and what can a tenant do when the landlord fails to supply heat?", route="both",
         sql=f"SELECT count(*) FROM building_violations WHERE {HEAT} AND violation_status = 'OPEN'",
         chunks=["5-12-110#3"], phrase="fails to supply heat, running water",
         answer=lambda r: f"{r[0][0]:,} are marked open; after written notice the tenant may buy heat and deduct the cost from rent, recover damages, or get substitute housing (5-12-110(f)).",
         must=lambda r: [num(r[0][0]), ["deduct", "damages", "substitute"]]),
    dict(id="q074", q="How many 311 requests did the Department of Housing handle in 2025, and how much does the 2027 budget propose for that department?", route="both",
         sql=f"SELECT count(*) FROM service_requests_311 WHERE owner_department = 'Department of Housing' AND {NOT_DUP} AND {Y2025}",
         chunks=["budget-2027-p152-1"], phrase="Department of Housing | 177,012,026 | 171,058,072",
         answer=lambda r: f"{r[0][0]:,} requests in 2025; the proposed 2027 budget is $171,058,072.",
         must=lambda r: [num(r[0][0]), money(171058072)]),
    dict(id="q075", q="How many water in basement complaints were made in 2026, and what is the proposed 2027 budget for the Department of Water Management?", route="both",
         sql=f"SELECT count(*) FROM service_requests_311 WHERE sr_short_code = 'AAF' AND {NOT_DUP} AND {Y2026}",
         chunks=["budget-2027-p097-1"], phrase="Dept Total | 778,101,058 | 783,350,165",
         answer=lambda r: f"{r[0][0]:,} complaints in 2026 (to 2026-11-18); the proposed budget is $783,350,165.",
         must=lambda r: [num(r[0][0]), money(783350165)]),
    dict(id="q076", q="How many requests did the Chicago Department of Transportation handle in 2026, and what is its proposed 2027 budget?", route="both",
         sql=f"SELECT count(*) FROM service_requests_311 WHERE owner_department = 'CDOT - Department of Transportation' AND {NOT_DUP} AND {Y2026}",
         chunks=["budget-2027-p097-1"], phrase="Dept Total | 1,727,847,563 | 1,997,393,291",
         answer=lambda r: f"{r[0][0]:,} requests; the proposed budget is $1,997,393,291.",
         must=lambda r: [num(r[0][0]), money(1997393291)]),
    dict(id="q077", q="How many heat violations were recorded in December 2025, and what minimum nighttime temperature does the code require?", route="both",
         sql=f"SELECT count(*) FROM building_violations WHERE {HEAT} AND violation_date >= '2025-12-01' AND violation_date < '2026-01-01'",
         chunks=["14X-8-802.2.2"], phrase="66°F (19°C) at 10:30 p.m.",
         answer=lambda r: f"{r[0][0]:,} heat violations; at night (10:30 p.m. to 8:30 a.m.) the minimum is 66°F (14X-8-802.2.2).",
         must=lambda r: [num(r[0][0]), ["66"]]),
    dict(id="q078", q="How many requests did Animal Care and Control handle in 2025, and how much does the proposed 2027 budget give Chicago Animal Care and Control?", route="both",
         sql=f"SELECT count(*) FROM service_requests_311 WHERE owner_department = 'Animal Care and Control' AND {NOT_DUP} AND {Y2025}",
         chunks=["budget-2027-p162-1"], phrase="Chicago Animal Care and Control | 8,177,388 | 9,530,803",
         answer=lambda r: f"{r[0][0]:,} requests; the proposed budget is $9,530,803.",
         must=lambda r: [num(r[0][0]), money(9530803)]),
    dict(id="q079", q="How many restaurant complaints were made in 2026, and what does the 2027 budget propose for the Chicago Department of Public Health?", route="both",
         sql=f"SELECT count(*) FROM service_requests_311 WHERE sr_short_code = 'HFB' AND {NOT_DUP} AND {Y2026}",
         chunks=["budget-2027-p138-1"], phrase="Chicago Department of Public Health | 347,937,660 | 333,468,767",
         answer=lambda r: f"{r[0][0]:,} restaurant complaints; the proposed budget is $333,468,767.",
         must=lambda r: [num(r[0][0]), money(333468767)]),

    # ---- unanswerable ----
    dict(id="q080", q="How many 311 information-only calls were made in 2026?", route="sql", answerable=False, tags=["trap:not-loaded"],
         answer="Can't be answered: information-only calls weren't loaded."),
    dict(id="q081", q="How many building violations were recorded in community area 25?", route="sql", answerable=False, tags=["trap:no-ward-in-violations"],
         answer="Can't be answered: building violations have no community area column."),
    dict(id="q082", q="How many building permits were issued in 2022?", route="sql", answerable=False, tags=["trap:before-data"],
         answer="Can't be answered: the data starts on 2025-01-01."),
    dict(id="q083", q="What are the city's rules for renting out my apartment on Airbnb?", route="docs", answerable=False,
         answer="Not covered by the loaded documents (Municipal Code 14X-8, 5-12, 5-16 and the 2027 budget)."),
    dict(id="q084", q="What minimum hot water temperature must landlords provide?", route="docs", answerable=False, tags=["trap:not-in-chapters"],
         answer="Not in the loaded chapters: 5-12-110 refers to hot water 'as required by the municipal code', but the temperature rule (old 13-196-430, 120°F) isn't loaded."),
    dict(id="q085", q="How many people live in ward 25?", route="sql", answerable=False, tags=["trap:no-population"],
         answer="Can't be answered: the tables have no population data."),
    dict(id="q086", q="Will rat complaints go up next year?", route="sql", answerable=False, tags=["trap:forecast"],
         answer="Can't be answered: the tables record the past, not forecasts."),
    dict(id="q087", q="How many noise complaints were made in ward 44 in 2025?", route="sql", answerable=False, tags=["trap:not-loaded"],
         answer="Can't be answered: the only noise type (aircraft noise) wasn't loaded."),
]


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def build(conn_rows, conn_chunks) -> list[dict]:
    """Questions -> JSON records. conn_rows(sql) -> (columns, rows); conn_chunks(ids) -> {id: text}."""
    records, problems = [], []
    seen = set()
    for d in Q:
        qid = d["id"]
        if qid in seen:
            problems.append(f"{qid}: duplicate id")
        seen.add(qid)
        answerable = d.get("answerable", True)
        rows = columns = None
        if d.get("sql"):
            columns, rows = conn_rows(d["sql"])
            if not rows or rows[0][0] is None:
                problems.append(f"{qid}: reference SQL returned nothing")
                continue
        answer = d["answer"](rows) if callable(d["answer"]) else d["answer"]
        must = d.get("must", [])
        must = must(rows) if callable(must) else must
        chunks = d.get("chunks", [])
        if chunks:
            texts = conn_chunks(chunks)
            missing = [c for c in chunks if c not in texts]
            if missing:
                problems.append(f"{qid}: chunks not found: {missing}")
            if d.get("phrase") and not any(_norm(d["phrase"]) in _norm(t) for t in texts.values()):
                problems.append(f"{qid}: phrase {d['phrase']!r} not in {chunks}")
        if answerable and d["route"] in ("sql", "both") and not d.get("sql"):
            problems.append(f"{qid}: answerable table question without reference SQL")
        if answerable and d["route"] in ("docs", "both") and not chunks:
            problems.append(f"{qid}: answerable document question without source chunks")
        records.append({
            "id": qid, "question": d["q"], "route": d["route"], "answerable": answerable,
            "reference_sql": d.get("sql"),
            "reference_result": {"columns": columns, "rows": rows[:5]} if rows else None,
            "reference_answer": answer,
            "answer_must_contain": [sorted(set(map(str, g))) for g in must],
            "source_chunks": chunks, "key_phrase": d.get("phrase"),
            "tags": d.get("tags", []), "as_of": AS_OF,
        })
    if problems:
        raise SystemExit("eval set problems:\n  " + "\n  ".join(problems))
    return sorted(records, key=lambda r: r["id"])


def main() -> None:
    load_dotenv(find_dotenv(usecwd=True))
    p = argparse.ArgumentParser()
    p.add_argument("--check", action="store_true", help="compare with the existing file; write nothing")
    args = p.parse_args()

    from app.db import connect_readonly, run_select

    def rows_of(sql):
        columns, rows, _ = run_select(sql, 50)
        return columns, rows

    def chunk_texts(ids):
        with connect_readonly() as conn:
            return dict(conn.execute("SELECT id, text FROM doc_chunks WHERE id = ANY(%s)", [ids]).fetchall())

    records = build(rows_of, chunk_texts)
    lines = [json.dumps(r, ensure_ascii=False) for r in records]
    if args.check:
        old = OUT.read_text().splitlines() if OUT.exists() else []
        diff = sorted(set(lines) ^ set(old))
        print(f"{len(records)} questions; {'no differences' if not diff else f'{len(diff)} lines differ'}")
        sys.exit(1 if diff else 0)
    OUT.write_text("\n".join(lines) + "\n")
    by = {}
    for r in records:
        key = r["route"] if r["answerable"] else "unanswerable"
        by[key] = by.get(key, 0) + 1
    print(f"wrote {len(records)} questions to {OUT}: {by}")


if __name__ == "__main__":
    main()
