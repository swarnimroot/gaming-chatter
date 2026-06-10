"""Per-run Anthropic cost meter (Phase 4 follow-up).

Captures the real `usage` from each Anthropic response, prices it per model,
and accumulates it against the currently-running JobRun so `/runs` can show the
actual dollars each pipeline run spent instead of a docstring estimate.

THREAD-LOCAL STACK with EXCLUSIVE semantics. Two facts shape the design:

1. `run_daily_pipeline` calls `run_weekly_extension` INLINE, and that opens its
   own JobRun while the daily row is still running (nested execution, two
   separate rows). `record()` adds tokens to the INNERMOST open run only, so
   synthesis tokens land on the weekly row and are NOT double-counted on the
   daily row — the two rows sum without overlap.
2. Each orchestrator runs in a single thread and nests within that same thread,
   while a concurrently-blocked "skipped" run lives on a different thread. A
   thread-local stack keeps every thread's accounting isolated, so a skipped
   run can never steal the running thread's tokens (a plain global stack could,
   since `record()` targets the top frame). No lock is needed: each stack is
   only ever touched by its owning thread.

`record()` is a no-op when the calling thread has no open run (Anthropic calls
from manual backfill scripts simply go unmetered rather than erroring).

Leak handling: `close_run(run_id)` pops frames down to and including the
matching frame, folding any never-closed inner frames into it, so a crashed
sub-run's tokens are attributed to its parent rather than silently dropped.
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Optional

log = logging.getLogger(__name__)

# USD per MILLION tokens, (input, output), keyed by model id (the app/config.py
# defaults). Standard non-batch list pricing, June 2026. Env-overridden model
# ids absent from this table are priced at $0 with a warning (see _cost_for).
PRICING: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-opus-4-7": (4.00, 20.00),
}
_CACHE_READ_MULT = 0.1     # cache hits billed at 0.1x the input rate
_CACHE_WRITE_MULT = 1.25   # ephemeral cache writes billed at 1.25x the input rate

_TOKEN_KEYS = ("input", "output", "cache_read", "cache_creation")

_local = threading.local()


def _stack() -> list[dict[str, Any]]:
    s = getattr(_local, "gc_cost_stack", None)
    if s is None:
        s = []
        _local.gc_cost_stack = s
    return s


def _empty_counts() -> dict[str, int]:
    return {k: 0 for k in _TOKEN_KEYS}


def open_run(run_id: int) -> None:
    """Push a fresh accounting frame for `run_id` onto the calling thread."""
    frame = {"run_id": run_id, "by_model": {}}
    frame.update(_empty_counts())
    _stack().append(frame)


def record(model: str, usage: Any) -> None:
    """Add one Anthropic response's token usage to the innermost open run.

    No-op when the calling thread has no open run. `usage` is the SDK usage
    object; missing fields default to 0 so this never raises inside a live API
    path.
    """
    if usage is None:
        return
    stack = _stack()
    if not stack:
        return
    counts = {
        "input": getattr(usage, "input_tokens", 0) or 0,
        "output": getattr(usage, "output_tokens", 0) or 0,
        "cache_read": getattr(usage, "cache_read_input_tokens", 0) or 0,
        "cache_creation": getattr(usage, "cache_creation_input_tokens", 0) or 0,
    }
    frame = stack[-1]
    per_model = frame["by_model"].setdefault(model, _empty_counts())
    for k in _TOKEN_KEYS:
        frame[k] += counts[k]
        per_model[k] += counts[k]


def _cost_for(model: str, m: dict[str, int]) -> float:
    rate = PRICING.get(model)
    if rate is None:
        log.warning("cost: no pricing for model %r - counted as $0", model)
        return 0.0
    in_rate, out_rate = rate
    return (
        m["input"] / 1e6 * in_rate
        + m["output"] / 1e6 * out_rate
        + m["cache_read"] / 1e6 * in_rate * _CACHE_READ_MULT
        + m["cache_creation"] / 1e6 * in_rate * _CACHE_WRITE_MULT
    )


def _merge(dst: dict[str, Any], src: dict[str, Any]) -> None:
    for k in _TOKEN_KEYS:
        dst[k] += src[k]
    for model, m in src["by_model"].items():
        d = dst["by_model"].setdefault(model, _empty_counts())
        for k in _TOKEN_KEYS:
            d[k] += m[k]


def close_run(run_id: int) -> dict[str, Any]:
    """Pop the calling thread's stack down to and including `run_id`'s frame;
    return its totals + priced cost.

    Frames above the match (never-closed inner sub-runs) are folded into it.
    Returns zeros if no matching frame is found (e.g. open_run was never called
    for this run), leaving the stack untouched in that case.
    """
    stack = _stack()
    leaked: list[dict[str, Any]] = []
    frame: Optional[dict[str, Any]] = None
    while stack:
        top = stack.pop()
        if top["run_id"] == run_id:
            frame = top
            break
        leaked.append(top)
    if frame is None:
        # run_id not on the stack — restore what we popped and report nothing.
        for fr in reversed(leaked):
            stack.append(fr)
        return {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "by_model": {}}
    for lf in leaked:
        _merge(frame, lf)
    cost = sum(_cost_for(model, m) for model, m in frame["by_model"].items())
    return {
        # Total input-side tokens processed (fresh + cached), informational.
        "input_tokens": frame["input"] + frame["cache_read"] + frame["cache_creation"],
        "output_tokens": frame["output"],
        "cost_usd": round(cost, 6),
        "by_model": frame["by_model"],
    }
