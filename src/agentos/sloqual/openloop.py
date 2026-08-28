"""Open-loop workload engine (anti coordinated omission).

Arrival schedule is pre-computed from a seeded RNG BEFORE the run; each
request's latency reference point is its SCHEDULED send time on the monotonic
clock; the generator never waits for completions and never slows down because
the system is behind. Requests that cannot be dispatched (in-flight cap
exhausted past a grace horizon) are recorded as NOT_STARTED/dropped — never
silently discarded.
"""
from __future__ import annotations

import random
import queue
import threading
import time
from dataclasses import dataclass, field


def build_schedule(*, count: int, rate_events_per_second: float,
                   seed: int, fixed_rate: bool = False) -> list[int]:
    """Return sorted arrival offsets (ns) relative to schedule start."""
    rng = random.Random(seed)
    interval_ns = 1_000_000_000 / rate_events_per_second
    offsets: list[int] = []
    cursor = 0.0
    for _ in range(count):
        if fixed_rate:
            cursor += interval_ns
        else:
            # exponential inter-arrival => Poisson process at the target rate
            cursor += rng.expovariate(rate_events_per_second) * 1_000_000_000
        offsets.append(int(cursor))
    return offsets


@dataclass
class Observation:
    index: int
    scheduled_offset_ns: int
    dispatch_abs_ns: int | None = None     # perf_counter_ns at dispatch start
    completion_abs_ns: int | None = None   # perf_counter_ns at terminal observe
    outcome: str = "NOT_STARTED"           # SUCCEEDED|DENIED|FAILED|TIMEOUT|NOT_STARTED|...
    service_ns: int = 0
    detail: dict = field(default_factory=dict)

    def as_dict(self, origin_ns: int) -> dict:
        queue_wait_ns = 0
        end_to_end_ns = 0
        if self.dispatch_abs_ns is not None:
            queue_wait_ns = max(0, self.dispatch_abs_ns - (origin_ns + self.scheduled_offset_ns))
            if self.completion_abs_ns is not None:
                end_to_end_ns = self.completion_abs_ns - (origin_ns + self.scheduled_offset_ns)
        return {
            "index": self.index,
            "scheduled_offset_ms": round(self.scheduled_offset_ns / 1e6, 6),
            "dispatch_offset_ms": (
                round((self.dispatch_abs_ns - origin_ns) / 1e6, 6)
                if self.dispatch_abs_ns is not None else None),
            "completion_offset_ms": (
                round((self.completion_abs_ns - origin_ns) / 1e6, 6)
                if self.completion_abs_ns is not None else None),
            "outcome": self.outcome,
            "service_ms": round(self.service_ns / 1e6, 6),
            "queue_wait_ms": round(queue_wait_ns / 1e6, 6),
            "end_to_end_ms": round(end_to_end_ns / 1e6, 6),
            "detail": self.detail,
        }


@dataclass
class OpenLoopResult:
    observations: list[Observation]
    schedule_origin_ns: int
    last_completion_ns: int | None
    not_started: int
    drain_s: float = 0.0

    def summary_counts(self) -> dict:
        counts: dict[str, int] = {}
        for obs in self.observations:
            counts[obs.outcome] = counts.get(obs.outcome, 0) + 1
        return counts

    def raw_rows(self) -> list[dict]:
        return [obs.as_dict(self.schedule_origin_ns) for obs in self.observations]

    def window_end_ns(self) -> int:
        candidates = [self.last_completion_ns or 0]
        if self.observations:
            scheduled_last = self.schedule_origin_ns + self.observations[-1].scheduled_offset_ns
            candidates.append(scheduled_last)
        return max(candidates)


class OpenLoopRunner:
    """Dispatch pre-scheduled requests without closing the loop."""

    def __init__(self, *, max_inflight: int = 512,
                 not_started_grace_s: float = 2.0):
        self.max_inflight = max_inflight
        self.not_started_grace_s = not_started_grace_s

    def run(
        self,
        schedule: list[int],
        *,
        dispatch_fn,                  # (index) -> tuple[str, dict]; blocks to terminal
    ) -> OpenLoopResult:
        origin = time.perf_counter_ns()
        observations: list[Observation | None] = [None] * len(schedule)
        slots = threading.BoundedSemaphore(self.max_inflight)
        lock = threading.Lock()
        not_started = 0
        last_completion: list[int | None] = [None]
        worker_threads: list[threading.Thread] = []

        def worker(index: int) -> None:
            obs = observations[index]
            assert obs is not None
            try:
                dispatch_start = time.perf_counter_ns()
                obs.dispatch_abs_ns = dispatch_start
                outcome, detail = dispatch_fn(index)
                completion = time.perf_counter_ns()
                obs.completion_abs_ns = completion
                obs.outcome = outcome
                obs.service_ns = completion - dispatch_start
                obs.detail = detail
                with lock:
                    if last_completion[0] is None or completion > last_completion[0]:
                        last_completion[0] = completion
            finally:
                slots.release()

        for index, offset_ns in enumerate(schedule):
            target_ns = origin + offset_ns
            delay = target_ns - time.perf_counter_ns()
            if delay > 0:
                time.sleep(delay / 1e9)
            acquired = slots.acquire(timeout=self.not_started_grace_s)
            if not acquired:
                not_started += 1
                observations[index] = Observation(
                    index=index, scheduled_offset_ns=offset_ns,
                    outcome="NOT_STARTED",
                    detail={"reason": "inflight_cap_saturated"})
                continue
            observations[index] = Observation(index=index,
                                              scheduled_offset_ns=offset_ns)
            thread = threading.Thread(target=worker, args=(index,), daemon=True)
            thread.start()
            worker_threads.append(thread)

        dispatch_loop_end = time.perf_counter_ns()
        for thread in worker_threads:
            thread.join(timeout=300.0)
        drain_end = time.perf_counter_ns()
        return OpenLoopResult(
            observations=[obs for obs in observations if obs is not None],
            schedule_origin_ns=origin,
            last_completion_ns=last_completion[0],
            not_started=not_started,
            drain_s=round((drain_end - dispatch_loop_end) / 1e9, 6),
        )

    def run_batched(
            self, schedule: list[int], *, dispatch_batch_fn,
            max_batch_size: int = 32,
            batch_window_s: float = 0.01) -> OpenLoopResult:
        """Dispatch arrivals through a bounded group-commit queue.

        The producer follows the precomputed schedule and never waits for a
        completion.  A single coordinator drains bounded batches; saturation
        is surfaced as NOT_STARTED rather than hidden by backpressure.
        ``dispatch_batch_fn`` receives indexes and returns one
        ``(outcome, detail)`` pair per index in the same order.
        """
        if max_batch_size < 1:
            raise ValueError("max_batch_size must be >= 1")
        if batch_window_s < 0:
            raise ValueError("batch_window_s must be >= 0")

        origin = time.perf_counter_ns()
        observations: list[Observation | None] = [None] * len(schedule)
        pending: queue.Queue = queue.Queue(maxsize=max(1, self.max_inflight))
        sentinel = object()
        not_started = 0
        last_completion: list[int | None] = [None]

        def coordinator() -> None:
            stop_after_batch = False
            while True:
                item = pending.get()
                if item is sentinel:
                    return
                batch = [int(item)]
                deadline = time.perf_counter() + batch_window_s
                while len(batch) < max_batch_size:
                    remaining = deadline - time.perf_counter()
                    if remaining <= 0:
                        break
                    try:
                        item = pending.get(timeout=remaining)
                    except queue.Empty:
                        break
                    if item is sentinel:
                        stop_after_batch = True
                        break
                    batch.append(int(item))

                dispatch_start = time.perf_counter_ns()
                for index in batch:
                    obs = observations[index]
                    assert obs is not None
                    obs.dispatch_abs_ns = dispatch_start
                try:
                    outcomes = list(dispatch_batch_fn(batch))
                    if len(outcomes) != len(batch):
                        raise ValueError(
                            "dispatch_batch_fn returned a different result count")
                except Exception as exc:  # scenario boundary, fail every item
                    outcomes = [("ERROR", {"error": str(exc)[:120]})
                                for _ in batch]
                completion = time.perf_counter_ns()
                for index, (outcome, detail) in zip(batch, outcomes):
                    obs = observations[index]
                    assert obs is not None
                    obs.completion_abs_ns = completion
                    obs.outcome = str(outcome)
                    obs.service_ns = completion - dispatch_start
                    obs.detail = dict(detail or {})
                last_completion[0] = completion
                if stop_after_batch:
                    return

        worker = threading.Thread(target=coordinator, daemon=True)
        worker.start()
        for index, offset_ns in enumerate(schedule):
            target_ns = origin + offset_ns
            delay = target_ns - time.perf_counter_ns()
            if delay > 0:
                time.sleep(delay / 1e9)
            observations[index] = Observation(
                index=index, scheduled_offset_ns=offset_ns)
            try:
                pending.put_nowait(index)
            except queue.Full:
                not_started += 1
                observations[index].outcome = "NOT_STARTED"
                observations[index].detail = {
                    "reason": "batch_queue_saturated"}

        dispatch_loop_end = time.perf_counter_ns()
        pending.put(sentinel)
        worker.join(timeout=300.0)
        drain_end = time.perf_counter_ns()
        return OpenLoopResult(
            observations=[obs for obs in observations if obs is not None],
            schedule_origin_ns=origin,
            last_completion_ns=last_completion[0],
            not_started=not_started,
            drain_s=round((drain_end - dispatch_loop_end) / 1e9, 6),
        )
