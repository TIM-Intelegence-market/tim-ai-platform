import pytest

from src.research_evidence.url_policy import UrlPolicy, check_url


def test_accepts_http_and_https_urls():
    assert check_url("http://example.com", UrlPolicy()) == (True, "ok")
    assert check_url("https://example.com/path", UrlPolicy()) == (True, "ok")


def test_rejects_non_http_schemes():
    assert check_url("ftp://example.com", UrlPolicy()) == (False, "scheme not allowed")


def test_rejects_missing_hostname():
    assert check_url("https:///path", UrlPolicy()) == (False, "hostname missing")


def test_rejects_non_string_input():
    assert check_url(None, UrlPolicy()) == (False, "url must be a string")


def test_rejects_urls_longer_than_policy_limit():
    assert check_url("https://example.com", UrlPolicy(max_url_length=10)) == (False, "url too long")


def test_rejects_credentials():
    assert check_url("https://user:password@example.com", UrlPolicy()) == (False, "credentials not allowed")


@pytest.mark.parametrize("url", [
    "http://localhost",
    "http://127.0.0.1",
    "http://10.0.0.1",
    "http://169.254.1.1",
    "http://224.0.0.1",
    "http://0.0.0.0",
    "http://[::1]",
    "http://[fc00::1]",
    "http://[fe80::1]",
    "http://[ff02::1]",
    "http://[::]",
])
def test_rejects_private_or_local_addresses(url):
    assert check_url(url, UrlPolicy()) == (False, "private address")


def test_accepts_public_ip_literal():
    assert check_url("https://8.8.8.8", UrlPolicy()) == (True, "ok")
    assert check_url("https://[2001:4860:4860::8888]", UrlPolicy()) == (True, "ok")


def test_deny_domains_match_exact_and_subdomains():
    policy = UrlPolicy(deny_domains=("example.com.",))
    assert check_url("https://example.com.", policy) == (False, "domain denied")
    assert check_url("https://a.example.com", policy) == (False, "domain denied")


def test_deny_domain_does_not_match_partial_suffix():
    policy = UrlPolicy(deny_domains=("example.com",))
    assert check_url("https://badexample.com", policy) == (True, "ok")


def test_allow_domains_require_exact_or_dot_suffix_match():
    policy = UrlPolicy(allow_domains=("Example.COM",))
    assert check_url("https://EXAMPLE.com", policy) == (True, "ok")
    assert check_url("https://a.example.com", policy) == (True, "ok")
    assert check_url("https://badexample.com", policy) == (False, "domain not allowed")


def test_allow_domains_are_checked_after_deny_domains():
    policy = UrlPolicy(allow_domains=("example.com",), deny_domains=("example.com",))
    assert check_url("https://example.com", policy) == (False, "domain denied")
