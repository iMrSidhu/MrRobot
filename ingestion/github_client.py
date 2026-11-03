"""GitHub REST search client for the ingestion service (DESIGN.md §5 Step 2.1).

Async `'<keyword> stars:>=N'` searches with pagination and an optional token.
When GitHub throttles us (403/429 or an exhausted primary rate limit) we raise
RateLimited(wait_seconds) so the caller knows when to retry.
"""
from __future__ import annotations

import time
from typing import Sequence

import httpx

from shared.config import settings
from shared.logging import get_logger
from shared.models import RepoCandidate

log = get_logger("ingestion")

BASE_URL = "https://api.github.com"
MAX_PAGES = 10  # shortcut: GitHub's search API only ever returns the first 1000 matches per query


class RateLimited(Exception):
    """GitHub is throttling us; wait this many seconds before retrying."""

    def __init__(self, wait_seconds: int):
        super().__init__(f"github rate limited, retry in {wait_seconds}s")
        self.wait_seconds = wait_seconds


def _retry_wait(resp: httpx.Response) -> int:
    """Seconds to wait, from Retry-After (secondary limit) or X-RateLimit-Reset (primary)."""
    after = resp.headers.get("retry-after")
    if after is not None:
        return max(0, int(after))
    reset = resp.headers.get("x-ratelimit-reset")
    if reset is not None:
        return max(1, int(reset) - int(time.time()))
    return 60


def _check_rate_limit(resp: httpx.Response) -> None:
    if resp.status_code in (403, 429) or resp.headers.get("x-ratelimit-remaining") == "0":
        wait_s = _retry_wait(resp)
        log.warning(f"rate limited status={resp.status_code} wait={wait_s}s")
        raise RateLimited(wait_s)


def _to_candidate(item: dict) -> RepoCandidate:
    return RepoCandidate(
        id=item["id"],
        name=item["full_name"],
        url=item["clone_url"],  # ready for `git clone` in the processor
        stars=item["stargazers_count"],
    )


async def search_repositories(
    keywords: Sequence[str],
    min_stars: int,
    *,
    token: str | None = None,
    sort: str = "stars",  # "stars" or "updated"
    per_page: int = 100,
    client: httpx.AsyncClient | None = None,
) -> list[RepoCandidate]:
    """Search each `'<keyword> stars:>=N'`, highest stars first; de-duplicated across keywords.

    `keyword` is passed through raw, so GitHub qualifiers are allowed — e.g.
    `"harness in:name"` matches only repo titles (search is case-insensitive).
    """
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token is None:
        token = settings.github_token  # optional: fall back to env/.env
    if token:
        headers["Authorization"] = f"token {token}"

    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(base_url=BASE_URL, timeout=30)

    found: dict[str, RepoCandidate] = {}  # keyed by full_name -> cross-keyword dedupe
    try:
        for keyword in keywords:
            query = f"{keyword} stars:>={min_stars}"
            for page in range(1, MAX_PAGES + 1):
                resp = await client.get(
                    "/search/repositories",
                    params={"q": query, "sort": sort, "order": "desc", "per_page": per_page, "page": page},
                    headers=headers,
                )
                _check_rate_limit(resp)
                resp.raise_for_status()
                items = resp.json()["items"]
                for item in items:
                    candidate = _to_candidate(item)
                    found.setdefault(candidate.name, candidate)
                if len(items) < per_page:  # last page
                    break
    finally:
        if owns_client:
            await client.aclose()

    log.info(f"searched {len(list(keywords))} keywords -> {len(found)} unique repos")
    return list(found.values())
