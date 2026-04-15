"""LiveEventBus — shared in-process pub/sub for session events.

Both the Telegram handler and the Web API handler run in the same asyncio
event loop. This bus lets the Telegram handler publish live tool/text events
that Web SSE subscribers can consume in real time — no Redis needed.
"""

import asyncio
from typing import Any

import structlog

logger = structlog.get_logger()

_MAX_QUEUE_SIZE = 256  # drop events if subscriber can't keep up


class LiveEventBus:
    """Per-session broadcast bus backed by asyncio.Queue."""

    def __init__(self):
        # session_id → list of subscriber queues
        self._subs: dict[str, list[asyncio.Queue]] = {}

    def subscribe(self, session_id: str) -> asyncio.Queue:
        """Register a new subscriber for a session. Returns its event queue."""
        q: asyncio.Queue = asyncio.Queue(maxsize=_MAX_QUEUE_SIZE)
        self._subs.setdefault(session_id, []).append(q)
        logger.debug("Bus: subscriber added", session_id=session_id,
                     total=len(self._subs[session_id]))
        return q

    def unsubscribe(self, session_id: str, q: asyncio.Queue) -> None:
        """Remove a subscriber queue."""
        subs = self._subs.get(session_id, [])
        try:
            subs.remove(q)
        except ValueError:
            pass
        if not subs:
            self._subs.pop(session_id, None)
        logger.debug("Bus: subscriber removed", session_id=session_id)

    async def publish(self, session_id: str, event: dict[str, Any]) -> None:
        """Broadcast an event to all subscribers of a session."""
        subs = self._subs.get(session_id)
        if not subs:
            return
        for q in list(subs):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning("Bus: queue full, dropping event",
                               session_id=session_id)

    def has_subscribers(self, session_id: str) -> bool:
        return bool(self._subs.get(session_id))


# Global singleton — imported by handlers.py and chat.py
live_bus = LiveEventBus()
