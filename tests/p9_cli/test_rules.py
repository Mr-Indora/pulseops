import pytest

from cli.rules import THRESHOLDS, diagnose

HEALTHY = {
    "p95_ratio": 1.0,
    "error_ratio": 0.0,
    "pool_util": 0.3,
    "pool_wait_p95": 0.001,
    "db_time_share": 0.5,
    "top_statement_share": 0.3,
    "db_error_spans": 0,
    "process_restarted": False,
    "cpu_busy": 0.3,
    "cpu_limit": 1.0,
}


def ev(**kw):
    return HEALTHY | kw


CASES = [
    ("restart", ev(process_restarted=True), "APP_RESTART"),
    ("db down", ev(error_ratio=0.9, db_error_spans=40), "DB_DOWN"),
    ("errors but no db error spans", ev(error_ratio=0.9), "UNKNOWN"),
    ("pool", ev(pool_util=1.0, pool_wait_p95=0.8), "POOL_EXHAUSTION"),
    ("pool full but no wait", ev(pool_util=1.0, pool_wait_p95=0.01), "UNKNOWN"),
    (
        "missing index",
        ev(p95_ratio=6, db_time_share=0.9, top_statement_share=0.85),
        "SLOW_QUERY_MISSING_INDEX",
    ),
    (
        "db latency spread",
        ev(p95_ratio=4, db_time_share=0.9, top_statement_share=0.3),
        "DB_LATENCY",
    ),
    (
        "boundary top share 0.6 is spread",
        ev(p95_ratio=4, db_time_share=0.9, top_statement_share=0.6),
        "DB_LATENCY",
    ),
    (
        "cpu throttled to 0.2",
        ev(p95_ratio=5, db_time_share=0.1, cpu_busy=0.19, cpu_limit=0.2),
        "CPU_SATURATION",
    ),
    (
        "cpu low and unknown limit",
        ev(p95_ratio=5, db_time_share=0.1, cpu_busy=0.19, cpu_limit=None),
        "UNKNOWN",
    ),
    ("slow but ambiguous db share 0.5", ev(p95_ratio=5, db_time_share=0.5), "UNKNOWN"),
    ("healthy", ev(), "UNKNOWN"),
    ("no data at all", {}, "UNKNOWN"),
    (
        "missing jaeger data cannot give slow-query",
        ev(p95_ratio=6, db_time_share=None, top_statement_share=None),
        "UNKNOWN",
    ),
]


@pytest.mark.parametrize("name,evidence,expected", CASES, ids=[c[0] for c in CASES])
def test_top_diagnosis(name, evidence, expected):
    assert diagnose(evidence)[0]["id"] == expected


def test_priority_when_several_rules_match():
    both = ev(
        process_restarted=True, error_ratio=0.9, db_error_spans=5, pool_util=1, pool_wait_p95=1
    )
    assert [d["id"] for d in diagnose(both)] == ["APP_RESTART", "DB_DOWN", "POOL_EXHAUSTION"]


def test_matches_carry_evidence_and_plain_english_why():
    d = diagnose(ev(p95_ratio=6, db_time_share=0.9, top_statement_share=0.85))[0]
    assert d["evidence"]["top_statement_share"] == 0.85 and "ONE statement" in d["why"]


def test_unknown_is_honest():
    d = diagnose(ev())[0]
    assert d["id"] == "UNKNOWN" and "not guessing" in d["why"]


def test_thresholds_are_configurable():
    e = ev(p95_ratio=1.5, db_time_share=0.9, top_statement_share=0.9)
    assert diagnose(e)[0]["id"] == "UNKNOWN"
    assert diagnose(e, THRESHOLDS | {"p95_ratio": 1.2})[0]["id"] == "SLOW_QUERY_MISSING_INDEX"
