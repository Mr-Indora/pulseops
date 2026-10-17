"""Deterministic diagnosis rules (Blueprint Section 6). Order = priority:
restart > db_down > pool > slow_query > db_latency > cpu. A missing (None) evidence value
never satisfies a condition, so absent data can only lead to UNKNOWN, never to a guess."""
from __future__ import annotations

import operator as op
from collections.abc import Callable
from typing import NamedTuple

THRESHOLDS = {
    "db_down_error_ratio": 0.2,
    "pool_util": 0.9,
    "pool_wait_p95_s": 0.1,
    "p95_ratio": 2.0,
    "db_share_high": 0.6,
    "db_share_low": 0.4,
    "top_statement_share": 0.6,
    "zero": 0,
    "cpu_near_limit": 0.8,    # fraction of the container CPU limit
    "cpu_limit_default": 1.0,  # compose cpus "1.0" if docker inspect fails
}


def _all(ev: dict, t: dict, *conds: tuple) -> bool:
    """conds are (evidence key, comparison, threshold name)."""
    return all(ev.get(k) is not None and cmp(ev[k], t[name]) for k, cmp, name in conds)


class Rule(NamedTuple):
    id: str
    keys: tuple[str, ...]                 # evidence attached to a match
    test: Callable[[dict, dict], bool]    # (evidence, thresholds) -> matched?
    why: Callable[[dict, dict], str]      # plain-English explanation


def _cpu_near_limit(e: dict, t: dict) -> bool:
    cap = t["cpu_near_limit"] * (e.get("cpu_limit") or t["cpu_limit_default"])
    return e.get("cpu_busy") is not None and e["cpu_busy"] >= cap


_SLOW = (("p95_ratio", op.gt, "p95_ratio"), ("db_time_share", op.gt, "db_share_high"))
_SLOW_KEYS = ("p95_ratio", "db_time_share", "top_statement_share")

RULES = [
    Rule("APP_RESTART", ("process_restarted",),
         lambda e, t: e.get("process_restarted") is True,
         lambda e, t: "The API process start time changed inside the window: the process "
                      "was restarted (crash or kill), not merely slowed down."),
    Rule("DB_DOWN", ("error_ratio", "db_error_spans"),
         lambda e, t: _all(e, t, ("error_ratio", op.gt, "db_down_error_ratio"),
                           ("db_error_spans", op.gt, "zero")),
         lambda e, t: f"{e['error_ratio']:.0%} of requests got 5xx and {e['db_error_spans']} "
                      "spans show DB connection errors: the database is unreachable."),
    Rule("POOL_EXHAUSTION", ("pool_util", "pool_wait_p95"),
         lambda e, t: _all(e, t, ("pool_util", op.ge, "pool_util"),
                           ("pool_wait_p95", op.gt, "pool_wait_p95_s")),
         lambda e, t: f"The connection pool peaked at {e['pool_util']:.0%} and requests waited "
                      f"{e['pool_wait_p95'] * 1000:.0f} ms (p95) for one: demand > pool size."),
    Rule("SLOW_QUERY_MISSING_INDEX", _SLOW_KEYS,
         lambda e, t: _all(e, t, *_SLOW, ("top_statement_share", op.gt, "top_statement_share")),
         lambda e, t: f"p95 is {e['p95_ratio']:.1f}x baseline, {e['db_time_share']:.0%} of time is "
                      f"in the DB and ONE statement owns {e['top_statement_share']:.0%} "
                      "of it: a single query got slow, typical of a missing index."),
    Rule("DB_LATENCY", _SLOW_KEYS,
         lambda e, t: _all(e, t, *_SLOW, ("top_statement_share", op.le, "top_statement_share")),
         lambda e, t: f"p95 is {e['p95_ratio']:.1f}x baseline, {e['db_time_share']:.0%} of time "
                      f"is in the DB, but no statement dominates "
                      f"({e['top_statement_share']:.0%}): every query is slow: DB path slow."),
    Rule("CPU_SATURATION", ("p95_ratio", "db_time_share", "cpu_busy", "cpu_limit"),
         lambda e, t: _all(e, t, ("p95_ratio", op.gt, "p95_ratio"),
                           ("db_time_share", op.lt, "db_share_low")) and _cpu_near_limit(e, t),
         lambda e, t: f"p95 {e['p95_ratio']:.1f}x baseline, only {e['db_time_share']:.0%} of time "
                      f"is in the DB and the process burns {e['cpu_busy']:.2f} cores, near its "
                      "limit: the app itself is CPU-bound."),
]


def diagnose(evidence: dict, thresholds: dict | None = None) -> list[dict]:
    """Ranked matches ({id, why, evidence}); a single UNKNOWN entry if nothing matches."""
    t = thresholds or THRESHOLDS
    hits = [{"id": r.id, "why": r.why(evidence, t),
             "evidence": {k: evidence.get(k) for k in r.keys}}
            for r in RULES if r.test(evidence, t)]
    return hits or [{"id": "UNKNOWN", "evidence": dict(evidence),
                     "why": "No rule matched the collected evidence; not guessing."}]
