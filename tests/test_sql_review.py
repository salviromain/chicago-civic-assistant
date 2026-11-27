"""The SQL review: catches the mistakes the eval found, and leaves correct queries alone."""

import pytest

from app.sql_review import review_sql

DROP_CITY = "AND NOT origin IN ('Generated In House', 'Mass Entry')"
GRAF = "SELECT COUNT(*) FROM service_requests_311 WHERE sr_short_code = 'GRAF' AND NOT duplicate "


@pytest.mark.parametrize("question, sql, words", [
    ("How many graffiti removal requests were made in ward 12 in 2025?", GRAF + DROP_CITY, "residents"),
    ("How many vicious animal complaints were made in 2026?",
     "SELECT count(*) FROM service_requests_311 WHERE sr_short_code = 'EAF' AND NOT duplicate AND origin NOT IN ('Generated In House', 'Mass Entry')", "residents"),
    ("How many restaurant complaints were made in 2026, and what does the budget propose for the Department of Public Health?",
     "SELECT COUNT(*) FROM service_requests_311 WHERE sr_short_code = 'HFB' AND NOT duplicate " + DROP_CITY, "residents"),
    ("How many 311 requests are still open?", "SELECT COUNT(*) FROM service_requests_311 WHERE status = 'Open'", "NOT duplicate"),
    ("What was the average number of days to close street light out complaints in 2025?",
     "SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY x) FROM service_requests_311 WHERE NOT duplicate", "avg"),
    ("What is the median processing time for express permits?", "SELECT avg(processing_time) FROM building_permits", "percentile_cont"),
    ("What share of building inspections in 2025 failed?",
     "SELECT count(*) FILTER (WHERE inspection_status = 'FAILED') / count(*) FROM building_violations", "DISTINCT inspection_number"),
    ("How many open fire hydrant complaints were made in July 2025?",
     "SELECT COUNT(*) FROM service_requests_311 WHERE sr_short_code = 'WBT' AND status = 'Open' AND NOT duplicate", "type name"),
    ("Which address had the most heat violations recorded since 2025?",
     "SELECT address, COUNT(*) AS n FROM building_violations WHERE violation_ordinance LIKE '%(13-196-410)%' "
     "GROUP BY address ORDER BY n DESC LIMIT 1", "ties"),
])
def test_catches_the_eval_mistakes(question, sql, words):
    problems = review_sql(question, sql)
    assert len(problems) == 1 and words in problems[0]


@pytest.mark.parametrize("question, sql", [
    ("In which wards do residents report the most graffiti?", GRAF + DROP_CITY),
    ("How many tree requests did the city generate itself in 2025?",
     "SELECT count(*) FROM service_requests_311 WHERE origin IN ('Generated In House', 'Mass Entry') AND NOT duplicate"),
    ("How many duplicate pothole reports were there in 2025?", "SELECT count(*) FROM service_requests_311 WHERE duplicate"),
    ("How many open hydrant complaints in ward 3 in 2025, counting every report?",
     "SELECT count(*) FROM service_requests_311 WHERE sr_short_code = 'WBT' AND ward = 3"),
    ("How many water on street complaints are still open?",
     "SELECT count(*) FROM service_requests_311 WHERE sr_short_code = 'AAE' AND status = 'Open' AND NOT duplicate"),
    ("What was the median time to close a pothole complaint in 2025?",
     "SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY x) FROM service_requests_311 WHERE NOT duplicate"),
    ("What share of building inspections in 2025 failed?",
     "SELECT count(DISTINCT inspection_number) FILTER (WHERE inspection_status = 'FAILED') FROM building_violations"),
    ("How many building violations were recorded in 2025?", "SELECT count(*) FROM building_violations"),
    ("How many building permits were issued in 2025?", "SELECT count(*) FROM building_permits"),
    ("Which address had the most heat violations recorded since 2025?",
     "SELECT address, count(*) AS n FROM building_violations GROUP BY address ORDER BY n DESC LIMIT 5"),
    ("List the 10 wards with the most permits.",
     "SELECT ward, count(*) FROM building_permits GROUP BY ward ORDER BY 2 DESC LIMIT 10"),
])
def test_leaves_correct_queries_alone(question, sql):
    assert review_sql(question, sql) == []
