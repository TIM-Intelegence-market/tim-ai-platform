from hashlib import sha256

import pytest

from src.research_evidence.crawl4ai_provider import Crawl4AIProvider
from src.research_evidence.model import Evidence
from src.research_evidence.url_policy import UrlPolicy
from src.research_evidence.web import FetchError, WebResearchProvider

URL = "https://example.com/article"
NOW = "2026-10-16T12:00:00Z"


class FakeTransport:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    def __call__(self, *args):
        self.calls.append(args)
        if self.error:
            raise self.error
        return self.result


def ok_payload(markdown="# Hello", url=URL, title="Hello page"):
    entry = {"markdown": markdown, "metadata": {"title": title}}
    if url is not None:
        entry["url"] = url
    return (200, {"results": [entry]})


def provider(transport, **kwargs):
    kwargs.setdefault("policy", UrlPolicy())
    kwargs.setdefault("clock", lambda: NOW)
    return Crawl4AIProvider("http://127.0.0.1:11235", transport, **kwargs)


def fetch_error(prov, url=URL):
    with pytest.raises(FetchError) as error:
        prov.fetch(url, timeout_seconds=5.0)
    return error.value.code


def test_success_builds_web_evidence():
    transport = FakeTransport(ok_payload())
    prov = provider(transport)
    evidence = prov.fetch(URL, timeout_seconds=7.5)

    assert isinstance(evidence, Evidence)
    assert prov.name == "crawl4ai"
    assert evidence.source_uri == URL
    assert evidence.source_type == "web"
    assert evidence.provider == "crawl4ai"
    assert evidence.extraction_method == "crawl4ai.markdown"
    assert evidence.title == "Hello page"
    assert evidence.content == "# Hello"
    assert evidence.content_hash == "sha256:" + sha256(b"# Hello").hexdigest()
    assert evidence.retrieved_at == NOW
    assert evidence.metadata == {"final_url": URL, "redirected": False}
    assert evidence.warnings == ()
    assert transport.calls == [
        ("POST", "http://127.0.0.1:11235/crawl", {"urls": [URL]}, 7.5)
    ]


def test_provider_satisfies_protocol_shape():
    prov: WebResearchProvider = provider(FakeTransport(ok_payload()))
    assert isinstance(prov.name, str)


def test_missing_title_and_url_defaults():
    transport = FakeTransport((200, {"results": [{"markdown": "x"}]}))
    evidence = provider(transport).fetch(URL, timeout_seconds=1)
    assert evidence.title == ""
    assert evidence.metadata == {"final_url": URL, "redirected": False}


def test_public_redirect_is_recorded():
    final = "https://www.example.org/moved"
    evidence = provider(FakeTransport(ok_payload(url=final))).fetch(URL, timeout_seconds=1)
    assert evidence.metadata == {"final_url": final, "redirected": True}


@pytest.mark.parametrize(
    ("url", "policy"),
    [
        ("http://127.0.0.1/admin", UrlPolicy()),
        ("http://localhost:8080/", UrlPolicy()),
        ("file:///etc/passwd", UrlPolicy()),
        ("https://user:pw@example.com/", UrlPolicy()),
        (URL, UrlPolicy(deny_domains=("example.com",))),
        (URL, UrlPolicy(allow_domains=("other.org",))),
    ],
)
def test_policy_denial_before_transport(url, policy):
    transport = FakeTransport(ok_payload())
    assert fetch_error(provider(transport, policy=policy), url) == "policy"
    assert transport.calls == []


@pytest.mark.parametrize("status", [404, 500, 302])
def test_non_200_status(status):
    transport = FakeTransport((status, {"results": [{"markdown": "x"}]}))
    assert fetch_error(provider(transport)) == f"http_{status}"
    assert len(transport.calls) == 1


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {},
        {"results": []},
        {"results": "x"},
        {"results": [None]},
        {"results": [{}]},
        {"results": [{"markdown": None}]},
        {"results": [{"markdown": 3}]},
    ],
)
def test_parse_errors(payload):
    assert fetch_error(provider(FakeTransport((200, payload)))) == "parse"


@pytest.mark.parametrize(
    "final_url",
    ["http://169.254.169.254/latest/meta-data", "http://10.0.0.5/", "http://localhost/", 42],
)
def test_redirect_to_disallowed_address(final_url):
    transport = FakeTransport(ok_payload(url=final_url))
    assert fetch_error(provider(transport)) == "redirect_policy"
    assert len(transport.calls) == 1


def test_redirect_to_denied_domain():
    transport = FakeTransport(ok_payload(url="https://evil.test/"))
    prov = provider(transport, policy=UrlPolicy(deny_domains=("evil.test",)))
    assert fetch_error(prov) == "redirect_policy"


def test_truncation_adds_warning():
    transport = FakeTransport(ok_payload(markdown="abcdefghij"))
    evidence = provider(transport, max_content_chars=4).fetch(URL, timeout_seconds=1)
    assert evidence.content == "abcd"
    assert evidence.warnings == ("truncated",)
    assert evidence.content_hash == "sha256:" + sha256(b"abcd").hexdigest()


def test_content_at_limit_is_not_truncated():
    transport = FakeTransport(ok_payload(markdown="abcd"))
    evidence = provider(transport, max_content_chars=4).fetch(URL, timeout_seconds=1)
    assert evidence.content == "abcd"
    assert evidence.warnings == ()


@pytest.mark.parametrize("error", [TimeoutError("slow"), ConnectionError("down"), RuntimeError()])
def test_transport_exception(error):
    transport = FakeTransport(error=error)
    assert fetch_error(provider(transport)) == "transport"
    assert len(transport.calls) == 1


def test_single_transport_call_per_fetch_without_retry():
    transport = FakeTransport((503, {}))
    prov = provider(transport)
    fetch_error(prov)
    assert len(transport.calls) == 1
    transport.result = ok_payload()
    prov.fetch(URL, timeout_seconds=1)
    assert len(transport.calls) == 2


@pytest.mark.parametrize("base_url", ["http://localhost:11235", "http://127.0.0.1:8/"])
def test_loopback_base_url_accepted(base_url):
    transport = FakeTransport(ok_payload())
    Crawl4AIProvider(base_url, transport, policy=UrlPolicy(), clock=lambda: NOW).fetch(
        URL, timeout_seconds=1
    )
    assert transport.calls[0][1] == base_url.rstrip("/") + "/crawl"


@pytest.mark.parametrize(
    "base_url",
    [
        "http://example.com:11235",
        "http://10.0.0.2:11235",
        "https://127.0.0.1:11235",
        "http://127.0.0.1",
        "http://localhost",
        "http://[::1]:11235",
        "http://user:pw@127.0.0.1:11235",
        "http://127.0.0.1:11235/api",
        "http://127.0.0.1:99999",
        "ftp://127.0.0.1:21",
        None,
    ],
)
def test_non_loopback_base_url_rejected(base_url):
    with pytest.raises(ValueError):
        Crawl4AIProvider(base_url, FakeTransport(), policy=UrlPolicy(), clock=lambda: NOW)


def test_fetch_error_carries_code():
    error = FetchError("parse")
    assert error.code == "parse"
    assert isinstance(error, Exception)
