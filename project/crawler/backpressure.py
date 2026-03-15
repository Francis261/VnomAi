"""Backpressure controls for rendered crawling."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from project.crawler.config import RenderBackpressureLimits


@dataclass(slots=True)
class RenderRequestToken:
    request_id: str


class RenderBackpressureController:
    """Tracks inflight and queued rendered requests."""

    def __init__(self, limits: RenderBackpressureLimits) -> None:
        self.limits = limits
        self._inflight: set[str] = set()
        self._pending: deque[str] = deque()

    @property
    def inflight(self) -> int:
        return len(self._inflight)

    @property
    def pending(self) -> int:
        return len(self._pending)

    def enqueue(self, request_id: str) -> bool:
        if self.pending >= self.limits.max_pending_rendered:
            return False
        self._pending.append(request_id)
        return True

    def acquire_next(self) -> RenderRequestToken | None:
        if self.inflight >= self.limits.max_inflight_rendered:
            return None
        if not self._pending:
            return None
        request_id = self._pending.popleft()
        self._inflight.add(request_id)
        return RenderRequestToken(request_id=request_id)

    def release(self, token: RenderRequestToken) -> None:
        self._inflight.discard(token.request_id)
