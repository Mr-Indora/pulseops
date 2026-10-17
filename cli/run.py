"""Experiment flow (Blueprint 5.2): BASELINE, inject, DETECT, DIAGNOSE, recover, VERIFY."""
from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

from cli import grafana, report
from cli.jaeger import analyze, fetch_traces
from cli.prom import Prom
from cli.rules import THRESHOLDS, diagnose
from faults import injector

POLL_S = 2.0


def measure_window(start: float, end: float, warmup_frac: float = 0.25, warmup_cap: float = 10.0):
    """Skip the load ramp-up / recovery transient at the start of a phase (<= 10s, <= 25%)."""
    return start + min(warmup_cap, (end - start) * warmup_frac), end


def new_run_id(scenario: str, ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).strftime("%Y%m%d-%H%M%S") + f"-{scenario}"


def expected_alerts(spec: dict) -> list[str]:
    raw = spec.get("expected_alert") or []
    parts = raw if isinstance(raw, list) else re.split(r"\s*(?:/|,|\||\bor\b)\s*", raw)
    return [a for a in parts if a]


def _profile_size(profile: str) -> dict:
    try:
        from workload.profiles import PROFILES
        return {k: PROFILES[profile][k] for k in ("users", "spawn_rate")}
    except (ImportError, KeyError, TypeError):
        return {}  # let locustfile decide


def locust_cmd(profile: str, run_time_s: int, prefix: str, url: str) -> list[str]:
    cmd = [sys.executable, "-m", "locust", "-f", "workload/locustfile.py", "--headless",
           "--profile", profile, "--run-time", f"{run_time_s}s", "--csv", prefix, "--host", url]
    size = _profile_size(profile)
    return cmd + (["-u", str(size["users"]), "-r", str(size["spawn_rate"])] if size else [])


def start_locust(profile: str, prefix: Path, run_time_s: int) -> subprocess.Popen:
    url = os.environ.get("PULSEOPS_API_URL", "http://localhost:8000")
    with open(f"{prefix}.log", "wb") as log:
        proc = subprocess.Popen(locust_cmd(profile, run_time_s, str(prefix), url), stdout=log,
                                stderr=subprocess.STDOUT)
    time.sleep(3)
    if proc.poll() is not None:
        raise RuntimeError(f"locust ({profile}) exited with {proc.returncode}; see {prefix}.log")
    return proc


def stop_locust(proc: subprocess.Popen | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    proc.send_signal(signal.SIGINT)  # graceful: Locust flushes its CSV files on the way out
    try:
        proc.wait(20)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()  # reap it, otherwise poll() can still report "running" right after the kill


def cpu_limit(container: str = "pulseops-api") -> float | None:
    try:
        out = subprocess.run(["docker", "inspect", "-f", "{{.HostConfig.NanoCpus}}", container],
                             capture_output=True, text=True, timeout=10, check=True).stdout
        return int(out.strip()) / 1e9 or None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def collect_evidence(prom: Prom, base: tuple, during: tuple) -> tuple[dict, dict, dict]:
    """Flat Section-6 evidence dict plus the raw baseline/during metrics."""
    b, d = prom.window(*base), prom.window(*during)
    ratio = d["p95"] / b["p95"] if d["p95"] is not None and b["p95"] else None
    ev = {"p95_ratio": ratio, **{k: d[k] for k in
          ("error_ratio", "pool_util", "pool_wait_p95", "cpu_busy", "process_restarted")}}
    try:
        ev.update(analyze(fetch_traces(*during)))
    except (httpx.HTTPError, ValueError):
        ev.update(db_time_share=None, top_statement_share=None, db_error_spans=None)
    ev["cpu_limit"] = cpu_limit()
    return ev, b, d


def wait_for_alert(prom: Prom, expected: list[str], timeout: float) -> tuple[float | None, list]:
    deadline = time.time() + timeout
    while True:
        try:
            alerts = prom.alerts()
            firing = sorted({a["labels"]["alertname"] for a in alerts if a["state"] == "firing"})
        except httpx.HTTPError:
            firing = []
        if any(n in expected for n in firing):
            return time.time(), firing
        if time.time() >= deadline:
            return None, firing
        time.sleep(POLL_S)


def _check(value, ok) -> bool | None:
    return None if value is None else bool(ok(value))


def run(scenario: str, baseline: int = 60, verify: int = 60, detect: int = 120,
        diagnose_s: int = 30, root: str = "reports") -> dict:
    spec = injector.spec(scenario)
    prom, profile = Prom(), spec.get("workload_profile", "normal")
    t = {"start": time.time()}
    rdir = Path(root) / new_run_id(scenario, t["start"])
    rdir.mkdir(parents=True, exist_ok=True)
    budget = baseline + detect + diagnose_s + verify + 90  # only a bound; we stop Locust ourselves
    procs: list = []
    fault_load = None
    recovered, recover_error = False, None
    try:
        procs.append(start_locust("normal", rdir / "locust", budget))  # baseline = normal load
        t["load_start"] = time.time()
        time.sleep(baseline)
        t["inject"] = time.time()
        injector.inject(scenario)
        grafana.annotate("INJECT", scenario)
        if profile != "normal":  # load-driven fault (S3): extra pressure on top of normal traffic
            fault_load = start_locust(profile, rdir / "locust_fault", budget)
            procs.append(fault_load)
        seen, firing = wait_for_alert(prom, expected_alerts(spec), detect)
        t["detect_end"] = time.time()
        time.sleep(diagnose_s)  # let the fault show in the metric windows before reading them
        t["diagnosed"] = time.time()
        ev, base_m, during_m = collect_evidence(prom, measure_window(t["load_start"], t["inject"]),
                                                (t["inject"], t["diagnosed"]))
        diagnoses = diagnose(ev)
        t["recover"] = time.time()
        stop_locust(fault_load)
        injector.recover(scenario)
        recovered = True
        grafana.annotate("FIX", scenario)
        t["recovered"] = time.time()
        time.sleep(verify)
        t["verify_end"] = time.time()
    finally:  # leave the system clean even on Ctrl-C or any exception
        if not recovered:
            try:
                injector.recover(scenario)
                recovered = True
            except Exception as exc:  # noqa: BLE001 - report and keep stopping Locust
                recover_error = repr(exc)
                print(f"WARNING: recover({scenario}) failed: {exc!r}", file=sys.stderr)
        for p in procs:
            stop_locust(p)
    after = prom.window(*measure_window(t["recovered"], t["verify_end"]))
    checks = {
        "p95_within_1_2x": None if after["p95"] is None or base_m["p95"] is None
        else after["p95"] <= 1.2 * base_m["p95"],
        "error_below_1pct": _check(after["error_ratio"], lambda v: v < 0.01),
        "diagnosis_correct": diagnoses[0]["id"] == spec["expected_diagnosis"],
    }
    result = {
        "run_id": rdir.name, "scenario": scenario, "description": spec.get("description", ""),
        "verdict": "PASS" if all(v is True for v in checks.values()) else "FAIL", "checks": checks,
        "expected_diagnosis": spec["expected_diagnosis"], "diagnoses": diagnoses, "evidence": ev,
        "timeline": t, "phases": {"baseline": base_m, "during": during_m, "after": after},
        "alert": {"expected": expected_alerts(spec), "fired": seen is not None, "firing": firing,
                  "time_to_detect_s": None if seen is None else seen - t["inject"]},
        "fix_description": spec.get("fix_description"), "recovered": recovered,
        "recover_error": recover_error, "thresholds": THRESHOLDS,
        "params": {"baseline": baseline, "verify": verify, "detect": detect,
                   "diagnose": diagnose_s},
    }
    report.write(result, root)
    return result
