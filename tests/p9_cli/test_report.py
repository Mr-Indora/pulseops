from cli import report
from cli.rules import THRESHOLDS

M = {
    "p50": 0.012,
    "p95": 0.05,
    "p99": 0.09,
    "rps": 21.5,
    "error_ratio": 0.0,
    "pool_util": 0.3,
    "pool_wait_p95": 0.002,
    "cpu_busy": 0.31,
}


def fixture(**over):
    r = {
        "run_id": "20260101-000000-S4_missing_index",
        "scenario": "S4_missing_index",
        "description": "missing index",
        "verdict": "PASS",
        "expected_diagnosis": "SLOW_QUERY_MISSING_INDEX",
        "checks": {"p95_within_1_2x": True, "error_below_1pct": True, "diagnosis_correct": True},
        "diagnoses": [
            {"id": "SLOW_QUERY_MISSING_INDEX", "why": "one statement dominates", "evidence": {}}
        ],
        "evidence": {"p95_ratio": 8.123456, "db_time_share": 0.9, "db_error_spans": None},
        "timeline": {
            "load_start": 1_700_000_000,
            "inject": 1_700_000_060,
            "detect_end": 1_700_000_075,
            "diagnosed": 1_700_000_105,
            "recover": 1_700_000_105,
            "recovered": 1_700_000_110,
            "verify_end": 1_700_000_170,
        },
        "phases": {"baseline": M, "during": M | {"p95": 0.4}, "after": M | {"p95": 0.055}},
        "alert": {
            "expected": ["SlowDBQueries"],
            "fired": True,
            "firing": ["SlowDBQueries"],
            "time_to_detect_s": 15.2,
        },
        "fix_description": "alembic upgrade head",
        "recovered": True,
        "recover_error": None,
        "thresholds": THRESHOLDS,
        "params": {"baseline": 60, "verify": 60, "detect": 120, "diagnose": 30},
    }
    return r | over


def test_all_sections_present():
    md = report.render(fixture())
    for h in (
        "## Summary",
        "## Timeline",
        "## Metrics before / during / after",
        "## Alert",
        "## Diagnosis",
        "## Fix applied",
        "## Caveats",
    ):
        assert h in md
    assert "**PASS**" in md and "15.2 s" in md and "alembic upgrade head" in md
    assert "N=1" in md and "p95_ratio=2.0" in md


def test_values_and_units_rendered():
    md = report.render(fixture())
    assert "| p95 latency (ms) | 50.0 | 400.0 | 55.0 |" in md
    assert "| 5xx error rate (%) | 0.00 | 0.00 | 0.00 |" in md
    assert "| p95_ratio | 8.123 |" in md


def test_missing_data_is_na_not_invented():
    r = fixture(
        verdict="FAIL",
        checks={"p95_within_1_2x": None, "error_below_1pct": None, "diagnosis_correct": False},
        alert={"expected": [], "fired": False, "firing": [], "time_to_detect_s": None},
    )
    r["phases"]["after"] = {k: None for k in M}
    r["timeline"]["recovered"] = None
    md = report.render(r)
    assert "| p95 latency (ms) | 50.0 | 400.0 | n/a |" in md
    assert "Time to detect: n/a" in md and "p95 after fix <= 1.2x baseline: n/a" in md
    assert "| db_error_spans | n/a |" in md and "**FAIL**" in md


def test_write_load_roundtrip(tmp_path):
    d = report.write(fixture(), tmp_path)
    assert (d / "report.md").read_text().startswith("# PulseOps run")
    assert (
        report.load("20260101-000000-S4_missing_index", tmp_path)["scenario"] == "S4_missing_index"
    )
    assert report.load("latest", tmp_path)["verdict"] == "PASS"
