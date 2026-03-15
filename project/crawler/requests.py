"""Request metadata assembly for crawl execution."""

from __future__ import annotations

from dataclasses import dataclass

from project.api.schemas import CrawlRequest, RenderMode
from project.crawler.rendering import RenderDecisionEngine


@dataclass(slots=True)
class CrawlRequestPlan:
    url: str
    render_mode: RenderMode
    use_playwright: bool
    meta: dict[str, object]


class RequestPlanner:
    """Plans HTTP-first requests with optional render retries."""

    def __init__(self, decision_engine: RenderDecisionEngine | None = None) -> None:
        self.decision_engine = decision_engine or RenderDecisionEngine()

    def build_initial_request(self, crawl_request: CrawlRequest) -> CrawlRequestPlan:
        use_playwright = crawl_request.render_mode is RenderMode.ALWAYS
        meta = {
            "render_mode": crawl_request.render_mode.value,
            "playwright": use_playwright,
        }
        return CrawlRequestPlan(
            url=crawl_request.url,
            render_mode=crawl_request.render_mode,
            use_playwright=use_playwright,
            meta=meta,
        )

    def maybe_schedule_render_retry(
        self,
        crawl_request: CrawlRequest,
        response_html: str,
    ) -> CrawlRequestPlan | None:
        should_render = self.decision_engine.should_render(
            render_mode=crawl_request.render_mode,
            html=response_html,
        )
        if not should_render:
            return None
        return CrawlRequestPlan(
            url=crawl_request.url,
            render_mode=crawl_request.render_mode,
            use_playwright=True,
            meta={
                "render_mode": crawl_request.render_mode.value,
                "playwright": True,
                "render_retry": True,
            },
        )
