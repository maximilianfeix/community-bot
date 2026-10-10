from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from communitybot.github import API, GitHub, GitHubError, Reply, parse_releases, parse_repo

TOKEN = "github_pat_test_0123456789"


class FakeFetch:
    """Answers GETs from a list of replies and records what was asked."""

    def __init__(self, *replies: Reply) -> None:
        self.replies = list(replies)
        self.calls: list[tuple[str, dict[str, str]]] = []

    async def __call__(self, url: str, headers: Mapping[str, str]) -> Reply:
        self.calls.append((url, dict(headers)))
        return self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]


REPO_JSON = {"stargazers_count": 43, "description": "Free  proxies\nthat work", "archived": False, "x": 1}
RELEASE_JSON = {
    "id": 7,
    "tag_name": "v1.2.0",
    "name": "Spring cleaning",
    "html_url": "https://github.com/o/r/releases/tag/v1.2.0",
    "published_at": "2026-10-01T10:00:00Z",
    "body": "notes",
    "prerelease": False,
    "draft": False,
    "author": {"login": "someone"},
}


async def test_repo_is_fetched_parsed_and_cached_with_its_etag() -> None:
    cache: dict[str, dict[str, Any]] = {}
    fetch = FakeFetch(Reply(200, {"ETag": 'W/"abc"'}, REPO_JSON))
    info = await GitHub(fetch, cache).repo("o/r")
    assert (info.stars, info.description, info.archived) == (43, "Free proxies that work", False)
    url, headers = fetch.calls[0]
    assert url == f"{API}/repos/o/r"
    assert "If-None-Match" not in headers
    assert "Authorization" not in headers
    assert cache[url]["etag"] == 'W/"abc"'
    assert "x" not in cache[url]["data"]


async def test_second_request_is_conditional_and_a_304_reuses_the_cache() -> None:
    cache: dict[str, dict[str, Any]] = {}
    fetch = FakeFetch(Reply(200, {"etag": '"v1"'}, REPO_JSON), Reply(304, {}))
    client = GitHub(fetch, cache)
    first = await client.repo("o/r")
    second = await client.repo("o/r")
    assert first == second
    assert fetch.calls[1][1]["If-None-Match"] == '"v1"'


async def test_token_is_sent_only_as_a_bearer_header() -> None:
    fetch = FakeFetch(Reply(200, {}, REPO_JSON))
    await GitHub(fetch, {}, TOKEN).repo("o/r")
    url, headers = fetch.calls[0]
    assert headers["Authorization"] == f"Bearer {TOKEN}"
    assert TOKEN not in url


async def test_releases_are_parsed_and_the_cache_keeps_only_used_fields() -> None:
    cache: dict[str, dict[str, Any]] = {}
    fetch = FakeFetch(Reply(200, {}, [RELEASE_JSON]))
    found = await GitHub(fetch, cache).releases("o/r")
    assert [(r.id, r.tag, r.name, r.stable) for r in found] == [(7, "v1.2.0", "Spring cleaning", True)]
    assert fetch.calls[0][0] == f"{API}/repos/o/r/releases?per_page=30"
    assert "author" not in next(iter(cache.values()))["data"][0]


@pytest.mark.parametrize(
    ("reply", "kind"),
    [
        (Reply(403, {"X-RateLimit-Remaining": "0"}), "rate_limit"),
        (Reply(429, {"Retry-After": "60"}), "rate_limit"),
        (Reply(401, {}), "auth"),
        (Reply(403, {}), "auth"),
        (Reply(404, {}), "not_found"),
        (Reply(502, {}), "server"),
        (Reply(302, {"Location": "https://evil.example"}), "server"),
        (Reply(304, {}), "server"),
    ],
)
async def test_failures_are_classified(reply: Reply, kind: str) -> None:
    with pytest.raises(GitHubError) as caught:
        await GitHub(FakeFetch(reply), {}).repo("o/r")
    assert caught.value.kind == kind


async def test_error_text_never_contains_the_token() -> None:
    with pytest.raises(GitHubError) as caught:
        await GitHub(FakeFetch(Reply(401, {"x": TOKEN}, {"message": TOKEN})), {}, TOKEN).repo("o/r")
    assert TOKEN not in str(caught.value)


async def test_failed_request_does_not_touch_the_cache() -> None:
    cache: dict[str, dict[str, Any]] = {}
    fetch = FakeFetch(Reply(200, {"etag": '"v1"'}, REPO_JSON), Reply(500, {}))
    client = GitHub(fetch, cache)
    await client.repo("o/r")
    before = dict(cache)
    with pytest.raises(GitHubError):
        await client.repo("o/r")
    assert cache == before


@pytest.mark.parametrize("repo", ["", "o", "o/", "/r", "o/r/x", "o/../r", "o/r?x=1", "o/r#f", "o /r", ".."])
async def test_odd_repository_names_never_reach_the_network(repo: str) -> None:
    fetch = FakeFetch(Reply(200, {}, REPO_JSON))
    with pytest.raises(GitHubError):
        await GitHub(fetch, {}).repo(repo)
    assert fetch.calls == []


class TestParsing:
    def test_repo_with_missing_or_odd_fields(self) -> None:
        info = parse_repo({"stargazers_count": "many", "description": None})
        assert (info.stars, info.description, info.archived) == (0, "", False)

    @pytest.mark.parametrize("data", [None, [], "text"])
    def test_repo_that_is_not_an_object(self, data: object) -> None:
        with pytest.raises(GitHubError):
            parse_repo(data)

    @pytest.mark.parametrize("data", [None, {}, "text"])
    def test_releases_that_are_not_a_list(self, data: object) -> None:
        with pytest.raises(GitHubError):
            parse_releases(data)

    def test_entries_without_an_id_are_skipped(self) -> None:
        assert parse_releases([{"tag_name": "v1"}, "junk", {"id": True}]) == []

    def test_name_falls_back_to_the_tag(self) -> None:
        assert parse_releases([{**RELEASE_JSON, "name": None}])[0].name == "v1.2.0"

    def test_links_that_do_not_point_to_github_are_dropped(self) -> None:
        hostile = {**RELEASE_JSON, "html_url": "https://evil.example/releases/v1"}
        assert parse_releases([hostile])[0].url == ""

    def test_very_long_notes_are_capped(self) -> None:
        assert len(parse_releases([{**RELEASE_JSON, "body": "x" * 50_000}])[0].body) == 6000

    def test_draft_and_prerelease_are_not_stable(self) -> None:
        found = parse_releases(
            [{**RELEASE_JSON, "prerelease": True}, {**RELEASE_JSON, "id": 8, "draft": True}]
        )
        assert [r.stable for r in found] == [False, False]
