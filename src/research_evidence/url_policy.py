from dataclasses import dataclass
import ipaddress
from urllib.parse import urlparse


@dataclass(frozen=True)
class UrlPolicy:
    allow_domains: tuple[str, ...] = ()
    deny_domains: tuple[str, ...] = ()
    max_url_length: int = 2048


def _normalise_domain(domain: str) -> str:
    return domain.lower().rstrip(".")


def _matches_domain(host: str, domain: str) -> bool:
    domain = _normalise_domain(domain)
    return bool(domain) and (host == domain or host.endswith("." + domain))


def check_url(url: str, policy: UrlPolicy) -> tuple[bool, str]:
    try:
        if not isinstance(url, str):
            return False, "url must be a string"
        if len(url) > policy.max_url_length:
            return False, "url too long"

        parsed = urlparse(url)
        if parsed.scheme.lower() not in ("http", "https"):
            return False, "scheme not allowed"
        if parsed.username is not None or parsed.password is not None:
            return False, "credentials not allowed"

        host = parsed.hostname
        if not host:
            return False, "hostname missing"
        host = host.lower().rstrip(".")
        if host == "localhost":
            return False, "private address"

        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address is not None and (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_unspecified
        ):
            return False, "private address"

        if any(_matches_domain(host, domain) for domain in policy.deny_domains):
            return False, "domain denied"
        if policy.allow_domains and not any(
            _matches_domain(host, domain) for domain in policy.allow_domains
        ):
            return False, "domain not allowed"
        return True, "ok"
    except Exception:
        return False, "invalid url"
