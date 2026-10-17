"""reports/<run_id>/{report.md, evidence.json}. Missing data is printed as "n/a", never invented."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

ROWS = [("p50 latency (ms)", "p50", 1000, 1), ("p95 latency (ms)", "p95", 1000, 1),
        ("p99 latency (ms)", "p99", 1000, 1), ("throughput (req/s)", "rps", 1, 1),
        ("5xx error rate (%)", "error_ratio", 100, 2), ("pool util peak (%)", "pool_util", 100, 0),
        ("pool wait p95 (ms)", "pool_wait_p95", 1000, 1), ("process CPU (cores)", "cpu_busy", 1, 2)]
PHASES = [("BASELINE", "load_start", "inject"), ("DETECT", "inject", "detect_end"),
          ("DIAGNOSE", "detect_end", "diagnosed"), ("RECOVER", "recover", "recovered"),
          ("VERIFY", "recovered", "verify_end")]


def _n(v, scale: float = 1, nd: int = 1) -> str:
    return "n/a" if v is None else f"{v * scale:.{nd}f}"


def _t(ts) -> str:
    return "n/a" if ts is None else datetime.fromtimestamp(ts, UTC).strftime("%H:%M:%S")


def _yn(v) -> str:
    return "n/a" if v is None else ("yes" if v else "no")


def render(r: dict) -> str:
    t, al, ph, c = r["timeline"], r["alert"], r["phases"], r["checks"]
    b, a = ph["baseline"], ph["after"]
    limit = None if b.get("p95") is None else b["p95"] * 1.2
    top = r["diagnoses"][0]
    out = [f"# PulseOps run `{r['run_id']}`", "", "## Summary", "",
           f"**{r['verdict']}** - scenario `{r['scenario']}`: {r['description']}", "",
           f"- p95 after fix <= 1.2x baseline: {_yn(c['p95_within_1_2x'])} "
           f"(after {_n(a.get('p95'), 1000)} ms, limit {_n(limit, 1000)} ms)",
           f"- error rate after fix < 1%: {_yn(c['error_below_1pct'])} "
           f"(after {_n(a.get('error_ratio'), 100, 2)} %)",
           f"- diagnosis == expected: {_yn(c['diagnosis_correct'])} "
           f"(got `{top['id']}`, expected `{r['expected_diagnosis']}`)", "",
           "## Timeline (UTC)", "", "| Phase | Start | End | Seconds |", "|---|---|---|---|"]
    for name, k0, k1 in PHASES:
        dur = None if t.get(k0) is None or t.get(k1) is None else t[k1] - t[k0]
        out.append(f"| {name} | {_t(t.get(k0))} | {_t(t.get(k1))} | {_n(dur, 1, 0)} |")
    out += ["", "## Metrics before / during / after", "",
            "| Metric | Before | During | After |", "|---|---|---|---|"]
    for label, key, s, nd in ROWS:
        cells = (_n(ph[p].get(key), s, nd) for p in ("baseline", "during", "after"))
        out.append(f"| {label} | " + " | ".join(cells) + " |")
    out += ["", "## Alert", "",
            f"- Expected: {', '.join(al['expected']) or 'n/a'}",
            f"- Fired within detect timeout ({r['params']['detect']}s): {_yn(al['fired'])}",
            f"- Time to detect: {_n(al['time_to_detect_s'], 1, 1)} s (2s polling)",
            f"- Firing at that moment: {', '.join(al['firing']) or 'none'}", "",
            "## Diagnosis", "", f"Expected `{r['expected_diagnosis']}`. Ranked result:", ""]
    out += [f"{i}. **{d['id']}** - {d['why']}" for i, d in enumerate(r["diagnoses"], 1)]
    out += ["", "| Evidence | Value |", "|---|---|"]
    out += [f"| {k} | {_n(v, 1, 3) if isinstance(v, float) else (v if v is not None else 'n/a')} |"
            for k, v in r["evidence"].items()]
    out += ["", "## Fix applied", "", r.get("fix_description") or "n/a",
            f"\nrecover() succeeded: {_yn(r['recovered'])} {r.get('recover_error') or ''}",
            "", "## Caveats", "",
            "- Single run (N=1), laptop-scale Docker stack; no repeats, no confidence interval.",
            f"- Phases: baseline {r['params']['baseline']}s, verify {r['params']['verify']}s "
            f"(diagnose {r['params']['diagnose']}s). Metric windows skip a warm-up of up to 10s.",
            "- Latency/errors are server-side Prometheus data; client timeouts not counted.",
            "- Trace evidence uses at most 200 of the newest traces in the window.",
            "- Standalone `diagnose` baselines on the window just before (may be contaminated).",
            "- Thresholds used: " + ", ".join(f"{k}={v}" for k, v in r["thresholds"].items()), ""]
    return "\n".join(out)


def write(r: dict, root: str | Path = "reports") -> Path:
    d = Path(root) / r["run_id"]
    d.mkdir(parents=True, exist_ok=True)
    (d / "evidence.json").write_text(json.dumps(r, indent=2, default=str))
    (d / "report.md").write_text(render(r))
    return d


def load(run_id: str = "latest", root: str | Path = "reports") -> dict:
    root = Path(root)
    if run_id == "latest":  # run ids start with a timestamp, so lexical order is chronological
        runs = sorted(root.glob("*/evidence.json"))
        if not runs:
            raise FileNotFoundError(f"no runs found under {root}/")
        return json.loads(runs[-1].read_text())
    return json.loads((root / run_id / "evidence.json").read_text())
