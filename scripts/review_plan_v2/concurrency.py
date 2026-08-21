"""Bounded-parallelism worker pool. Wraps ThreadPoolExecutor with cap + per-task timing."""
from __future__ import annotations

import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any


@dataclass
class TaskResult:
    name: str
    value: Any
    exception: BaseException | None
    duration_ms: int


class TaskNeverStarted(TimeoutError):
    """The task never got a worker slot — it never reached a provider at all.

    A distinct type, not a bare `TimeoutError`, because the orchestrator has to
    tell "never ran" from "ran and timed out" and the difference decides whether
    a leg gets branded misconfigured. Providers already convert their own read
    timeouts into CallResults, so nothing else raises TimeoutError today — but
    `socket.timeout IS TimeoutError` since 3.10, so a future path that lets one
    escape would silently be classified as starvation and SUPPRESS a real
    dead-leg banner. Subclasses TimeoutError so existing handlers still catch it.
    """


def run_with_cap(
    callables: list[tuple[str, Callable[[], Any]]],
    max_workers: int = 4,
    deadline_sec: float | None = None,
) -> list[TaskResult]:
    """Submit all callables to a ThreadPoolExecutor. Return TaskResult per callable in submission order.

    deadline_sec: run-level wall-clock cap on QUEUED work. When it expires,
    futures that have not started are cancelled and reported as TimeoutError.

    What the deadline cannot do is stop a task already running: `Future.cancel()`
    is a no-op once a worker has picked the task up, and the executor must join
    its threads before this function can return. That is a property of the
    runtime, not a bug to fix here -- what bounds in-flight work is the
    per-attempt and per-call budget in the provider layer.

    What it MUST NOT do is throw away results it waited for anyway. The previous
    version recorded every outstanding future as TimeoutError at the deadline and
    then blocked in `ThreadPoolExecutor.__exit__` (`shutdown(wait=True)`) while
    those same tasks finished and returned. Measured: 4 x 10s tasks at
    concurrency 2 with deadline_sec=3.0 ran the full 10s and reported all four
    as failures, two of which had produced values. Upstream that inflates
    `failed_task_count`, so a chunk that WAS reviewed still printed
    '[INCOMPLETE] ... its verdict is unproven' and exited 2 -- and its findings
    were discarded, leaving the gate blind to defects it had already paid to
    find. So: drain first, then harvest, and time out only what genuinely never
    produced a result.
    """
    results: list[TaskResult | None] = [None] * len(callables)
    started = time.monotonic()
    deadline_passed = False

    ex = ThreadPoolExecutor(max_workers=max(1, max_workers))
    try:
        futures = [(idx, name, ex.submit(_timed, fn))
                   for idx, (name, fn) in enumerate(callables)]

        outstanding: list[tuple[int, str, Any]] = []
        for idx, name, fut in futures:
            remaining = None
            if deadline_sec is not None:
                remaining = max(0.0, deadline_sec - (time.monotonic() - started))
            try:
                value, dur_ms = fut.result(timeout=remaining)
                results[idx] = TaskResult(name=name, value=value, exception=None,
                                          duration_ms=dur_ms)
            except TimeoutError as e:
                # Ambiguous: `fut.result(timeout=...)` raises TimeoutError, and so
                # does a task that itself times out. Only the former means the
                # budget blew, and only then may we cancel siblings.
                #
                # This must be resolved HERE, not by re-raising. Python does not
                # route an exception raised inside an `except` clause to a
                # sibling `except` on the same `try`, so a bare `raise` escaped
                # run_with_cap entirely and aborted the whole reviewer phase on
                # the first provider timeout. Verified live: one task raising
                # TimeoutError propagated straight out. The earlier version of
                # the test below used ValueError, which cannot catch this.
                if deadline_sec is None or (time.monotonic() - started) < deadline_sec:
                    results[idx] = TaskResult(
                        name=name, value=None, exception=e,
                        duration_ms=int((time.monotonic() - started) * 1000),
                    )
                    continue
                deadline_passed = True
                fut.cancel()  # effective only while the task is still queued
                outstanding.append((idx, name, fut))
            except Exception as e:  # narrow: don't swallow KeyboardInterrupt/SystemExit
                results[idx] = TaskResult(
                    name=name, value=None, exception=e,
                    duration_ms=int((time.monotonic() - started) * 1000),
                )
    finally:
        # Join workers BEFORE harvesting, so in-flight tasks have finished and
        # `fut.done()` is a settled answer rather than a race.
        ex.shutdown(wait=True)

    if deadline_passed:
        budget_ms = int((deadline_sec or 0) * 1000)
        for idx, name, fut in outstanding:
            if fut.cancelled() or not fut.done():
                results[idx] = TaskResult(
                    name=name, value=None,
                    exception=TaskNeverStarted(
                        f"task did not run within the {deadline_sec:.0f}s run budget"
                    ),
                    duration_ms=budget_ms,
                )
                continue
            exc = fut.exception()
            if exc is not None:
                results[idx] = TaskResult(name=name, value=None, exception=exc,
                                          duration_ms=budget_ms)
            else:
                value, dur_ms = fut.result()
                results[idx] = TaskResult(name=name, value=value, exception=None,
                                          duration_ms=dur_ms)

    return [r for r in results if r is not None]


def _timed(fn: Callable[[], Any]) -> tuple[Any, int]:
    s = time.monotonic()
    v = fn()
    return v, int((time.monotonic() - s) * 1000)
