"""Request metadata assembly for crawl execution."""

from __future__ import annotations

from dataclasses import dataclass

from project.api.schemas import CrawlRequest, RenderMode
from project.crawler.backpressure import RenderBackpressureController, RenderRequestToken
from project.crawler.rendering import RenderDecisionEngine


@dataclass(slots=True)
class CrawlRequestPlan:
    url: str
    render_mode: RenderMode
    use_playwright: bool
    meta: dict[str, object]
    render_token: RenderRequestToken | None = None


class RequestPlanner:
    """Plans HTTP-first requests with optional render retries and backpressure."""

    def __init__(
        self,
        decision_engine: RenderDecisionEngine | None = None,
        backpressure: RenderBackpressureController | None = None,
    ) -> None:
        self.decision_engine = decision_engine or RenderDecisionEngine()
        self.backpressure = backpressure

    def build_initial_request(self, crawl_request: CrawlRequest) -> CrawlRequestPlan:
        use_playwright = crawl_request.render_mode is RenderMode.ALWAYS
        token: RenderRequestToken | None = None

        if use_playwright and self.backpressure is not None:
            request_id = self._request_id(crawl_request, suffix="always")
            if not self.backpressure.enqueue(request_id):
                return CrawlRequestPlan(
                    url=crawl_request.url,
                    render_mode=crawl_request.render_mode,
                    use_playwright=False,
                    meta={
                        "render_mode": crawl_request.render_mode.value,
                        "playwright": False,
                        "render_deferred": True,
                        "render_reason": "render_queue_full",
                    },
                )
            token = self.backpressure.acquire_next()
            use_playwright = token is not None

        meta = {
            "render_mode": crawl_request.render_mode.value,
            "playwright": use_playwright,
        }
        if token is None and use_playwright is False and crawl_request.render_mode is RenderMode.ALWAYS:
            meta["render_deferred"] = True

        return CrawlRequestPlan(
            url=crawl_request.url,
            render_mode=crawl_request.render_mode,
            use_playwright=use_playwright,
            meta=meta,
            render_token=token,
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

        token: RenderRequestToken | None = None
        if self.backpressure is not None:
            request_id = self._request_id(crawl_request, suffix="retry")
            if not self.backpressure.enqueue(request_id):
                return CrawlRequestPlan(
                    url=crawl_request.url,
                    render_mode=crawl_request.render_mode,
                    use_playwright=False,
                    meta={
                        "render_mode": crawl_request.render_mode.value,
                        "playwright": False,
                        "render_retry": True,
                        "render_deferred": True,
                        "render_reason": "render_queue_full",
                    },
                )
            token = self.backpressure.acquire_next()
            if token is None:
                return CrawlRequestPlan(
                    url=crawl_request.url,
                    render_mode=crawl_request.render_mode,
                    use_playwright=False,
                    meta={
                        "render_mode": crawl_request.render_mode.value,
                        "playwright": False,
                        "render_retry": True,
                        "render_deferred": True,
                        "render_reason": "render_inflight_limit",
                    },
                )

        return CrawlRequestPlan(
            url=crawl_request.url,
            render_mode=crawl_request.render_mode,
            use_playwright=True,
            meta={
                "render_mode": crawl_request.render_mode.value,
                "playwright": True,
                "render_retry": True,
            },
            render_token=token,
        )

    def complete_render(self, plan: CrawlRequestPlan) -> None:
        """Release backpressure token after rendered request finishes."""
        if self.backpressure is None or plan.render_token is None:
            return
        self.backpressure.release(plan.render_token)

    @staticmethod
    def _request_id(crawl_request: CrawlRequest, suffix: str) -> str:
        return f"{crawl_request.url}::{suffix}"
