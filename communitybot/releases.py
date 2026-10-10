"""Decide which releases to announce. Pure.

Rules:
- The first successful look at a repository is a baseline: everything already there is remembered and nothing
  is announced. Otherwise the first start would announce every old release.
- After that, a published stable release is announced once. Releases are told apart by GitHub's id, not by
  tag name, so an edited release is not announced again.
- A prerelease is not announced and not remembered, so it is announced when it is promoted to stable.
- At most a few per round, oldest first, so a long outage cannot flood the channel.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

MAX_PER_ROUND = 3


@dataclass(frozen=True)
class Release:
    id: int
    tag: str
    name: str
    url: str
    published_at: str
    body: str = ""
    prerelease: bool = False
    draft: bool = False

    @property
    def stable(self) -> bool:
        return not self.prerelease and not self.draft and bool(self.published_at)


def baseline(releases: Sequence[Release]) -> list[int]:
    """The ids to remember on the first look: all stable releases that exist now."""
    return sorted(release.id for release in releases if release.stable)


def new_releases(releases: Sequence[Release], seen: Sequence[int]) -> list[Release]:
    """Stable releases not announced yet, oldest first, capped per round."""
    known = set(seen)
    fresh = [release for release in releases if release.stable and release.id not in known]
    fresh.sort(key=lambda release: (release.published_at, release.id))
    return fresh[:MAX_PER_ROUND]


def latest(releases: Sequence[Release]) -> Release | None:
    """The most recently published stable release, for the project card."""
    stable = [release for release in releases if release.stable]
    return max(stable, key=lambda release: (release.published_at, release.id), default=None)
