from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest
from discord import ui

from communitybot import messages, views
from communitybot.definition import ACCENT, SERVER
from communitybot.github import RepoInfo
from communitybot.projects import BY_SLUG, OWNER, PROJECTS
from communitybot.releases import Release

PROJECT = BY_SLUG["dejabuilt"]
CHANNELS = {key: 1000 + index for index, key in enumerate(SERVER.channel_keys())}

MAX_COMPONENTS = 40  # Discord's limit for one message built from layout components
MAX_TEXT = 4000  # ... and for all its text together


def make_release(**changes: Any) -> Release:
    fields: dict[str, Any] = {
        "id": 1,
        "tag": "v0.2.1",
        "name": "v0.2.1",
        "url": "https://github.com/maximilianfeix/dejabuilt/releases/tag/v0.2.1",
        "published_at": "2026-10-10T18:51:18Z",
        "body": "- reads only two environment variables",
    }
    return Release(**{**fields, **changes})


EMOJI_ID = 123456789012345678


@pytest.fixture
def icons() -> Iterator[None]:
    """Custom emojis as the running bot has them."""
    messages.ICONS.update(
        {project.slug: f"<:{project.slug.replace('-', '_')}:{EMOJI_ID}>" for project in PROJECTS}
    )
    yield
    messages.ICONS.clear()


def all_views() -> list[ui.LayoutView]:
    return [
        messages.welcome(CHANNELS),
        messages.rules(),
        messages.projects({}, {}),
        messages.release(PROJECT, make_release()),
        messages.hello(CHANNELS),
        messages.ask(),
        views.picker(),
    ]


def link_buttons(view: ui.LayoutView) -> list[tuple[str, str]]:
    return [
        (child.label or "", child.url or "")
        for child in view.walk_children()
        if isinstance(child, ui.Button) and child.url
    ]


def within_limits(view: ui.LayoutView) -> bool:
    return view.total_children_count <= MAX_COMPONENTS and len(messages.text_of(view)) <= MAX_TEXT


class TestWelcome:
    def test_links_every_public_channel(self) -> None:
        text = messages.text_of(messages.welcome(CHANNELS))
        for key in ("channel:general", "channel:help", "channel:announcements"):
            assert f"<#{CHANNELS[key]}>" in text

    def test_banner_sits_on_top_and_refers_to_the_attached_file(self) -> None:
        view = messages.welcome(CHANNELS)
        container = view.children[0]
        assert isinstance(container, ui.Container)
        assert isinstance(container.children[0], ui.MediaGallery)
        assert messages.pictures(view) == ["banner.png"]

    def test_works_before_the_channels_exist(self) -> None:
        assert "Where things are" not in messages.text_of(messages.welcome({}))

    def test_uses_the_accent_colour_and_stays_within_limits(self) -> None:
        view = messages.welcome(CHANNELS)
        assert messages.components(view)[0]["accent_color"] == ACCENT
        assert within_limits(view)


def test_rules_are_numbered() -> None:
    text = messages.text_of(messages.rules())
    for number, rule in enumerate(messages.RULES, 1):
        assert f"{number}. {rule}" in text


class TestPictures:
    def test_every_card_starts_with_a_picture_that_exists(self) -> None:
        for view in all_views():
            for container in view.children:
                assert isinstance(container, ui.Container)
                assert isinstance(container.children[0], ui.MediaGallery)
            names = messages.pictures(view)
            assert names
            assert all(messages.PICTURES[name].is_file() for name in names)

    def test_every_picture_says_what_it_shows(self) -> None:
        for view in all_views():
            for child in view.walk_children():
                if isinstance(child, ui.MediaGallery):
                    assert all(item.description for item in child.items)

    def test_files_match_the_layout_one_to_one(self) -> None:
        view = messages.projects({}, {})
        assert [file.filename for file in messages.files(view)] == [f"{p.slug}.png" for p in PROJECTS]

    def test_a_changed_picture_changes_the_fingerprint(self, monkeypatch: pytest.MonkeyPatch) -> None:
        before = messages.fingerprint(messages.rules())
        monkeypatch.setitem(messages.PICTURES, "head-rules.png", messages.PICTURES["banner.png"])
        assert messages.fingerprint(messages.rules()) != before


class TestIcons:
    def test_without_emojis_nothing_refers_to_one(self) -> None:
        for view in all_views():
            assert "<:" not in messages.text_of(view)
            assert all(child.emoji is None for child in view.walk_children() if isinstance(child, ui.Button))

    def test_with_emojis_headings_and_buttons_carry_the_sign(self, icons: None) -> None:
        assert messages.text_of(messages.release(PROJECT, make_release())).startswith(
            f"## <:dejabuilt:{EMOJI_ID}> dejabuilt v0.2.1"
        )
        links = [child.emoji for child in messages.ask().walk_children() if isinstance(child, ui.Button)]
        toggles = [
            child.item.emoji
            for child in views.picker().walk_children()
            if isinstance(child, views.NotifyButton)
        ]
        for emojis in (links, toggles):
            assert [emoji.id for emoji in emojis if emoji] == [EMOJI_ID] * len(PROJECTS)


class TestProjects:
    def test_every_project_is_a_card_in_its_own_colour_with_its_links(self) -> None:
        view = messages.projects({}, {})
        assert [card["accent_color"] for card in messages.components(view)] == [p.colour for p in PROJECTS]
        text = messages.text_of(view)
        for project in PROJECTS:
            assert project.tagline in text
        assert link_buttons(view) == [
            link
            for project in PROJECTS
            for link in (
                ("GitHub", project.url),
                ("Releases", f"{project.url}/releases"),
                ("Issues", f"{project.url}/issues"),
            )
        ]

    def test_line_with_data(self) -> None:
        line = messages.project_line(PROJECT, RepoInfo(1234, "", False), make_release())
        assert line.startswith("★ 1,234 · Python · [v0.2.1](https://github.com/")
        assert "<t:1791658278:R>" in line

    def test_line_without_data_yet(self) -> None:
        assert messages.project_line(PROJECT, None, None) == "Python · no release yet"

    def test_release_without_a_link_is_not_shown_as_a_link(self) -> None:
        line = messages.project_line(PROJECT, RepoInfo(1, "", False), make_release(url=""))
        assert line == "★ 1 · Python · no release yet"

    def test_stays_within_limits_with_all_data(self) -> None:
        info = {p.slug: RepoInfo(123_456, "", False) for p in PROJECTS}
        latest: dict[str, Release | None] = {p.slug: make_release(tag="v" + "9" * 60) for p in PROJECTS}
        assert within_limits(messages.projects(info, latest))

    def test_single_project_card(self) -> None:
        view = messages.project(PROJECT, RepoInfo(7, "", False), None)
        assert "★ 7" in messages.text_of(view)
        assert link_buttons(view)[0] == ("GitHub", f"https://github.com/{OWNER}/dejabuilt")
        assert messages.pictures(view) == ["dejabuilt.png"]


class TestRelease:
    def test_heading_notes_link_and_footer(self) -> None:
        view = messages.release(PROJECT, make_release(name="Less environment"), "<@&77>")
        text = messages.text_of(view)
        assert text.startswith("## dejabuilt v0.2.1\n-# Less environment")
        assert "- reads only two environment variables" in text
        assert "-# <@&77> · maximilianfeix/dejabuilt · <t:1791658278:D>" in text
        assert link_buttons(view) == [("Full release notes", make_release().url)]

    def test_no_subtitle_when_the_name_is_just_the_tag(self) -> None:
        text = messages.text_of(messages.release(PROJECT, make_release()))
        assert text.startswith("## dejabuilt v0.2.1\n- reads")

    def test_without_a_role_nothing_is_mentioned(self) -> None:
        text = messages.text_of(messages.release(PROJECT, make_release()))
        assert "<@" not in text
        assert "-# maximilianfeix/dejabuilt" in text

    def test_empty_notes_and_missing_link_have_fallbacks(self) -> None:
        view = messages.release(PROJECT, make_release(body="", url=""))
        assert "No release notes." in messages.text_of(view)
        assert link_buttons(view) == [("Full release notes", PROJECT.url)]

    def test_hostile_notes_cannot_ping_or_overflow(self) -> None:
        body = "@everyone <@&123> <script>x</script> [safe](https://evil.example) " + "y" * 9000
        view = messages.release(PROJECT, make_release(body=body, tag="<@&999>"), "<@&77>")
        text = messages.text_of(view)
        assert "@everyone" not in text
        assert "<@&123>" not in text
        assert "<script>" not in text
        assert "(https://evil.example)" in text
        assert text.count("<@&77>") == 1
        assert within_limits(view)

    def test_odd_timestamp_is_tolerated(self) -> None:
        text = messages.text_of(messages.release(PROJECT, make_release(published_at="soon")))
        assert "<t:" not in text


class TestStarterCards:
    def test_hello_points_to_the_help_channel(self) -> None:
        text = messages.text_of(messages.hello(CHANNELS))
        assert f"<#{CHANNELS['channel:help']}>" in text

    def test_hello_works_before_the_channels_exist(self) -> None:
        assert "<#" not in messages.text_of(messages.hello({}))

    def test_ask_links_every_issue_tracker(self) -> None:
        view = messages.ask()
        assert link_buttons(view) == [(project.name, f"{project.url}/issues") for project in PROJECTS]
        assert len(PROJECTS) <= 5  # one row of buttons
        assert within_limits(view)


class TestFingerprint:
    def test_same_content_same_fingerprint(self) -> None:
        assert messages.fingerprint(views.picker()) == messages.fingerprint(views.picker())

    def test_changes_when_content_or_extra_changes(self) -> None:
        base = messages.fingerprint(messages.projects({}, {}))
        with_stars = messages.fingerprint(messages.projects({"dejabuilt": RepoInfo(5, "", False)}, {}))
        assert base != with_stars
        assert messages.fingerprint(views.picker(), "a") != messages.fingerprint(views.picker(), "b")


class TestButtons:
    def test_one_button_per_project_with_a_stable_id(self) -> None:
        view = views.picker()
        ids = [
            child.item.custom_id for child in view.walk_children() if isinstance(child, views.NotifyButton)
        ]
        assert ids == [f"community:notify:{project.slug}" for project in PROJECTS]
        assert len(ids) <= 5
        assert view.timeout is None
        assert within_limits(view)

    def test_ids_match_the_template_that_revives_them_after_a_restart(self) -> None:
        template = views.NotifyButton.__discord_ui_compiled_template__
        for project in PROJECTS:
            match = template.fullmatch(f"community:notify:{project.slug}")
            assert match is not None
            assert match["slug"] == project.slug
        assert template.fullmatch("community:notify:../etc") is None

    @pytest.mark.parametrize(
        ("permissions", "managed", "below", "expected"),
        [
            (0, False, True, True),
            (8, False, True, False),
            (0, True, True, False),
            (0, False, False, False),
        ],
    )
    def test_only_plain_roles_below_the_bot_are_handed_out(
        self, permissions: int, managed: bool, below: bool, expected: bool
    ) -> None:
        class FakeRole(SimpleNamespace):
            def __lt__(self, other: object) -> bool:
                return bool(self.below)

        role = FakeRole(permissions=SimpleNamespace(value=permissions), managed=managed, below=below)
        me = SimpleNamespace(top_role=object())
        assert views.safe_to_toggle(role, me) is expected  # type: ignore[arg-type]


def test_project_registry_is_consistent() -> None:
    slugs = [project.slug for project in PROJECTS]
    assert len(set(slugs)) == len(slugs)
    assert all(len(project.tagline) <= 180 for project in PROJECTS)
    assert len({project.colour for project in PROJECTS}) == len(PROJECTS)
    assert {role.key for role in SERVER.roles} == {project.role_key for project in PROJECTS}


def test_definition_respects_discord_naming_rules() -> None:
    keys: list[str] = [role.key for role in SERVER.roles]
    for category in SERVER.categories:
        keys.append(category.key)
        for channel in category.channels:
            keys.append(channel.key)
            assert channel.name == channel.name.lower()
            assert " " not in channel.name
            assert len(channel.topic) <= 1024
    assert len(set(keys)) == len(keys)
