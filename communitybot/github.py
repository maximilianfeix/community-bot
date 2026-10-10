"""Read public repository data from the GitHub API.

Only two things are asked per repository: its metadata (stars) and its first page of releases. Every answer
is cached with its ETag, and the next request says "only if changed". The requests go to one fixed host, are
GET only, and follow no links from a response.

The HTTP call is injected, so the tests run without a network.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from .releases import Release
from .sanitize import one_line

API = "https://api.github.com"
RELEASES_PER_PAGE = 30
MAX_BODY_CHARS = 6000


class GitHubError(Exception):
    """A request failed. `kind` is one of: rate_limit, not_found, auth, server, network, format."""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


@dataclass(frozen=True)
class Reply:
    status: int
    headers: Mapping[str, str]
    data: Any = None


Fetch = Callable[[str, Mapping[str, str]], Awaitable[Reply]]
"""Perform one GET: (url, headers) -> Reply. Must not follow redirects."""


@dataclass(frozen=True)
class RepoInfo:
    stars: int
    description: str
    archived: bool


class GitHub:
    def __init__(self, fetch: Fetch, cache: dict[str, dict[str, Any]], token: str = "") -> None:
        self._fetch = fetch
        self._cache = cache
        self._token = token

    async def repo(self, repo: str) -> RepoInfo:
        return parse_repo(await self._get(f"/repos/{_checked(repo)}", _slim_repo))

    async def releases(self, repo: str) -> list[Release]:
        path = f"/repos/{_checked(repo)}/releases?per_page={RELEASES_PER_PAGE}"
        return parse_releases(await self._get(path, _slim_releases))

    async def _get(self, path: str, slim: Callable[[Any], Any]) -> Any:
        url = API + path
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "communitybot (+https://github.com/maximilianfeix/community-bot)",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        cached = self._cache.get(url)
        if cached and cached.get("etag"):
            headers["If-None-Match"] = str(cached["etag"])

        reply = await self._fetch(url, headers)
        if reply.status == 304 and cached is not None:
            return cached["data"]
        if reply.status == 200:
            etag = _header(reply.headers, "etag")
            data = slim(reply.data)
            self._cache[url] = {"etag": etag, "data": data}
            return data
        raise _error(reply)


_REPO_FIELDS = ("stargazers_count", "description", "archived")
_RELEASE_FIELDS = ("id", "tag_name", "name", "html_url", "published_at", "prerelease", "draft")


def _slim_repo(data: Any) -> Any:
    """Keep only the fields that are used, so the cache in the state file stays small."""
    return {key: data.get(key) for key in _REPO_FIELDS} if isinstance(data, Mapping) else data


def _slim_releases(data: Any) -> Any:
    if not isinstance(data, list):
        return data
    return [
        {
            **{key: item.get(key) for key in _RELEASE_FIELDS},
            "body": str(item.get("body") or "")[:MAX_BODY_CHARS],
        }
        for item in data
        if isinstance(item, Mapping)
    ]


def parse_repo(data: Any) -> RepoInfo:
    if not isinstance(data, Mapping):
        raise GitHubError("format", "repository answer is not an object")
    return RepoInfo(
        stars=_count(data.get("stargazers_count")),
        description=one_line(data.get("description"), 300),
        archived=bool(data.get("archived")),
    )


def parse_releases(data: Any) -> list[Release]:
    if not isinstance(data, list):
        raise GitHubError("format", "releases answer is not a list")
    releases = []
    for item in data:
        if not isinstance(item, Mapping) or not _count(item.get("id")):
            continue
        tag = one_line(item.get("tag_name"), 80)
        releases.append(
            Release(
                id=_count(item.get("id")),
                tag=tag,
                name=one_line(item.get("name"), 120) or tag,
                url=_release_url(item.get("html_url")),
                published_at=one_line(item.get("published_at"), 40),
                body=str(item.get("body") or "")[:MAX_BODY_CHARS],
                prerelease=bool(item.get("prerelease")),
                draft=bool(item.get("draft")),
            )
        )
    return releases


def _release_url(value: object) -> str:
    """Only links to github.com are passed on; anything else is dropped."""
    url = one_line(value, 300)
    return url if url.startswith("https://github.com/") else ""


def _checked(repo: str) -> str:
    """`owner/name` from the fixed project list; refuse anything that could change the path."""
    owner, _, name = repo.partition("/")
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_."
    for part in (owner, name):
        if not part or part in (".", "..") or any(ch not in allowed for ch in part):
            raise GitHubError("format", "repository name is not of the form owner/name")
    return f"{owner}/{name}"


def _error(reply: Reply) -> GitHubError:
    status = reply.status
    if status in (403, 429) and (
        _header(reply.headers, "x-ratelimit-remaining") == "0" or _header(reply.headers, "retry-after")
    ):
        return GitHubError("rate_limit", "GitHub rate limit reached")
    if status in (401, 403):
        return GitHubError("auth", f"GitHub refused the request ({status})")
    if status == 404:
        return GitHubError("not_found", "repository not found")
    if status >= 500:
        return GitHubError("server", f"GitHub server error ({status})")
    return GitHubError("server", f"unexpected answer from GitHub ({status})")


def _header(headers: Mapping[str, str], name: str) -> str:
    wanted = name.lower()
    return next((value for key, value in headers.items() if key.lower() == wanted), "")


def _count(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0
