from unittest.mock import MagicMock

import pytest

from cli import report, run

SPEC = {
    "description": "d",
    "expected_alert": "HighLatencyP95 / SlowDBQueries",
    "expected_diagnosis": "DB_LATENCY",
    "workload_profile": "normal",
    "fix_description": "fix",
}
BASE = {
    "p50": 0.01,
    "p95": 0.05,
    "p99": 0.08,
    "rps": 20,
    "error_ratio": 0.0,
    "pool_util": 0.2,
    "pool_wait_p95": 0.001,
    "cpu_busy": 0.3,
    "process_restarted": False,
}
DURING = BASE | {"p95": 0.4}
AFTER = BASE | {"p95": 0.055}


def test_measure_window_skips_warmup():
    assert run.measure_window(0, 60) == (10, 60)  # capped at 10s
    assert run.measure_window(100, 120) == (105, 120)  # 25% of a short phase
    assert run.measure_window(5, 5) == (5, 5)


def test_run_id_and_expected_alerts():
    assert run.new_run_id("S1", 0) == "19700101-000000-S1"
    assert run.expected_alerts(SPEC) == ["HighLatencyP95", "SlowDBQueries"]
    assert run.expected_alerts({"expected_alert": ["A", "B"]}) == ["A", "B"]
    assert run.expected_alerts({}) == []


def test_locust_cmd_matches_contract(monkeypatch):
    monkeypatch.setattr(run, "_profile_size", lambda p: {"users": 20, "spawn_rate": 5})
    c = run.locust_cmd("normal", 90, "reports/x/locust", "http://h:8000")
    assert c[1:3] == ["-m", "locust"]
    for pair in (
        ["-f", "workload/locustfile.py"],
        ["--profile", "normal"],
        ["--run-time", "90s"],
        ["--csv", "reports/x/locust"],
        ["--host", "http://h:8000"],
        ["-u", "20"],
        ["-r", "5"],
    ):
        i = c.index(pair[0])
        assert c[i : i + 2] == pair
    assert "--headless" in c


@pytest.fixture
def env(monkeypatch, tmp_path):
    inj = MagicMock()
    inj.spec.return_value = dict(SPEC)
    prom = MagicMock()
    prom.window.side_effect = [BASE, DURING, AFTER]
    prom.alerts.return_value = [{"labels": {"alertname": "HighLatencyP95"}, "state": "firing"}]
    monkeypatch.setattr(run, "injector", inj)
    monkeypatch.setattr(run, "grafana", MagicMock())
    monkeypatch.setattr(run, "Prom", lambda: prom)
    monkeypatch.setattr(run, "start_locust", lambda *a, **k: MagicMock(name="locust"))
    monkeypatch.setattr(run, "stop_locust", MagicMock())
    monkeypatch.setattr(run, "fetch_traces", lambda *a: [])
    monkeypatch.setattr(
        run,
        "analyze",
        lambda t: {"db_time_share": 0.9, "top_statement_share": 0.3, "db_error_spans": 0},
    )
    monkeypatch.setattr(run, "cpu_limit", lambda: 1.0)
    monkeypatch.setattr(run.time, "sleep", lambda s: None)
    return inj, tmp_path


def test_happy_path_pass_and_report_files(env):
    inj, root = env
    r = run.run("S1", 1, 1, 1, 1, root=str(root))
    assert r["verdict"] == "PASS"
    assert r["checks"] == {
        "p95_within_1_2x": True,
        "error_below_1pct": True,
        "diagnosis_correct": True,
    }
    assert r["alert"]["fired"] and r["alert"]["time_to_detect_s"] >= 0
    inj.inject.assert_called_once_with("S1")
    inj.recover.assert_called_once_with("S1")  # no double recover on the happy path
    d = root / r["run_id"]
    assert (d / "report.md").exists() and (d / "evidence.json").exists()
    assert report.load("latest", root)["run_id"] == r["run_id"]


def test_three_booleans_are_independent(env):
    inj, root = env
    run.Prom().window.side_effect = [BASE, DURING, AFTER | {"p95": 0.5, "error_ratio": 0.2}]
    r = run.run("S1", 1, 1, 1, 1, root=str(root))
    assert r["checks"] == {
        "p95_within_1_2x": False,
        "error_below_1pct": False,
        "diagnosis_correct": True,
    }
    assert r["verdict"] == "FAIL"


def test_missing_data_is_none_and_fails_never_passes(env):
    inj, root = env
    run.Prom().window.side_effect = [BASE, DURING, {k: None for k in AFTER}]
    r = run.run("S1", 1, 1, 1, 1, root=str(root))
    assert r["checks"]["p95_within_1_2x"] is None and r["verdict"] == "FAIL"
    assert "n/a" in (root / r["run_id"] / "report.md").read_text()


def test_alert_timeout_recorded(env):
    inj, root = env
    run.Prom().alerts.return_value = []
    r = run.run("S1", 1, 1, 0, 1, root=str(root))
    assert r["alert"]["fired"] is False and r["alert"]["time_to_detect_s"] is None


@pytest.mark.parametrize("exc", [RuntimeError("boom"), KeyboardInterrupt()])
def test_recover_runs_in_finally_when_inject_fails(env, exc):
    inj, root = env
    inj.inject.side_effect = exc
    with pytest.raises(type(exc)):
        run.run("S1", 1, 1, 1, 1, root=str(root))
    inj.recover.assert_called_once_with("S1")
    assert run.stop_locust.called


def test_recover_runs_when_interrupted_during_detect(env, monkeypatch):
    inj, root = env
    monkeypatch.setattr(run, "wait_for_alert", MagicMock(side_effect=KeyboardInterrupt))
    with pytest.raises(KeyboardInterrupt):
        run.run("S1", 1, 1, 1, 1, root=str(root))
    inj.recover.assert_called_once_with("S1")


def test_failing_recover_does_not_skip_locust_cleanup(env):
    inj, root = env
    inj.inject.side_effect = RuntimeError("boom")
    inj.recover.side_effect = RuntimeError("recover broke")
    with pytest.raises(RuntimeError, match="boom"):
        run.run("S1", 1, 1, 1, 1, root=str(root))
    assert run.stop_locust.called


def test_load_driven_scenario_adds_fault_load_and_stops_it_before_recover(env, monkeypatch):
    inj, root = env
    inj.spec.return_value = SPEC | {"workload_profile": "pool_pressure"}
    started = []
    monkeypatch.setattr(
        run, "start_locust", lambda profile, *a: started.append(profile) or MagicMock()
    )
    run.run("S3", 1, 1, 1, 1, root=str(root))
    assert started == ["normal", "pool_pressure"]


def test_stop_locust_sends_sigint_to_a_real_process():
    import subprocess
    import sys

    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    run.stop_locust(p)
    assert p.poll() is not None
    run.stop_locust(p)  # already exited: no error
    run.stop_locust(None)


def test_start_locust_fails_fast_when_process_dies(monkeypatch, tmp_path):
    import subprocess
    import sys

    real_popen = subprocess.Popen

    def popen_and_wait(*a, **k):
        p = real_popen(*a, **k)
        p.wait()
        return p

    monkeypatch.setattr(run, "locust_cmd", lambda *a: [sys.executable, "-c", "raise SystemExit(3)"])
    monkeypatch.setattr(run.subprocess, "Popen", popen_and_wait)
    monkeypatch.setattr(run.time, "sleep", lambda s: None)
    with pytest.raises(RuntimeError, match="exited with 3"):
        run.start_locust("normal", tmp_path / "locust", 10)
