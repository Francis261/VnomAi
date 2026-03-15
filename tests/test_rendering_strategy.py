from project.api.schemas import CrawlRequest, CrawlStatus, RenderMode
from project.crawler.backpressure import RenderBackpressureController
from project.crawler.config import CrawlerConfig, RenderBackpressureLimits
from project.crawler.rendering import RenderDecisionEngine
from project.crawler.requests import RequestPlanner
from project.crawler.status import CrawlStatusTracker


def test_render_mode_flag_defaults_to_auto():
    request = CrawlRequest(url="https://example.com")
    assert request.render_mode is RenderMode.AUTO


def test_auto_mode_retries_only_for_empty_shell():
    planner = RequestPlanner()
    request = CrawlRequest(url="https://example.com", render_mode=RenderMode.AUTO)

    shell_html = '<html><body><div id="root">Loading...</div><noscript>enable javascript</noscript></body></html>'
    rich_html = "<html><body><main><article><p>" + ("content " * 50) + "</p></article></main></body></html>"

    plan = planner.maybe_schedule_render_retry(request, shell_html)
    assert plan is not None
    assert plan.use_playwright is True
    assert planner.maybe_schedule_render_retry(request, rich_html) is None


def test_scrapy_defaults_to_http_and_can_enable_playwright():
    default_settings = CrawlerConfig(use_scrapy_playwright=False).scrapy_settings()
    assert default_settings["DOWNLOAD_HANDLERS"] == {}

    pw_settings = CrawlerConfig(use_scrapy_playwright=True).scrapy_settings()
    assert "http" in pw_settings["DOWNLOAD_HANDLERS"]


def test_backpressure_limits_are_enforced_for_render_retries():
    limits = RenderBackpressureLimits(max_inflight_rendered=1, max_pending_rendered=1)
    controller = RenderBackpressureController(limits)
    planner = RequestPlanner(backpressure=controller)

    request = CrawlRequest(url="https://example.com", render_mode=RenderMode.AUTO)
    shell_html = '<html><body><div id="root">Loading...</div><noscript>enable javascript</noscript></body></html>'

    first_plan = planner.maybe_schedule_render_retry(request, shell_html)
    assert first_plan is not None
    assert first_plan.use_playwright is True

    second_plan = planner.maybe_schedule_render_retry(request, shell_html)
    assert second_plan is not None
    assert second_plan.use_playwright is False
    assert second_plan.meta["render_reason"] == "render_inflight_limit"

    assert controller.inflight == 1
    planner.complete_render(first_plan)
    assert controller.inflight == 0


def test_render_usage_stats_are_tracked():
    tracker = CrawlStatusTracker(CrawlStatus(crawl_id="c1"))
    tracker.mark_rendered()
    tracker.mark_render_failure()

    assert tracker.status.rendered_pages == 1
    assert tracker.status.render_failures == 1


def test_decision_engine_always_and_off_modes():
    engine = RenderDecisionEngine()
    assert engine.should_render(RenderMode.ALWAYS, html=None) is True
    assert engine.should_render(RenderMode.OFF, html="<html></html>") is False


def test_always_mode_uses_playwright_when_capacity_exists():
    limits = RenderBackpressureLimits(max_inflight_rendered=1, max_pending_rendered=1)
    controller = RenderBackpressureController(limits)
    planner = RequestPlanner(backpressure=controller)

    request = CrawlRequest(url="https://example.com", render_mode=RenderMode.ALWAYS)
    plan = planner.build_initial_request(request)

    assert plan.use_playwright is True
    assert plan.render_token is not None
