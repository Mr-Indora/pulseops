import csv
import os
import subprocess
import sys
from pathlib import Path

import pytest

API_URL = os.environ.get("PULSEOPS_API_URL")
# Acceptance runs set PULSEOPS_REQUIRE_SMOKE=1 so a missing URL fails instead of a silent skip.
pytestmark = pytest.mark.skipif(
    not API_URL and not os.environ.get("PULSEOPS_REQUIRE_SMOKE"), reason="PULSEOPS_API_URL not set"
)

ROOT = Path(__file__).resolve().parents[2]


def test_short_headless_run_has_traffic_and_no_failures(tmp_path):
    assert API_URL, "PULSEOPS_REQUIRE_SMOKE is set but PULSEOPS_API_URL is not"
    prefix = tmp_path / "smoke"
    subprocess.run(
        [sys.executable, "-m", "locust", "-f", "workload/locustfile.py", "--headless",
         "--profile", "normal", "-u", "5", "-r", "5",  # harness check, not a capacity test
         "--run-time", "15s", "--csv", str(prefix), "--host", API_URL],
        cwd=ROOT, check=True, timeout=90,
    )
    with open(f"{prefix}_stats.csv") as f:
        total = next(r for r in csv.DictReader(f) if r["Name"] == "Aggregated")
    requests, failures = int(total["Request Count"]), int(total["Failure Count"])
    assert requests > 0
    assert failures / requests < 0.01
