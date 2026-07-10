"""Single-process run lifecycle and event registry.

This intentionally assumes one uvicorn worker. Durable run/cell state remains in the database,
so clients can recover by polling after a process restart; live tasks and SSE queues cannot.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from app.db import get_engine, session_scope
from app.models import BenchmarkRun, RunStatus
from app.runner.engine import EventSink, _counts, execute_run
from app.runner.spec import RunSpec


@dataclass(frozen=True)
class RunSnapshot:
    run_id: int
    status: str
    counts: dict[str, int]


class _ManagerSink(EventSink):
    def __init__(self, manager: RunManager, run_id: int) -> None:
        self.manager = manager
        self.run_id = run_id

    def emit(self, event: dict[str, Any]) -> None:
        self.manager._publish(self.run_id, event)


class RunManager:
    def __init__(self, *, replay_size: int = 1000) -> None:
        self._tasks: dict[int, asyncio.Task[None]] = {}
        self._events: dict[int, deque[dict[str, Any]]] = defaultdict(
            lambda: deque(maxlen=replay_size)
        )
        self._subscribers: dict[int, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(set)

    async def launch(self, spec: RunSpec) -> int:
        with session_scope(get_engine()) as session:
            missing = spec.validate_documents(session)
            if missing:
                raise ValueError(f"Unknown document ids: {missing}")
            run = BenchmarkRun(
                name=spec.name,
                task_pack_version="v2",
                pack=spec.pack,
                spec=spec.model_dump(mode="json", by_alias=True),
                status=RunStatus.pending,
            )
            session.add(run)
            session.flush()
            assert run.id is not None
            run_id = run.id
        task = asyncio.create_task(
            execute_run(run_id, spec, _ManagerSink(self, run_id)),
            name=f"colosseum-run-{run_id}",
        )
        self._tasks[run_id] = task
        task.add_done_callback(lambda finished: self._finished(run_id, finished))
        return run_id

    def status(self, run_id: int) -> RunSnapshot:
        with session_scope(get_engine()) as session:
            run = session.get(BenchmarkRun, run_id)
            if run is None:
                raise KeyError(run_id)
            value = run.status.value if isinstance(run.status, RunStatus) else str(run.status)
            return RunSnapshot(run_id, value, _counts(session, run_id))

    async def cancel(self, run_id: int) -> bool:
        task = self._tasks.get(run_id)
        if task is None or task.done():
            return False
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        return True

    async def subscribe(self, run_id: int, *, replay: bool = True) -> AsyncIterator[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        history = list(self._events.get(run_id, ())) if replay else []
        self._subscribers[run_id].add(queue)
        try:
            for event in history:
                yield event
            while True:
                event = await queue.get()
                yield event
                if event.get("type") == "run" and event.get("status") in {
                    "completed",
                    "failed",
                    "cancelled",
                }:
                    break
        finally:
            self._subscribers[run_id].discard(queue)

    def _publish(self, run_id: int, event: dict[str, Any]) -> None:
        self._events[run_id].append(event)
        for queue in tuple(self._subscribers.get(run_id, ())):
            queue.put_nowait(event)

    def _finished(self, run_id: int, task: asyncio.Task[None]) -> None:
        self._tasks.pop(run_id, None)
        if task.cancelled() or task.exception() is None:
            return
        with session_scope(get_engine()) as session:
            run = session.get(BenchmarkRun, run_id)
            if run:
                run.status = RunStatus.failed
                session.add(run)
            counts = _counts(session, run_id)
        self._publish(
            run_id,
            {"type": "run", "run_id": run_id, "status": "failed", "counts": counts},
        )


run_manager = RunManager()
