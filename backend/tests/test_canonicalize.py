from app.collectors.base import canonicalize_url


def test_canonicalize_strips_utm():
    assert canonicalize_url("https://example.com/post?utm_source=x&id=7") == "example.com/post?id=7"


def test_canonicalize_strips_www_and_trailing_slash():
    assert canonicalize_url("https://www.example.com/post/") == "example.com/post"


def test_canonicalize_strips_fragment():
    assert canonicalize_url("https://example.com/x#section") == "example.com/x"


def test_canonicalize_amp_suffix():
    assert canonicalize_url("https://example.com/a/amp") == "example.com/a"
