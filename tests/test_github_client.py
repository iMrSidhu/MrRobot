import asyncio
import json
import pathlib
import sys
import time

import httpx
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ingestion import github_client as gc  # noqa: E402


def item(rid: int, name: str, stars: int) -> dict:
    return {"id": rid, "full_name": name, "clone_url": f"https://github.com/{name}.git", "stargazers_count": stars}


def client_for(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=gc.BASE_URL)


def search(keywords, handler, min_stars=1000, **kwargs) -> list[gc.RepoCandidate]:
    async def go():
        async with client_for(handler) as c:
            return await gc.search_repositories(keywords, min_stars, client=c, **kwargs)

    return asyncio.run(go())


def test_success_maps_candidates():
    def handler(request):
        return httpx.Response(200, json={"items": [item(1, "owner/repo", 5000), item(2, "a/b", 1200)]})

    got = search(("ai agent",), handler=handler)
    assert [c.name for c in got] == ["owner/repo", "a/b"]
    assert got[0].id == 1 and got[0].stars == 5000
    assert got[0].url == "https://github.com/owner/repo.git"


def test_query_and_token_headers():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"items": []})

    search(("harness",), min_stars=1000, handler=handler, token="ghp_test")
    q = seen[0].url.params
    assert q["q"] == "harness stars:>1000" and q["sort"] == "stars" and q["per_page"] == "100"
    assert seen[0].headers["authorization"] == "token ghp_test"


def test_pagination_walks_pages():
    pages = {
        "1": [item(1, "a/1", 9000), item(2, "a/2", 8000)],
        "2": [item(3, "a/3", 7000)],  # short page -> stop
    }
    requested = []

    def handler(request):
        page = request.url.params["page"]
        requested.append(page)
        return httpx.Response(200, json={"items": pages[page]})

    got = search(("agent",), handler=handler, per_page=2)
    assert requested == ["1", "2"]
    assert [c.name for c in got] == ["a/1", "a/2", "a/3"]


def test_dedupe_across_keywords():
    calls = []

    def handler(request):
        calls.append(request.url.params["q"])
        return httpx.Response(200, json={"items": [item(1, "dup/repo", 5000)]})

    got = search(("x", "y"), handler=handler)
    assert len(calls) == 2  # both keywords searched
    assert len(got) == 1 and got[0].name == "dup/repo"


def test_rate_limited_403_uses_retry_after():
    def handler(request):
        return httpx.Response(403, json={"message": "secondary rate limit"}, headers={"Retry-After": "42"})

    with pytest.raises(gc.RateLimited) as exc:
        search(("k",), handler=handler)
    assert exc.value.wait_seconds == 42


def test_rate_limited_429_uses_ratelimit_reset():
    reset = int(time.time()) + 120

    def handler(request):
        return httpx.Response(429, json={"message": "abuse"}, headers={"X-RateLimit-Reset": str(reset)})

    with pytest.raises(gc.RateLimited) as exc:
        search(("k",), handler=handler)
    assert 100 <= exc.value.wait_seconds <= 120


def test_exhausted_limit_on_200_raises():
    def handler(request):
        return httpx.Response(200, json={"items": []}, headers={"X-RateLimit-Remaining": "0"})

    with pytest.raises(gc.RateLimited) as exc:  # no Retry-After/Reset -> 60s fallback
        search(("k",), handler=handler)
    assert exc.value.wait_seconds == 60


def test_http_error_propagates():
    def handler(request):
        return httpx.Response(500, json={"message": "boom"})

    with pytest.raises(httpx.HTTPStatusError):
        search(("k",), handler=handler)
