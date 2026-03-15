from __future__ import annotations

from datetime import UTC, datetime, timedelta

from project.search.inverted_index import IndexedDocument, InvertedIndex


def _doc(
    doc_id: str,
    *,
    title: str,
    headings: list[str] | None = None,
    content: str = "",
    url: str = "https://example.com/",
    crawled_at: datetime | None = None,
    host_score: float = 0.0,
) -> IndexedDocument:
    metadata = {"host_score": host_score}
    if crawled_at is not None:
        metadata["crawled_at"] = crawled_at.isoformat()
    return IndexedDocument(
        doc_id=doc_id,
        url=url,
        title=title,
        headings=headings or [],
        content=content,
        metadata=metadata,
    )


def test_bm25_prefers_higher_term_signal():
    index = InvertedIndex()
    index.add_document(_doc("high", title="python python tips", content="python guide"))
    index.add_document(_doc("low", title="python", content="guide"))

    results = index.search("python", debug=True)

    assert results[0].doc_id == "high"
    assert results[0].debug["bm25"] > results[1].debug["bm25"]


def test_phrase_and_url_boost_improve_ranking():
    index = InvertedIndex()
    index.add_document(
        _doc(
            "phrase-url",
            title="machine learning fundamentals",
            headings=["machine learning"],
            content="intro",
            url="https://example.com/guides/machine-learning",
        )
    )
    index.add_document(
        _doc(
            "baseline",
            title="learning about machines",
            content="machine and learning discussed separately",
            url="https://example.com/guides/overview",
        )
    )

    results = index.search("machine learning", debug=True)
    best = results[0]

    assert best.doc_id == "phrase-url"
    assert best.debug["phrase_boost"] > 0
    assert best.debug["url_token_boost"] > 0


def test_recency_and_authority_priors_are_applied():
    now = datetime.now(UTC)
    index = InvertedIndex()
    index.add_document(
        _doc(
            "fresh-authoritative",
            title="vector database",
            content="vector database basics",
            crawled_at=now - timedelta(days=1),
            host_score=1.0,
        )
    )
    index.add_document(
        _doc(
            "stale-low-authority",
            title="vector database",
            content="vector database basics",
            crawled_at=now - timedelta(days=365),
            host_score=0.0,
        )
    )

    results = index.search("vector database", debug=True)

    assert results[0].doc_id == "fresh-authoritative"
    assert results[0].debug["recency_prior"] > results[1].debug["recency_prior"]
    assert results[0].debug["authority_prior"] > results[1].debug["authority_prior"]


def test_search_response_debug_flag_controls_explainability():
    index = InvertedIndex()
    index.add_document(_doc("one", title="search api", content="search api docs"))

    without_debug = index.search_response("search", debug=False)
    with_debug = index.search_response("search", debug=True)

    assert "debug" not in without_debug["results"][0]
    assert "debug" in with_debug["results"][0]
    assert "bm25" in with_debug["results"][0]["debug"]
