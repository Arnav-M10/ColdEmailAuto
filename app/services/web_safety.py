from __future__ import annotations

import hashlib
import ipaddress
import socket
import time
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import Protocol, cast
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

ALLOWED_API_HOSTS = {
    "api.openalex.org",
    "api.crossref.org",
    "export.arxiv.org",
    "arxiv.org",
    "orcid.org",
    "pub.orcid.org",
}
ALLOWED_FULL_TEXT_HOSTS = {
    "academic.oup.com",
    "aasjournals.org",
    "cds.cern.ch",
    "escholarship.org",
    "frontiersin.org",
    "hal.science",
    "indico.cern.ch",
    "inspirehep.net",
    "iopscience.iop.org",
    "journals.aps.org",
    "journals.plos.org",
    "link.aps.org",
    "link.springer.com",
    "mdpi.com",
    "nature.com",
    "openreview.net",
    "plos.org",
    "pnas.org",
    "repo.scoap3.org",
    "royalsocietypublishing.org",
    "science.org",
    "www.frontiersin.org",
    "www.mdpi.com",
    "www.nature.com",
    "www.pnas.org",
    "www.science.org",
    "www.springer.com",
    "zenodo.org",
}

BLOCKED_HOSTNAMES = {"localhost", "localhost.localdomain"}
BLOCKED_CONTENT_TYPES = {"text/plain"}


@dataclass(frozen=True)
class URLValidationResult:
    url: str
    host: str
    category: str


@dataclass(frozen=True)
class FetchResult:
    url: str
    final_url: str
    status_code: int
    content_type: str
    body: bytes
    sha256: str
    robots_allowed: bool


class SafeFetchError(ValueError):
    pass


class ResponseLike(Protocol):
    status_code: int
    headers: dict[str, str]
    content: bytes

    @property
    def text(self) -> str: ...

    @property
    def url(self) -> object: ...


class HTTPClientLike(Protocol):
    def get(
        self,
        url: str,
        *,
        headers: dict[str, str],
        follow_redirects: bool,
    ) -> ResponseLike: ...


class RateLimiter:
    def __init__(self, min_delay_seconds: float) -> None:
        self.min_delay_seconds = min_delay_seconds
        self._last_seen_by_host: dict[str, float] = {}

    def wait(self, host: str) -> None:
        if self.min_delay_seconds <= 0:
            return
        now = time.monotonic()
        last_seen = self._last_seen_by_host.get(host)
        if last_seen is not None:
            remaining = self.min_delay_seconds - (now - last_seen)
            if remaining > 0:
                time.sleep(remaining)
        self._last_seen_by_host[host] = time.monotonic()


def is_university_host(host: str) -> bool:
    host = host.lower().strip(".")
    return (
        host.endswith(".edu")
        or ".edu." in host
        or host.endswith(".ac.uk")
        or ".ac." in host
        or host.endswith(".edu.au")
        or host.endswith(".edu.sg")
        or host.endswith(".edu.cn")
    )


def _is_private_ip(address: str) -> bool:
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return False
    return (
        parsed.is_private
        or parsed.is_loopback
        or parsed.is_link_local
        or parsed.is_multicast
        or parsed.is_reserved
        or parsed.is_unspecified
    )


def _resolve_host(host: str) -> list[str]:
    try:
        results = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise SafeFetchError(f"Could not resolve host: {host}") from exc
    addresses = sorted({str(item[4][0]) for item in results})
    if not addresses:
        raise SafeFetchError(f"Could not resolve host: {host}")
    return addresses


def validate_url(url: str, *, resolve_dns: bool = True) -> URLValidationResult:
    parsed = urlparse(url.strip())
    if parsed.scheme != "https":
        raise SafeFetchError("Only HTTPS URLs are allowed for remote retrieval.")
    if not parsed.hostname:
        raise SafeFetchError("URL must include a hostname.")

    host = parsed.hostname.lower().strip(".")
    if host in BLOCKED_HOSTNAMES or _is_private_ip(host):
        raise SafeFetchError("Localhost and private network targets are blocked.")

    if resolve_dns:
        for address in _resolve_host(host):
            if _is_private_ip(address):
                raise SafeFetchError("Host resolves to a blocked private network address.")

    if host in ALLOWED_API_HOSTS:
        category = "approved_public_api"
    elif is_university_host(host):
        category = "official_university_domain"
    elif host in ALLOWED_FULL_TEXT_HOSTS:
        category = "approved_public_full_text_host"
    else:
        raise SafeFetchError("URL is outside the allowed retrieval categories.")

    return URLValidationResult(url=url, host=host, category=category)


def retry_after_seconds(value: str | None) -> float | None:
    if not value:
        return None
    stripped = value.strip()
    if stripped.isdigit():
        return float(stripped)
    try:
        retry_time = parsedate_to_datetime(stripped)
    except (TypeError, ValueError, IndexError):
        return None
    return max(0.0, retry_time.timestamp() - time.time())


class SafeFetcher:
    def __init__(
        self,
        *,
        client: HTTPClientLike | None = None,
        rate_limiter: RateLimiter | None = None,
        max_bytes: int | None = None,
        max_redirects: int | None = None,
        user_agent: str | None = None,
    ) -> None:
        if client is None or max_bytes is None or max_redirects is None or user_agent is None:
            from app.config import get_settings

            settings = get_settings()
            max_bytes = max_bytes or settings.max_html_size_mb * 1024 * 1024
            max_redirects = max_redirects or settings.http_max_redirects
            user_agent = user_agent or settings.http_user_agent
            min_delay = settings.http_min_domain_delay_seconds
            timeout_seconds = settings.http_timeout_seconds
        else:
            min_delay = 1.0
            timeout_seconds = 12.0
        self.max_bytes = max_bytes
        self.max_redirects = max_redirects
        self.user_agent = user_agent
        if client is None:
            import httpx

            client = cast(HTTPClientLike, httpx.Client(timeout=timeout_seconds))
        self.client = client
        self.rate_limiter = rate_limiter or RateLimiter(min_delay)

    def robots_allowed(self, url: str, *, user_agent: str | None = None) -> bool:
        validation = validate_url(url)
        robots_url = f"https://{validation.host}/robots.txt"
        parser = RobotFileParser()
        parser.set_url(robots_url)
        try:
            response = self.client.get(
                robots_url,
                headers={"User-Agent": self.user_agent},
                follow_redirects=False,
            )
        except Exception:
            return True
        if response.status_code in {401, 403}:
            return False
        if response.status_code >= 400:
            return True
        parser.parse(response.text.splitlines())
        return parser.can_fetch(user_agent or self.user_agent, url)

    def fetch(self, url: str, *, expected: str = "html") -> FetchResult:
        current_url = url
        validation = validate_url(current_url)
        robots_allowed = self.robots_allowed(current_url)
        if not robots_allowed:
            raise SafeFetchError("robots.txt disallows retrieval for this URL.")

        for _redirect_index in range(self.max_redirects + 1):
            validation = validate_url(current_url)
            self.rate_limiter.wait(validation.host)
            response = self.client.get(
                current_url,
                headers={"User-Agent": self.user_agent},
                follow_redirects=False,
            )
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("location")
                if not location:
                    raise SafeFetchError("Redirect response did not include a target.")
                current_url = urljoin(current_url, location)
                continue
            if response.status_code == 429:
                retry_after = retry_after_seconds(response.headers.get("retry-after"))
                message = "Remote host rate-limited the request."
                if retry_after is not None:
                    message = f"{message} Retry after {retry_after:.0f} seconds."
                raise SafeFetchError(message)
            if response.status_code >= 400:
                raise SafeFetchError(f"Remote host returned HTTP {response.status_code}.")

            content_type = response.headers.get("content-type", "").split(";")[0].lower()
            body = response.content
            if len(body) > self.max_bytes:
                raise SafeFetchError("Response exceeded the configured size limit.")
            self._validate_content(expected=expected, content_type=content_type, body=body)
            return FetchResult(
                url=url,
                final_url=str(response.url),
                status_code=response.status_code,
                content_type=content_type,
                body=body,
                sha256=hashlib.sha256(body).hexdigest(),
                robots_allowed=robots_allowed,
            )

        raise SafeFetchError("Too many redirects.")

    def _validate_content(self, *, expected: str, content_type: str, body: bytes) -> None:
        if expected == "pdf":
            if not body.startswith(b"%PDF-"):
                raise SafeFetchError("Downloaded file is not a valid PDF.")
            if content_type and "pdf" not in content_type:
                raise SafeFetchError("PDF download did not use a PDF content type.")
            return
        if expected == "html":
            if body.startswith(b"%PDF-"):
                raise SafeFetchError("Expected HTML but received a PDF.")
            if content_type in BLOCKED_CONTENT_TYPES:
                raise SafeFetchError("Unsupported content type for HTML import.")
            if content_type and "html" not in content_type and "xml" not in content_type:
                raise SafeFetchError("Expected HTML content from department import.")
