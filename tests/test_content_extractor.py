from project.extractor import ContentExtractor


def test_extracts_structured_sections_and_metadata():
    extractor = ContentExtractor()
    html = """
    <html>
      <head>
        <link rel='canonical' href='https://example.com/article?id=123#top' />
      </head>
      <body>
        <h1>Headline</h1>
        <p>This is the lead paragraph with enough descriptive text to be retained for indexing.</p>
        <h2>Details</h2>
        <p>Extra context explains implementation specifics and edge-case handling for robustness.</p>
        <h3>Notes</h3>
        <p>Short but useful note with punctuation.</p>
      </body>
    </html>
    """

    extracted = extractor.extract("https://example.com/article/?utm=1", html)

    assert extracted is not None
    assert extracted.canonical_url == "https://example.com/article"
    assert [section.heading for section in extracted.sections] == ["Headline", "Details", "Notes"]
    assert [section.level for section in extracted.sections] == [1, 2, 3]
    assert 0.0 < float(extracted.metadata["extraction_confidence"]) <= 1.0
    assert extracted.metadata["canonical_url_source"] == "link"


def test_uses_fallback_extraction_when_parser_loses_structure():
    extractor = ContentExtractor()
    html = (
        "<html><body><div><h1>Guide</h1><div><p>"
        + ("readability style text " * 40)
        + "</p></div></div></body></html>"
    )

    extracted = extractor.extract("https://example.com/guide", html)

    assert extracted is not None
    assert extracted.metadata["extraction_strategy"] in {"structured", "fallback"}
    assert "readability style text" in extracted.content


def test_skips_duplicate_by_canonical_and_near_duplicate_content():
    extractor = ContentExtractor(near_duplicate_distance=8)
    first_html = """
    <html><head><link rel='canonical' href='https://example.com/post' /></head>
    <body><h1>Post</h1><p>This page explains retrieval augmented generation with practical caveats.</p></body></html>
    """
    second_html = """
    <html><body><h1>Same</h1><p>This page explains retrieval augmented generation with practical caveat.</p></body></html>
    """

    first = extractor.extract("https://example.com/post?ref=home", first_html)
    second = extractor.extract("https://example.com/post#anchor", second_html)
    third = extractor.extract("https://example.com/another", second_html)

    assert first is not None
    assert second is None
    assert third is None
