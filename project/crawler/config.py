"""Crawler configuration including optional rendering path."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class RenderBackpressureLimits:
    """Limits for browser-rendered requests to protect crawl throughput."""

    max_inflight_rendered: int = 4
    max_pending_rendered: int = 32


@dataclass(slots=True)
class CrawlerConfig:
    """Core crawler config with HTTP-first defaults."""

    use_scrapy_playwright: bool = False
    playwright_download_handler: str = "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler"
    backpressure: RenderBackpressureLimits = field(default_factory=RenderBackpressureLimits)

    def scrapy_settings(self) -> dict[str, object]:
        """Build Scrapy settings while keeping plain HTTP as default path."""
        settings: dict[str, object] = {
            "CONCURRENT_REQUESTS": 32,
            "DOWNLOAD_HANDLERS": {},
            "DOWNLOADER_MIDDLEWARES": {},
            "PLAYWRIGHT_MAX_PAGES_PER_CONTEXT": self.backpressure.max_inflight_rendered,
        }
        if self.use_scrapy_playwright:
            settings["DOWNLOAD_HANDLERS"] = {
                "http": self.playwright_download_handler,
                "https": self.playwright_download_handler,
            }
            settings["DOWNLOADER_MIDDLEWARES"] = {
                "scrapy_playwright.middleware.ScrapyPlaywrightDownloaderMiddleware": 543,
            }
        return settings
