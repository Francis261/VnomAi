"""Inverted index with retrieval and ranking stages."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from math import exp, log
import re
from typing import Any
from urllib.parse import urlparse

_TOKEN_RE = re.compile(r"[a-z0-9]+")


@dataclass(slots=True)
class IndexedDocument:
    """Document stored in the index."""

    doc_id: str
    url: str
    title: str = ""
    headings: list[str] | None = None
    content: str = ""
    metadata: dict[str, Any] | None = None


@dataclass(slots=True)
class SearchResult:
    """Single search result."""

    doc_id: str
    score: float
    document: IndexedDocument
    debug: dict[str, float] | None = None


class InvertedIndex:
    """In-memory inverted index with staged retrieval and ranking."""

    def __init__(self, *, bm25_k1: float = 1.5, bm25_b: float = 0.75, recency_half_life_days: float = 30.0) -> None:
        self._docs: dict[str, IndexedDocument] = {}
        self._postings: dict[str, set[str]] = defaultdict(set)
        self._token_freqs: dict[str, Counter[str]] = {}
        self._doc_len: dict[str, int] = {}
        self._avg_doc_len: float = 0.0
        self._bm25_k1 = bm25_k1
        self._bm25_b = bm25_b
        self._recency_half_life_days = recency_half_life_days

    def add_document(self, doc: IndexedDocument) -> None:
        """Add or replace a document in the index."""

        self._docs[doc.doc_id] = doc
        combined_tokens = self._combined_tokens(doc)
        counts = Counter(combined_tokens)
        self._token_freqs[doc.doc_id] = counts
        self._doc_len[doc.doc_id] = len(combined_tokens)
        for token in counts:
            self._postings[token].add(doc.doc_id)
        self._avg_doc_len = (sum(self._doc_len.values()) / len(self._doc_len)) if self._doc_len else 0.0

    def search(self, query: str, *, limit: int = 10, debug: bool = False) -> list[SearchResult]:
        """Search by query with retrieval then ranking stages."""

        query_tokens = _tokenize(query)
        if not query_tokens:
            return []

        candidates = self._retrieve(query_tokens)
        ranked = [self._rank(doc_id, query_tokens, debug=debug) for doc_id in candidates]
        ranked.sort(key=lambda result: result.score, reverse=True)
        return ranked[:limit]

    def search_response(self, query: str, *, limit: int = 10, debug: bool = False) -> dict[str, Any]:
        """Return API-friendly response with optional explainability."""

        results = self.search(query, limit=limit, debug=debug)
        payload: list[dict[str, Any]] = []
        for result in results:
            item: dict[str, Any] = {
                "doc_id": result.doc_id,
                "score": result.score,
                "url": result.document.url,
                "title": result.document.title,
            }
            if debug and result.debug is not None:
                item["debug"] = result.debug
            payload.append(item)
        return {"query": query, "results": payload}

    def _retrieve(self, query_tokens: list[str]) -> set[str]:
        """Retrieve candidate documents for ranking."""

        candidates: set[str] = set()
        for token in query_tokens:
            candidates |= self._postings.get(token, set())
        return candidates

    def _rank(self, doc_id: str, query_tokens: list[str], *, debug: bool) -> SearchResult:
        doc = self._docs[doc_id]
        bm25 = self._bm25_score(doc_id, query_tokens)
        phrase = self._phrase_boost(doc, query_tokens)
        url_boost = self._url_token_boost(doc, query_tokens)
        recency = self._recency_prior(doc)
        authority = self._authority_prior(doc)
        total = bm25 + phrase + url_boost + recency + authority

        components = None
        if debug:
            components = {
                "bm25": bm25,
                "phrase_boost": phrase,
                "url_token_boost": url_boost,
                "recency_prior": recency,
                "authority_prior": authority,
                "total": total,
            }

        return SearchResult(doc_id=doc_id, score=total, document=doc, debug=components)

    def _bm25_score(self, doc_id: str, query_tokens: list[str]) -> float:
        counts = self._token_freqs[doc_id]
        doc_len = self._doc_len[doc_id]
        score = 0.0
        for token in query_tokens:
            tf = counts.get(token, 0)
            if tf == 0:
                continue
            df = len(self._postings.get(token, ()))
            if df == 0:
                continue
            n_docs = len(self._docs)
            idf = log(1 + ((n_docs - df + 0.5) / (df + 0.5)))
            denom = tf + self._bm25_k1 * (1 - self._bm25_b + self._bm25_b * (doc_len / max(self._avg_doc_len, 1.0)))
            score += idf * ((tf * (self._bm25_k1 + 1)) / denom)
        return score

    def _phrase_boost(self, doc: IndexedDocument, query_tokens: list[str]) -> float:
        if len(query_tokens) < 2:
            return 0.0

        fields = {
            "title": _tokenize(doc.title),
            "headings": _tokenize(" ".join(doc.headings or [])),
            "content": _tokenize(doc.content),
        }
        weights = {"title": 1.2, "headings": 0.8, "content": 0.4}
        boost = 0.0

        query_pairs = list(zip(query_tokens, query_tokens[1:]))
        for left, right in query_pairs:
            for name, tokens in fields.items():
                if _contains_adjacent_pair(tokens, left, right):
                    boost += weights[name]
        return boost

    def _url_token_boost(self, doc: IndexedDocument, query_tokens: list[str]) -> float:
        url_tokens = _tokenize(_url_slug_and_path(doc.url))
        if not url_tokens:
            return 0.0
        overlap = len(set(query_tokens) & set(url_tokens))
        return overlap * 0.25

    def _recency_prior(self, doc: IndexedDocument) -> float:
        if not doc.metadata:
            return 0.0
        crawled_at = doc.metadata.get("crawled_at")
        if not crawled_at:
            return 0.0
        parsed = _parse_datetime(crawled_at)
        if not parsed:
            return 0.0
        age_days = max((datetime.now(UTC) - parsed).total_seconds() / 86400.0, 0.0)
        decay = exp(-log(2) * (age_days / self._recency_half_life_days))
        return 0.6 * decay

    def _authority_prior(self, doc: IndexedDocument) -> float:
        if not doc.metadata:
            return 0.0
        score = doc.metadata.get("host_score", 0.0)
        if not isinstance(score, int | float):
            return 0.0
        return max(min(float(score), 1.0), 0.0) * 0.5

    def _combined_tokens(self, doc: IndexedDocument) -> list[str]:
        body = " ".join(filter(None, [doc.title, " ".join(doc.headings or []), doc.content]))
        return _tokenize(body)


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _contains_adjacent_pair(tokens: list[str], left: str, right: str) -> bool:
    return any(tokens[idx] == left and tokens[idx + 1] == right for idx in range(len(tokens) - 1))


def _url_slug_and_path(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.netloc} {parsed.path}"


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        normalized = value.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(normalized)
        except ValueError:
            return None
    else:
        return None

    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)
