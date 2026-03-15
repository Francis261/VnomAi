"""Heuristic content extractor with section-aware output and deduplication."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urlsplit, urlunsplit

_BLOCK_TAGS = {"p", "li", "blockquote", "pre", "td", "section", "article", "main", "div"}
_HEADING_TAGS = {"h1", "h2", "h3"}
_NON_CONTENT_TAGS = {"script", "style", "noscript", "svg", "canvas", "template"}


@dataclass(slots=True)
class ContentBlock:
    """One heading section and its associated text."""

    heading: str
    level: int
    content: str


@dataclass(slots=True)
class ExtractedPage:
    """Normalized extracted output for downstream indexing."""

    source_url: str
    canonical_url: str
    content: str
    sections: list[ContentBlock]
    metadata: dict[str, object]


class _HTMLContentParser(HTMLParser):
    """Collect headings, block text and canonical URL from HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.canonical_url: str | None = None
        self._ignored_depth = 0
        self._stack: list[str] = []
        self._active_heading: tuple[int, list[str]] | None = None
        self._active_block: list[str] = []
        self._current_section: dict[str, object] = {"heading": "Introduction", "level": 1, "parts": []}
        self.sections: list[dict[str, object]] = [self._current_section]
        self.blocks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        self._stack.append(tag)
        if tag in _NON_CONTENT_TAGS:
            self._ignored_depth += 1
            return
        if tag == "link":
            attrs_map = {key.lower(): (value or "") for key, value in attrs}
            if attrs_map.get("rel", "").lower() == "canonical" and attrs_map.get("href"):
                self.canonical_url = attrs_map["href"].strip()
            return
        if self._ignored_depth > 0:
            return
        if tag in _HEADING_TAGS:
            self._flush_active_block()
            self._active_heading = (int(tag[1]), [])
        elif tag in _BLOCK_TAGS:
            self._active_block = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self._stack:
            self._stack.pop()
        if tag in _NON_CONTENT_TAGS:
            self._ignored_depth = max(0, self._ignored_depth - 1)
            return
        if self._ignored_depth > 0:
            return
        if tag in _HEADING_TAGS and self._active_heading is not None:
            level, parts = self._active_heading
            heading = _normalize_whitespace("".join(parts)) or f"Section {len(self.sections) + 1}"
            self._current_section = {"heading": heading, "level": level, "parts": []}
            self.sections.append(self._current_section)
            self._active_heading = None
        if tag in _BLOCK_TAGS:
            self._flush_active_block()

    def handle_data(self, data: str) -> None:
        if self._ignored_depth > 0:
            return
        text = _normalize_whitespace(data)
        if not text:
            return
        if self._active_heading is not None:
            self._active_heading[1].append(text + " ")
            return
        if self._active_block is not None:
            self._active_block.append(text + " ")

    def close(self) -> None:
        self._flush_active_block()
        super().close()

    def _flush_active_block(self) -> None:
        if not self._active_block:
            return
        text = _normalize_whitespace("".join(self._active_block))
        self._active_block = []
        if len(text) < 25:
            return
        self.blocks.append(text)
        parts = self._current_section.setdefault("parts", [])
        if isinstance(parts, list):
            parts.append(text)


class ContentExtractor:
    """Extract main page content with fallback heuristics and deduplication."""

    def __init__(self, near_duplicate_distance: int = 3) -> None:
        self._known_urls: set[str] = set()
        self._known_hashes: set[str] = set()
        self._known_simhashes: list[int] = []
        self._near_duplicate_distance = near_duplicate_distance

    def extract(self, url: str, html: str) -> ExtractedPage | None:
        parser = _HTMLContentParser()
        parser.feed(html)
        parser.close()

        canonical_url = self._normalize_canonical(url, parser.canonical_url)
        if canonical_url in self._known_urls:
            return None

        primary_sections = self._build_sections(parser.sections)
        primary_text = "\n\n".join(block.content for block in primary_sections if block.content)

        fallback_sections = self._fallback_extract(html)
        fallback_text = "\n\n".join(block.content for block in fallback_sections if block.content)

        selected_sections, selected_text, confidence = self._select_best_extraction(
            primary_sections,
            primary_text,
            fallback_sections,
            fallback_text,
        )

        content_hash = _content_hash(selected_text)
        simhash = _simhash(selected_text)
        if content_hash in self._known_hashes:
            return None
        if any(_hamming_distance(simhash, seen) <= self._near_duplicate_distance for seen in self._known_simhashes):
            return None

        self._known_urls.add(canonical_url)
        self._known_hashes.add(content_hash)
        self._known_simhashes.append(simhash)

        metadata: dict[str, object] = {
            "content_hash": content_hash,
            "simhash": f"{simhash:016x}",
            "extraction_confidence": round(confidence, 3),
            "extraction_strategy": "fallback" if selected_sections is fallback_sections else "structured",
            "canonical_url_source": "link" if parser.canonical_url else "normalized_source",
        }
        return ExtractedPage(
            source_url=url,
            canonical_url=canonical_url,
            content=selected_text,
            sections=selected_sections,
            metadata=metadata,
        )

    def _normalize_canonical(self, source_url: str, canonical_url: str | None) -> str:
        target = canonical_url.strip() if canonical_url else source_url
        parts = urlsplit(target)
        normalized_path = re.sub(r"/+", "/", parts.path or "/")
        if normalized_path != "/" and normalized_path.endswith("/"):
            normalized_path = normalized_path[:-1]
        return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), normalized_path, "", ""))

    def _build_sections(self, raw_sections: list[dict[str, object]]) -> list[ContentBlock]:
        sections: list[ContentBlock] = []
        for section in raw_sections:
            heading = str(section.get("heading") or "Introduction")
            level = int(section.get("level") or 1)
            parts = section.get("parts")
            text_parts = [p for p in parts if isinstance(p, str)] if isinstance(parts, list) else []
            content = "\n".join(text_parts).strip()
            if content:
                sections.append(ContentBlock(heading=heading, level=max(1, min(3, level)), content=content))
        return sections

    def _fallback_extract(self, html: str) -> list[ContentBlock]:
        cleaned = re.sub(r"<\s*(script|style|noscript)[^>]*>.*?<\s*/\s*\1\s*>", " ", html, flags=re.I | re.S)
        candidates = re.findall(r"<(p|li|blockquote|pre|h1|h2|h3)[^>]*>(.*?)</\1>", cleaned, flags=re.I | re.S)
        sections: list[ContentBlock] = []
        current_heading = "Introduction"
        current_level = 1
        current_parts: list[str] = []

        def flush() -> None:
            nonlocal current_parts
            body = "\n".join(current_parts).strip()
            if body:
                sections.append(ContentBlock(heading=current_heading, level=current_level, content=body))
            current_parts = []

        for tag, inner in candidates:
            text = _normalize_whitespace(_strip_tags(inner))
            if not text:
                continue
            tag = tag.lower()
            if tag in _HEADING_TAGS:
                flush()
                current_heading = text
                current_level = int(tag[1])
            elif len(text) >= 30:
                current_parts.append(text)

        flush()
        return sections

    def _select_best_extraction(
        self,
        primary_sections: list[ContentBlock],
        primary_text: str,
        fallback_sections: list[ContentBlock],
        fallback_text: str,
    ) -> tuple[list[ContentBlock], str, float]:
        primary_score = self._confidence(primary_sections, primary_text)
        fallback_score = self._confidence(fallback_sections, fallback_text)
        if fallback_score > primary_score + 0.1:
            return fallback_sections, fallback_text, fallback_score
        return primary_sections, primary_text, primary_score

    def _confidence(self, sections: list[ContentBlock], text: str) -> float:
        words = len(re.findall(r"\w+", text))
        if words == 0:
            return 0.0
        section_bonus = min(len(sections) / 6.0, 0.2)
        avg_block_words = (words / max(1, len(sections))) / 220.0
        density = min(avg_block_words, 0.5)
        punctuation_density = min(len(re.findall(r"[\.!?]", text)) / max(1, words / 15), 1.0)
        return max(0.0, min(1.0, 0.25 + section_bonus + density + 0.25 * punctuation_density))


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", unescape(text or "")).strip()


def _strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text)


def _content_hash(text: str) -> str:
    normalized = _normalize_whitespace(text).lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _simhash(text: str, bits: int = 64) -> int:
    tokens = re.findall(r"\w+", text.lower())
    if not tokens:
        return 0
    weights = [0] * bits
    for token in tokens:
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        value = int.from_bytes(digest, "big")
        for bit in range(bits):
            if value & (1 << bit):
                weights[bit] += 1
            else:
                weights[bit] -= 1
    result = 0
    for bit, weight in enumerate(weights):
        if weight >= 0:
            result |= 1 << bit
    return result


def _hamming_distance(first: int, second: int) -> int:
    return (first ^ second).bit_count()
