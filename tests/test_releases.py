from __future__ import annotations

from communitybot.releases import MAX_PER_ROUND, Release, baseline, latest, new_releases


def rel(release_id: int, day: int = 1, *, prerelease: bool = False, draft: bool = False) -> Release:
    return Release(
        id=release_id,
        tag=f"v{release_id}",
        name=f"v{release_id}",
        url=f"https://github.com/o/r/releases/tag/v{release_id}",
        published_at="" if draft else f"2026-10-{day:02d}T10:00:00Z",
        prerelease=prerelease,
        draft=draft,
    )


def test_baseline_remembers_stable_releases_only() -> None:
    found = [rel(3, 3), rel(2, 2, prerelease=True), rel(1, 1), rel(9, draft=True)]
    assert baseline(found) == [1, 3]


def test_empty_repository_has_an_empty_baseline() -> None:
    assert baseline([]) == []


def test_nothing_new_when_everything_was_seen() -> None:
    assert new_releases([rel(1), rel(2)], [1, 2]) == []


def test_new_stable_release_is_found() -> None:
    assert [r.id for r in new_releases([rel(2, 2), rel(1, 1)], [1])] == [2]


def test_prerelease_is_not_announced_until_it_becomes_stable() -> None:
    assert new_releases([rel(5, 5, prerelease=True)], []) == []
    assert [r.id for r in new_releases([rel(5, 5)], [])] == [5]


def test_draft_is_never_announced() -> None:
    assert new_releases([rel(5, draft=True)], []) == []


def test_edited_release_keeps_its_id_and_is_not_announced_again() -> None:
    edited = Release(1, "v1", "A new title", "https://github.com/o/r/releases/tag/v1", "2026-10-01T10:00:00Z")
    assert new_releases([edited], [1]) == []


def test_oldest_first_and_capped_per_round() -> None:
    found = [rel(n, n) for n in range(10, 0, -1)]
    fresh = new_releases(found, [])
    assert [r.id for r in fresh] == [1, 2, 3]
    assert len(fresh) == MAX_PER_ROUND


def test_catching_up_over_several_rounds_announces_each_once() -> None:
    found = [rel(n, n) for n in range(1, 8)]
    seen: list[int] = []
    announced: list[int] = []
    for _ in range(5):
        batch = new_releases(found, seen)
        seen.extend(r.id for r in batch)
        announced.extend(r.id for r in batch)
    assert announced == [1, 2, 3, 4, 5, 6, 7]


def test_same_timestamp_is_ordered_by_id() -> None:
    assert [r.id for r in new_releases([rel(8, 1), rel(7, 1)], [])] == [7, 8]


def test_latest_is_the_newest_stable_release() -> None:
    found = [rel(1, 1), rel(3, 9, prerelease=True), rel(2, 5)]
    newest = latest(found)
    assert newest is not None
    assert newest.id == 2


def test_latest_of_nothing_is_none() -> None:
    assert latest([]) is None
    assert latest([rel(1, prerelease=True)]) is None
