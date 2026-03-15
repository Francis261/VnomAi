"""API request and response schemas for crawl jobs."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class RenderMode(str, Enum):
    """Controls how aggressively JS rendering is used per request."""

    OFF = "off"
    AUTO = "auto"
    ALWAYS = "always"


@dataclass(slots=True)
class CrawlRequest:
    """Incoming crawl request payload."""

    url: str
    max_pages: int = 100
    render_mode: RenderMode = RenderMode.AUTO
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CrawlStatus:
    """Current crawl progress and quality counters."""

    crawl_id: str
    queued_pages: int = 0
    crawled_pages: int = 0
    failed_pages: int = 0
    rendered_pages: int = 0
    render_failures: int = 0
