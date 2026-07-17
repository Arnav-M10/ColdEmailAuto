from collections.abc import Callable
from dataclasses import dataclass, field

import pytest

from app.services import web_safety
from app.services.web_safety import ResponseLike, SafeFetcher, SafeFetchError, validate_url


def allow_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_resolve(_host: str) -> list[str]:
        return ["93.184.216.34"]

    monkeypatch.setattr(web_safety, "_resolve_host", fake_resolve)


def test_url_validation_allows_university_and_public_api_hosts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    allow_dns(monkeypatch)

    university = validate_url("https://astro.example.edu/people")
    openalex = validate_url("https://api.openalex.org/authors?search=jane")

    assert university.category == "official_university_domain"
    assert openalex.category == "approved_public_api"


@pytest.mark.parametrize(
    "url",
    [
        "http://astro.example.edu/people",
        "https://127.0.0.1/people",
        "https://localhost/people",
        "https://169.254.169.254/latest/meta-data",
        "https://example.com/people",
        "file:///etc/passwd",
    ],
)
def test_url_validation_blocks_unsafe_targets(url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    allow_dns(monkeypatch)

    with pytest.raises(SafeFetchError):
        validate_url(url)


def test_url_validation_blocks_hosts_resolving_to_private_ips(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_resolve(_host: str) -> list[str]:
        return ["10.0.0.5"]

    monkeypatch.setattr(web_safety, "_resolve_host", fake_resolve)

    with pytest.raises(SafeFetchError, match="private network"):
        validate_url("https://astro.example.edu/people")


@dataclass(frozen=True)
class FakeURL:
    path: str


@dataclass(frozen=True)
class FakeRequest:
    url: FakeURL


@dataclass
class FakeResponse:
    status_code: int
    content: bytes = b""
    headers: dict[str, str] = field(default_factory=dict)
    url: str = "https://astro.example.edu/people"

    @property
    def text(self) -> str:
        return self.content.decode("utf-8")


class FakeClient:
    def __init__(self, handler: Callable[[FakeRequest], FakeResponse]) -> None:
        self.handler = handler

    def get(
        self,
        url: str,
        *,
        headers: dict[str, str],
        follow_redirects: bool,
    ) -> ResponseLike:
        del headers, follow_redirects
        path = "/" + url.split("/", maxsplit=3)[3] if url.count("/") >= 3 else "/"
        return self.handler(FakeRequest(url=FakeURL(path=path)))


def response(
    status_code: int,
    *,
    text: str = "",
    content: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> FakeResponse:
    body = content if content is not None else text.encode("utf-8")
    return FakeResponse(status_code=status_code, content=body, headers=headers or {})


def build_fetcher(handler: Callable[[FakeRequest], FakeResponse]) -> SafeFetcher:
    fetcher = SafeFetcher(
        client=FakeClient(handler),
        rate_limiter=web_safety.RateLimiter(0),
        max_bytes=1024,
        max_redirects=5,
        user_agent="ProfessorOutreachManagerTest/0.1",
    )
    return fetcher


def test_fetcher_respects_robots_denial(monkeypatch: pytest.MonkeyPatch) -> None:
    allow_dns(monkeypatch)

    def handler(request: FakeRequest) -> FakeResponse:
        if request.url.path == "/robots.txt":
            return response(200, text="User-agent: *\nDisallow: /people")
        return response(200, text="<html></html>", headers={"content-type": "text/html"})

    fetcher = build_fetcher(handler)

    with pytest.raises(SafeFetchError, match="robots"):
        fetcher.fetch("https://astro.example.edu/people")


def test_fetcher_revalidates_redirect_targets(monkeypatch: pytest.MonkeyPatch) -> None:
    allow_dns(monkeypatch)

    def handler(request: FakeRequest) -> FakeResponse:
        if request.url.path == "/robots.txt":
            return response(404)
        return response(302, headers={"location": "https://127.0.0.1/private"})

    fetcher = build_fetcher(handler)

    with pytest.raises(SafeFetchError, match="private network"):
        fetcher.fetch("https://astro.example.edu/people")


def test_fetcher_rejects_oversized_html(monkeypatch: pytest.MonkeyPatch) -> None:
    allow_dns(monkeypatch)

    def handler(request: FakeRequest) -> FakeResponse:
        if request.url.path == "/robots.txt":
            return response(404)
        return response(200, content=b"x" * 2048, headers={"content-type": "text/html"})

    fetcher = build_fetcher(handler)

    with pytest.raises(SafeFetchError, match="size limit"):
        fetcher.fetch("https://astro.example.edu/people")


def test_fetcher_rejects_html_masquerading_as_pdf(monkeypatch: pytest.MonkeyPatch) -> None:
    allow_dns(monkeypatch)

    def handler(request: FakeRequest) -> FakeResponse:
        if request.url.path == "/robots.txt":
            return response(404)
        return response(
            200,
            content=b"<html>not a pdf</html>",
            headers={"content-type": "text/html"},
        )

    fetcher = build_fetcher(handler)

    with pytest.raises(SafeFetchError, match="not a valid PDF"):
        fetcher.fetch("https://astro.example.edu/paper.pdf", expected="pdf")
