from urllib.parse import urlsplit

from .model import Evidence, make_evidence
from .url_policy import UrlPolicy, check_url
from .web import FetchError


def _validate_base_url(base_url) -> str:
    if not isinstance(base_url, str):
        raise ValueError("base_url must be loopback http with a port")
    try:
        parsed = urlsplit(base_url)
        port = parsed.port
    except ValueError:
        raise ValueError("base_url must be loopback http with a port") from None
    if (
        parsed.scheme != "http"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.hostname not in {"127.0.0.1", "localhost"}
        or port is None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("base_url must be loopback http with a port")
    return base_url.rstrip("/")


class Crawl4AIProvider:
    name = "crawl4ai"

    def __init__(
        self,
        base_url,
        transport,
        *,
        policy: UrlPolicy,
        max_content_chars: int = 200_000,
        clock,
    ):
        if (
            not isinstance(max_content_chars, int)
            or isinstance(max_content_chars, bool)
            or max_content_chars < 1
        ):
            raise ValueError("max_content_chars must be a positive integer")
        self.base_url = _validate_base_url(base_url)
        self.transport = transport
        self.policy = policy
        self.max_content_chars = max_content_chars
        self.clock = clock

    def fetch(self, url: str, *, timeout_seconds: float) -> Evidence:
        allowed, _reason = check_url(url, self.policy)
        if not allowed:
            raise FetchError("policy")

        try:
            status, payload = self.transport(
                "POST",
                self.base_url + "/crawl",
                {"urls": [url]},
                timeout_seconds,
            )
        except Exception as exc:
            raise FetchError("transport") from exc

        if status != 200:
            raise FetchError(f"http_{status}")

        results = payload.get("results") if isinstance(payload, dict) else None
        if not isinstance(results, list) or not results or not isinstance(results[0], dict):
            raise FetchError("parse")
        first = results[0]
        content = first.get("markdown")
        if not isinstance(content, str):
            raise FetchError("parse")

        final_url = first.get("url")
        if final_url is None:
            final_url = url
        elif not check_url(final_url, self.policy)[0]:
            raise FetchError("redirect_policy")

        metadata = first.get("metadata")
        title = metadata.get("title") if isinstance(metadata, dict) else None
        if not isinstance(title, str):
            title = ""

        warnings: tuple[str, ...] = ()
        if len(content) > self.max_content_chars:
            content = content[: self.max_content_chars]
            warnings = ("truncated",)

        return make_evidence(
            source_uri=url,
            source_type="web",
            provider="crawl4ai",
            extraction_method="crawl4ai.markdown",
            title=title,
            content=content,
            retrieved_at=self.clock(),
            metadata={"final_url": final_url, "redirected": final_url != url},
            warnings=warnings,
        )
