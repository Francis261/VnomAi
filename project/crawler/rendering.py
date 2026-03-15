"""Rendering strategy helpers for Scrapy + optional Playwright."""

from __future__ import annotations

from dataclasses import dataclass

from project.api.schemas import RenderMode


@dataclass(slots=True)
class HtmlQualityHeuristics:
    """Simple heuristics to detect client-side rendered empty shells."""

    min_text_length: int = 120
    min_body_tags: int = 3

    def is_empty_shell(self, html: str) -> bool:
        content = html.lower()
        text_length = len("".join(ch for ch in html if ch.isalnum() or ch.isspace()).strip())
        body_tag_hits = content.count("<p") + content.count("<article") + content.count("<main")

        shell_markers = (
            "id=\"root\"",
            "id=\"app\"",
            "data-reactroot",
            "<noscript",
            "loading...",
            "enable javascript",
        )
        marker_hits = sum(1 for marker in shell_markers if marker in content)

        return (
            text_length < self.min_text_length
            or body_tag_hits < self.min_body_tags
            or marker_hits >= 2
        )


class RenderDecisionEngine:
    """Determines whether a request should be rendered."""

    def __init__(self, heuristics: HtmlQualityHeuristics | None = None) -> None:
        self.heuristics = heuristics or HtmlQualityHeuristics()

    def should_render(self, render_mode: RenderMode, html: str | None = None) -> bool:
        if render_mode is RenderMode.OFF:
            return False
        if render_mode is RenderMode.ALWAYS:
            return True
        if html is None:
            # AUTO mode defaults to plain HTTP first.
            return False
        return self.heuristics.is_empty_shell(html)
