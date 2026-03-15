"""Crawl status accounting utilities."""

from __future__ import annotations

from dataclasses import replace

from project.api.schemas import CrawlStatus


class CrawlStatusTracker:
    """Mutates crawl status counters as crawl events complete."""

    def __init__(self, status: CrawlStatus) -> None:
        self.status = status

    def mark_rendered(self) -> CrawlStatus:
        self.status = replace(self.status, rendered_pages=self.status.rendered_pages + 1)
        return self.status

    def mark_render_failure(self) -> CrawlStatus:
        self.status = replace(self.status, render_failures=self.status.render_failures + 1)
        return self.status

    def mark_crawled(self) -> CrawlStatus:
        self.status = replace(self.status, crawled_pages=self.status.crawled_pages + 1)
        return self.status

    def mark_failed(self) -> CrawlStatus:
        self.status = replace(self.status, failed_pages=self.status.failed_pages + 1)
        return self.status
