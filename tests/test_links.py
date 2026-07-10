from wikimem import WikiLink, parse_wiki_links


def test_parses_links_in_order():
    text = "去海边 [[daily_life:beach-trip-plan]]，另见 [[reading:海风书单]]。"
    assert parse_wiki_links(text) == [
        WikiLink("daily_life", "beach-trip-plan"),
        WikiLink("reading", "海风书单"),
    ]


def test_ignores_malformed_links():
    text = "[[no-colon]] [[:empty-cat]] [[cat:]] [[a:b:c]] [[spans\nlines:x]]"
    assert parse_wiki_links(text) == []


def test_strips_whitespace_inside_link():
    assert parse_wiki_links("[[ preferences : likes-the-sea ]]") == [
        WikiLink("preferences", "likes-the-sea")
    ]


def test_render_roundtrip():
    link = WikiLink("daily_life", "beach-trip-plan")
    assert parse_wiki_links(link.render()) == [link]
