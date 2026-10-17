"""python -m cli run <scenario> | list | diagnose --window <s> | verify | report <run_id>"""
from __future__ import annotations

import argparse
import sys
import time

import httpx

from cli import report
from cli import run as runner
from cli.prom import Prom
from cli.rules import diagnose
from faults import injector


def cmd_list(_: argparse.Namespace) -> int:
    for name in injector.list_scenarios():
        print(f"{name:26} {injector.spec(name).get('description', '')}")
    return 0


def cmd_run(a: argparse.Namespace) -> int:
    if a.scenario not in injector.list_scenarios():
        print(f"unknown scenario {a.scenario!r}; try: python -m cli list", file=sys.stderr)
        return 2
    r = runner.run(a.scenario, a.baseline, a.verify, a.detect, a.diagnose)
    print(f"{r['verdict']}  {r['run_id']}  checks={r['checks']}")
    print(f"report: reports/{r['run_id']}/report.md")
    return 0 if r["verdict"] == "PASS" else 1


def cmd_diagnose(a: argparse.Namespace) -> int:
    now = time.time()  # compares the last <window>s with the <window>s before it
    base, during = (now - 2 * a.window, now - a.window), (now - a.window, now)
    ev, _, _ = runner.collect_evidence(Prom(), base, during)
    for i, d in enumerate(diagnose(ev), 1):
        print(f"{i}. {d['id']}: {d['why']}")
    print("evidence:", {k: (round(v, 3) if isinstance(v, float) else v) for k, v in ev.items()})
    return 0


def cmd_verify(a: argparse.Namespace) -> int:
    prom, now = Prom(), time.time()
    cur = prom.window(now - a.window, now)
    try:
        base = report.load("latest")["phases"]["baseline"].get("p95")
    except FileNotFoundError:
        base = None  # no earlier run to compare latency against
    firing = sorted(x["labels"]["alertname"] for x in prom.alerts() if x.get("state") == "firing")
    checks = {
        "p95 <= 1.2x baseline": None if None in (base, cur["p95"]) else cur["p95"] <= 1.2 * base,
        "error rate < 1%": None if cur["error_ratio"] is None else cur["error_ratio"] < 0.01,
        "no alerts firing": not firing,
    }
    for k, v in checks.items():
        print(f"{'n/a' if v is None else ('ok' if v else 'FAIL'):5} {k}")
    print(f"p95={cur['p95']} baseline_p95={base} firing={firing or 'none'}")
    return 0 if all(v is True for v in checks.values()) else 1


def cmd_report(a: argparse.Namespace) -> int:
    d = report.write(report.load(a.run_id))  # re-render from the stored evidence.json
    print(d / "report.md")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m cli", description="PulseOps experiment CLI")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="list scenarios").set_defaults(fn=cmd_list)
    r = sub.add_parser("run", help="run one scenario end to end")
    r.add_argument("scenario")
    for flag, default in (("baseline", 60), ("verify", 60), ("detect", 120), ("diagnose", 30)):
        r.add_argument(f"--{flag}", type=int, default=default, help=f"{flag} phase seconds")
    r.set_defaults(fn=cmd_run)
    d = sub.add_parser("diagnose", help="diagnose the last --window seconds")
    d.add_argument("--window", type=int, default=120)
    d.set_defaults(fn=cmd_diagnose)
    v = sub.add_parser("verify", help="is the system healthy right now?")
    v.add_argument("--window", type=int, default=60)
    v.set_defaults(fn=cmd_verify)
    rp = sub.add_parser("report", help="re-render a report from its evidence.json")
    rp.add_argument("run_id", nargs="?", default="latest")
    rp.set_defaults(fn=cmd_report)
    args = p.parse_args(argv)
    try:
        return args.fn(args)
    except (httpx.HTTPError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
