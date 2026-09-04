"""Serialized, coalescing command queue for physical cover providers."""

from __future__ import annotations

import asyncio
import heapq
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from time import monotonic
from typing import Any

from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import Context, HomeAssistant
from homeassistant.util import dt as dt_util

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

COMMAND_QUEUES_KEY = "command_queues"

# Lower numbers run first.
PRIORITY_EMERGENCY = 0
PRIORITY_MANUAL_STOP = 10
PRIORITY_SAFETY = 20
PRIORITY_MANUAL = 30
PRIORITY_AUTOMATIC = 50
PRIORITY_TILT = 60

_DEFAULT_SPACING_SECONDS = 1.0
_DEFAULT_COMMAND_TIMEOUT_SECONDS = 30.0

ValidityCallback = Callable[[], bool]
StartedCallback = Callable[[Context, datetime], None]


@dataclass(slots=True)
class CommandResult:
    """Outcome of one queued provider command."""

    success: bool
    entity_id: str
    command_type: str
    service: str
    issued_at: datetime | None = None
    completed_at: datetime | None = None
    context_id: str | None = None
    error: Exception | None = None
    skipped_reason: str | None = None
    superseded: bool = False


FinishedCallback = Callable[[CommandResult], None]


@dataclass(order=True, slots=True)
class _QueuedCommand:
    """Internal priority-queue item."""

    priority: int
    sequence: int
    entity_id: str = field(compare=False)
    command_type: str = field(compare=False)
    service: str = field(compare=False)
    service_data: dict[str, Any] = field(compare=False)
    coalesce_key: str = field(compare=False)
    context: Context = field(compare=False)
    future: asyncio.Future[CommandResult] = field(compare=False)
    is_valid: ValidityCallback | None = field(compare=False, default=None)
    on_started: StartedCallback | None = field(compare=False, default=None)
    on_finished: FinishedCallback | None = field(compare=False, default=None)
    started: bool = field(compare=False, default=False)
    issued_at: datetime | None = field(compare=False, default=None)
    finished: bool = field(compare=False, default=False)


class SmartShadingCommandQueue:
    """Serialize provider calls and discard obsolete queued targets.

    Commands are coalesced per physical cover and command channel. A newer
    command replaces an older command which has not started only when its
    priority is at least as high. Tilt remains independent. Emergency stop
    commands therefore invalidate queued movement targets and cannot themselves
    be displaced by a later normal automatic target. A manual STOP remains more
    urgent than asset protection, while a manual position target cannot displace
    a queued weather-safety movement.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        *,
        spacing_seconds: float = _DEFAULT_SPACING_SECONDS,
        command_timeout_seconds: float = _DEFAULT_COMMAND_TIMEOUT_SECONDS,
        owner_id: str | None = None,
    ) -> None:
        self.hass = hass
        self._spacing_seconds = max(0.0, float(spacing_seconds))
        self._command_timeout_seconds = max(1.0, float(command_timeout_seconds))
        self._owner_id = str(owner_id or "unknown")
        self._condition = asyncio.Condition()
        self._heap: list[_QueuedCommand] = []
        self._pending: dict[tuple[str, str], _QueuedCommand] = {}
        self._sequence = 0
        self._worker: asyncio.Task[None] | None = None
        self._closing = False
        self._last_call_monotonic: float | None = None
        self._active: _QueuedCommand | None = None
        self._completed = 0
        self._failed = 0
        self._superseded = 0
        self._skipped = 0
        self._last_result: CommandResult | None = None
        self._listeners: set[Callable[[], None]] = set()

    def async_add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Register a synchronous queue-state listener."""
        self._listeners.add(listener)

        def remove() -> None:
            self._listeners.discard(listener)

        return remove

    def _notify(self) -> None:
        for listener in tuple(self._listeners):
            try:
                listener()
            except Exception:  # A diagnostic listener must never stop the queue.
                _LOGGER.exception("Command queue listener failed")

    async def async_submit(
        self,
        *,
        entity_id: str,
        command_type: str,
        service: str,
        service_data: dict[str, Any] | None = None,
        priority: int = PRIORITY_AUTOMATIC,
        coalesce_key: str | None = None,
        context: Context | None = None,
        is_valid: ValidityCallback | None = None,
        on_started: StartedCallback | None = None,
        on_finished: FinishedCallback | None = None,
    ) -> CommandResult:
        """Queue a command and wait for its provider result."""
        if self._closing:
            return CommandResult(
                success=False,
                entity_id=entity_id,
                command_type=command_type,
                service=service,
                skipped_reason="queue_closed",
            )

        loop = asyncio.get_running_loop()
        future: asyncio.Future[CommandResult] = loop.create_future()
        channel = coalesce_key or command_type
        key = (entity_id, channel)
        requested_priority = int(priority)
        blocked_result: CommandResult | None = None

        async with self._condition:
            # Shutdown may begin after the optimistic check above but before
            # this coroutine acquires the queue lock. Recheck while holding
            # the lock so no command can be added behind a stopped worker.
            if self._closing:
                return CommandResult(
                    success=False,
                    entity_id=entity_id,
                    command_type=command_type,
                    service=service,
                    skipped_reason="queue_closed",
                )
            previous = self._pending.get(key)
            if previous is not None and not previous.started:
                if requested_priority > previous.priority:
                    # A numerically lower value has higher priority. Keep a
                    # queued emergency/safety command authoritative instead of
                    # letting a later ordinary target silently remove it.
                    blocked_result = CommandResult(
                        success=False,
                        entity_id=entity_id,
                        command_type=command_type,
                        service=service,
                        completed_at=dt_util.utcnow(),
                        skipped_reason="higher_priority_pending",
                        superseded=True,
                    )
                    self._superseded += 1
                    self._last_result = blocked_result
                else:
                    self._superseded += 1
                    superseded_result = CommandResult(
                        success=False,
                        entity_id=previous.entity_id,
                        command_type=previous.command_type,
                        service=previous.service,
                        completed_at=dt_util.utcnow(),
                        skipped_reason="superseded",
                        superseded=True,
                    )
                    self._last_result = superseded_result
                    if not previous.future.done():
                        previous.future.set_result(superseded_result)

            if blocked_result is None:
                self._sequence += 1
                item = _QueuedCommand(
                    priority=requested_priority,
                    sequence=self._sequence,
                    entity_id=entity_id,
                    command_type=command_type,
                    service=service,
                    service_data=dict(service_data or {}),
                    coalesce_key=channel,
                    context=context or Context(),
                    future=future,
                    is_valid=is_valid,
                    on_started=on_started,
                    on_finished=on_finished,
                )
                self._pending[key] = item
                heapq.heappush(self._heap, item)
                self._ensure_worker_locked()
                self._condition.notify()
        self._notify()

        if blocked_result is not None:
            return blocked_result

        try:
            return await future
        except asyncio.CancelledError:
            async with self._condition:
                if self._pending.get(key) is item and not item.started:
                    self._pending.pop(key, None)
            self._notify()
            raise

    def snapshot(self) -> dict[str, Any]:
        """Return a compact queue state for diagnostics and entities."""
        active = self._active
        last = self._last_result
        return {
            "busy": active is not None or bool(self._pending),
            "depth": len(self._pending),
            "active": (
                {
                    "entity_id": active.entity_id,
                    "command_type": active.command_type,
                    "service": active.service,
                    "priority": active.priority,
                }
                if active is not None
                else None
            ),
            "completed": self._completed,
            "failed": self._failed,
            "superseded": self._superseded,
            "skipped": self._skipped,
            "last_result": (
                {
                    "success": last.success,
                    "entity_id": last.entity_id,
                    "command_type": last.command_type,
                    "service": last.service,
                    "issued_at": last.issued_at.isoformat() if last.issued_at else None,
                    "completed_at": (
                        last.completed_at.isoformat() if last.completed_at else None
                    ),
                    "error": type(last.error).__name__ if last.error else None,
                    "skipped_reason": last.skipped_reason,
                    "superseded": last.superseded,
                }
                if last is not None
                else None
            ),
        }

    async def async_shutdown(self) -> None:
        """Stop the worker and resolve any queued callers safely."""
        self._closing = True
        async with self._condition:
            for item in self._pending.values():
                if not item.future.done():
                    item.future.set_result(
                        CommandResult(
                            success=False,
                            entity_id=item.entity_id,
                            command_type=item.command_type,
                            service=item.service,
                            completed_at=dt_util.utcnow(),
                            skipped_reason="queue_closed",
                        )
                    )
            self._pending.clear()
            self._heap.clear()
            self._condition.notify_all()
        self._notify()
        active = self._active
        if self._worker is not None:
            self._worker.cancel()
            try:
                await self._worker
            except asyncio.CancelledError:
                pass
            self._worker = None
        if active is not None and not active.finished:
            result = CommandResult(
                success=False,
                entity_id=active.entity_id,
                command_type=active.command_type,
                service=active.service,
                issued_at=active.issued_at,
                completed_at=dt_util.utcnow(),
                context_id=active.context.id if active.started else None,
                skipped_reason="queue_closed",
            )
            self._finish_item(active, result)
        self._active = None
        self._listeners.clear()

    def _ensure_worker_locked(self) -> None:
        if self._worker is None or self._worker.done():
            self._worker = self.hass.async_create_background_task(
                self._async_worker(),
                f"Smart Shading Control command queue ({self._owner_id})",
            )

    async def _async_worker(self) -> None:
        while not self._closing:
            await self._async_wait_for_spacing()
            item = await self._async_next_item()
            if item is None:
                return
            await self._async_execute(item)

    async def _async_wait_for_spacing(self) -> None:
        """Wait before selecting the next item so new safety work can preempt."""
        if self._last_call_monotonic is None:
            return
        remaining = self._spacing_seconds - (monotonic() - self._last_call_monotonic)
        if remaining > 0:
            await asyncio.sleep(remaining)

    async def _async_next_item(self) -> _QueuedCommand | None:
        async with self._condition:
            while not self._closing:
                while self._heap:
                    candidate = heapq.heappop(self._heap)
                    key = (candidate.entity_id, candidate.coalesce_key)
                    if self._pending.get(key) is not candidate:
                        continue
                    return candidate
                await self._condition.wait()
        return None

    async def _async_execute(self, item: _QueuedCommand) -> None:
        if item.future.done():
            key = (item.entity_id, item.coalesce_key)
            async with self._condition:
                if self._pending.get(key) is item:
                    self._pending.pop(key, None)
            self._notify()
            return
        if item.is_valid is not None:
            try:
                valid = item.is_valid()
            except Exception:  # A validation bug must not strand the caller.
                _LOGGER.exception(
                    "Command validity callback failed for %s", item.entity_id
                )
                await self._async_finish_skipped(item, "validation_error")
                return
            if not valid:
                await self._async_finish_skipped(item, "obsolete")
                return

        key = (item.entity_id, item.coalesce_key)
        async with self._condition:
            # The item may have been replaced after it was selected but before
            # the provider call started. In that case the newer target wins.
            if self._pending.get(key) is not item or item.future.done():
                return
            self._pending.pop(key, None)
            item.started = True
            self._active = item

        issued_at = dt_util.utcnow()
        item.issued_at = issued_at
        if item.on_started is not None:
            try:
                item.on_started(item.context, issued_at)
            except Exception as err:
                _LOGGER.exception(
                    "Command start callback failed for %s", item.entity_id
                )
                self._failed += 1
                result = CommandResult(
                    success=False,
                    entity_id=item.entity_id,
                    command_type=item.command_type,
                    service=item.service,
                    issued_at=issued_at,
                    completed_at=dt_util.utcnow(),
                    context_id=item.context.id,
                    error=err,
                    skipped_reason="start_callback_error",
                )
                self._finish_item(item, result)
                self._active = None
                self._notify()
                return

        self._notify()
        try:
            async with asyncio.timeout(self._command_timeout_seconds):
                await self.hass.services.async_call(
                    "cover",
                    item.service,
                    item.service_data,
                    target={ATTR_ENTITY_ID: item.entity_id},
                    blocking=True,
                    context=item.context,
                )
        except asyncio.CancelledError:
            self._last_call_monotonic = monotonic()
            result = CommandResult(
                success=False,
                entity_id=item.entity_id,
                command_type=item.command_type,
                service=item.service,
                issued_at=issued_at,
                completed_at=dt_util.utcnow(),
                context_id=item.context.id,
                skipped_reason=(
                    "queue_closed" if self._closing else "worker_cancelled"
                ),
            )
            self._finish_item(item, result)
            raise
        except Exception as err:  # noqa: BLE001
            self._last_call_monotonic = monotonic()
            self._failed += 1
            result = CommandResult(
                success=False,
                entity_id=item.entity_id,
                command_type=item.command_type,
                service=item.service,
                issued_at=issued_at,
                completed_at=dt_util.utcnow(),
                context_id=item.context.id,
                error=err,
            )
        else:
            self._last_call_monotonic = monotonic()
            self._completed += 1
            result = CommandResult(
                success=True,
                entity_id=item.entity_id,
                command_type=item.command_type,
                service=item.service,
                issued_at=issued_at,
                completed_at=dt_util.utcnow(),
                context_id=item.context.id,
            )
        finally:
            if "result" in locals():
                self._finish_item(item, result)
            self._active = None
            self._notify()

    def _finish_item(self, item: _QueuedCommand, result: CommandResult) -> None:
        """Finalize a started item even when its submitter was cancelled."""
        if item.finished:
            return
        item.finished = True
        self._last_result = result
        if item.on_finished is not None:
            try:
                item.on_finished(result)
            except Exception:  # Completion cleanup must not strand the queue.
                _LOGGER.exception(
                    "Command completion callback failed for %s", item.entity_id
                )
        if not item.future.done():
            item.future.set_result(result)

    async def _async_finish_skipped(self, item: _QueuedCommand, reason: str) -> None:
        key = (item.entity_id, item.coalesce_key)
        async with self._condition:
            if self._pending.get(key) is item:
                self._pending.pop(key, None)
        self._finish_skipped(item, reason)

    def _finish_skipped(self, item: _QueuedCommand, reason: str) -> None:
        self._skipped += 1
        result = CommandResult(
            success=False,
            entity_id=item.entity_id,
            command_type=item.command_type,
            service=item.service,
            completed_at=dt_util.utcnow(),
            skipped_reason=reason,
        )
        self._last_result = result
        if not item.future.done():
            item.future.set_result(result)
        self._notify()


def get_command_queue(hass: HomeAssistant, owner_id: str) -> SmartShadingCommandQueue:
    """Return the independent command queue for one room controller.

    Each room owns its own worker. A slow or failing provider command in one
    room therefore cannot block, supersede or otherwise delay commands that
    belong to another room. Covers are already exclusively claimed per room.
    """
    runtime = hass.data.setdefault(DOMAIN, {})
    queues = runtime.setdefault(COMMAND_QUEUES_KEY, {})
    if not isinstance(queues, dict):
        queues = {}
        runtime[COMMAND_QUEUES_KEY] = queues
    queue = queues.get(owner_id)
    if not isinstance(queue, SmartShadingCommandQueue) or queue._closing:
        queue = SmartShadingCommandQueue(hass, owner_id=owner_id)
        queues[owner_id] = queue
    return queue


async def async_shutdown_command_queue(hass: HomeAssistant, owner_id: str) -> None:
    """Shut down and remove one room-owned command queue."""
    runtime = hass.data.get(DOMAIN)
    if not isinstance(runtime, dict):
        return
    queues = runtime.get(COMMAND_QUEUES_KEY)
    if not isinstance(queues, dict):
        return
    queue = queues.pop(owner_id, None)
    if isinstance(queue, SmartShadingCommandQueue):
        await queue.async_shutdown()
    if not queues:
        runtime.pop(COMMAND_QUEUES_KEY, None)
