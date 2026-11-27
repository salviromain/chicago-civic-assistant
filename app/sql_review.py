"""Checks that an LLM-written query does what the question asks. (Day 11)

    review_sql("How many graffiti removal requests in ward 12 in 2025?",
               "SELECT count(*) ... AND NOT origin IN ('Generated In House', 'Mass Entry') ...")
    -> ["The question doesn't mention residents, so keep city-generated requests: ..."]

The prompt states these rules (docs/TABLES.md), but on the eval set the model still
broke them (Day 9: 6 of 12 wrong answers dropped city-generated requests). Rules a
regular expression can check are checked here, in code. A problem goes back to the
model once, like a database error; it never blocks a query on its own.

Each check fires only on a clear mismatch between the question's words and the SQL,
so a correct query passes untouched.
"""

from __future__ import annotations

import re

CITY_GENERATED = re.compile(r"Generated In House|Mass Entry", re.I)
EXCLUDES_ORIGIN = re.compile(r"\bNOT\s+(?:\w+\.)?origin\s+IN\b|\borigin\s+NOT\s+IN\b|\borigin\s*(?:<>|!=)", re.I)
RESIDENT_WORDS = re.compile(r"\bresidents?\b|\bpeople\b|\bthe public\b|\bcitizens?\b|\bcity[- ]generated\b|\bcity generate", re.I)
REPORT_WORDS = re.compile(r"\breports?\b|\bcalls?\b|\bduplicates?\b|\bevery report\b|\bincluding duplicates\b", re.I)
AVERAGE_WORDS = re.compile(r"\baverage\b|\bmean\b", re.I)
MEDIAN_WORDS = re.compile(r"\bmedian\b|\btypical\b", re.I)
# "Which address had the most ...": ORDER BY ... LIMIT 1 returns one row even when two tie
TOP_ONE = re.compile(r"\bORDER\s+BY\b[^;]*\bLIMIT\s+1\s*;?\s*$", re.I)


def review_sql(question: str, sql: str) -> list[str]:
    """Problems with the query for this question, as instructions for a fix. Empty = fine."""
    problems = []
    q, s = question, sql

    uses_311 = "service_requests_311" in s
    if uses_311 and CITY_GENERATED.search(s) and EXCLUDES_ORIGIN.search(s) and not RESIDENT_WORDS.search(q):
        problems.append(
            "The question doesn't mention residents, so keep city-generated requests: remove the "
            "filter on origin ('Generated In House', 'Mass Entry'). 'Complaints' and 'requests' "
            "alone don't mean residents.")

    if (uses_311 and re.search(r"\bcount\s*\(", s, re.I) and "duplicate" not in s.lower()
            and not REPORT_WORDS.search(q)):
        problems.append("311 counts must exclude duplicates: add NOT duplicate.")

    if AVERAGE_WORDS.search(q) and not MEDIAN_WORDS.search(q) and re.search(r"percentile_cont", s, re.I) \
            and not re.search(r"\bavg\s*\(", s, re.I):
        problems.append("The question asks for the average: use avg(...), not the median (percentile_cont).")
    if MEDIAN_WORDS.search(q) and not AVERAGE_WORDS.search(q) and re.search(r"\bavg\s*\(", s, re.I) \
            and not re.search(r"percentile_cont", s, re.I):
        problems.append("The question asks for the median: use percentile_cont(0.5) WITHIN GROUP (ORDER BY ...), not avg(...).")

    if ("building_violations" in s and re.search(r"\binspections\b", q, re.I)
            and re.search(r"\bshare\b|\bpercent|\bhow many inspections\b|\bproportion\b|\brate\b", q, re.I)
            and "inspection_number" not in s):
        problems.append(
            "The question counts inspections, and building_violations has one row per violation: "
            "count inspections with count(DISTINCT inspection_number).")

    if (re.search(r"\bopen fire hydrant", q, re.I) and not re.search(r"\bstill open\b|\bare open\b", q, re.I)
            and re.search(r"\bstatus\s*=\s*'Open'", s, re.I)):
        problems.append(
            "'Open Fire Hydrant Complaint' is the type name (sr_short_code 'WBT'): 'open' here is "
            "not the status. Remove status = 'Open'.")

    if TOP_ONE.search(s):
        problems.append(
            "LIMIT 1 hides ties: return the top 5 rows (LIMIT 5) in the same order, so the "
            "answer can say whether several share first place.")
    return problems
