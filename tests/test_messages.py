from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import discord
import pytest

from communitybot import messages, views
from communitybot.definition import SERVER
from communitybot.github import RepoInfo
from communitybot.projects import BY_SLUG, OWNER, PROJECTS
from communitybot.releases import Release

PROJECT = BY_SLUG["dejabuilt"]
CHANNELS = {key: 1000 + index for index, key in enumerate(SERVER.channel_keys())}


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


def total_length(embed: discord.Embed) -> int:
    return len(embed)


class TestWelcome:
    def test_links_every_public_channel_and_shows_the_banner(self) -> None:
        embed = messages.welcome(CHANNELS)
        where = embed.fields[0].value or ""
        assert f"<#{CHANNELS['channel:general']}>" in where
        assert f"<#{CHANNELS['channel:help']}>" in where
        assert f"<#{CHANNELS['channel:announcements']}>" in where
        assert embed.image.url == "attachment://banner.png"

    def test_lists_every_rule_numbered(self) -> None:
        rules = messages.welcome(CHANNELS).fields[1].value or ""
        assert rules.count("\n") == len(messages.RULES) - 1
        assert rules.startswith("1. ")

    def test_works_before_the_channels_exist(self) -> None:
        embed = messages.welcome({})
        assert [field.name for field in embed.fields] == ["Rules"]


class TestProjectCards:
    def test_card_with_data(self) -> None:
        card = messages.project_card(PROJECT, RepoInfo(1234, "", False), make_release())
        values = {field.name: field.value for field in card.fields}
        assert card.title == "dejabuilt"
        assert card.url == f"https://github.com/{OWNER}/dejabuilt"
        assert values["Stars"] == "1,234"
        assert (values["Latest release"] or "").startswith("[v0.2.1](https://github.com/")
        assert "<t:1791658278:R>" in (values["Latest release"] or "")

    def test_card_without_data_yet(self) -> None:
        values = {f.name: f.value for f in messages.project_card(PROJECT, None, None).fields}
        assert values["Stars"] == messages.NO_DATA
        assert values["Latest release"] == "No release yet"

    def test_one_card_per_project_within_discords_limits(self) -> None:
        cards = messages.project_cards({}, {})
        assert len(cards) == len(PROJECTS) <= 10
        assert sum(total_length(card) for card in cards) <= 6000


class TestRelease:
    def test_announcement_fields(self) -> None:
        embed = messages.release(PROJECT, make_release(name="Less environment"))
        assert embed.title == "dejabuilt v0.2.1"
        assert embed.url == make_release().url
        assert embed.author.name == "Less environment"
        assert embed.timestamp is not None
        assert embed.footer.text == "maximilianfeix/dejabuilt · full notes on GitHub"

    def test_no_author_line_when_the_name_is_just_the_tag(self) -> None:
        assert messages.release(PROJECT, make_release()).author.name is None

    def test_empty_notes_and_missing_link_have_fallbacks(self) -> None:
        embed = messages.release(PROJECT, make_release(body="", url=""))
        assert embed.description == "No release notes."
        assert embed.url == PROJECT.url

    def test_hostile_notes_cannot_ping_or_overflow(self) -> None:
        body = "@everyone <@&123> <script>x</script> [safe](https://evil.example) " + "y" * 9000
        embed = messages.release(PROJECT, make_release(body=body))
        description = embed.description or ""
        assert "@everyone" not in description
        assert "<@&123>" not in description
        assert "<script>" not in description
        assert "(https://evil.example)" in description
        assert len(description) <= messages.NOTES_LIMIT + 1
        assert total_length(embed) <= 6000

    def test_odd_timestamp_is_tolerated(self) -> None:
        assert messages.release(PROJECT, make_release(published_at="soon")).timestamp is None


class TestFingerprint:
    def test_same_content_same_fingerprint(self) -> None:
        assert messages.fingerprint([messages.picker()]) == messages.fingerprint([messages.picker()])

    def test_changes_when_content_or_extra_changes(self) -> None:
        base = messages.fingerprint(messages.project_cards({}, {}))
        with_stars = messages.fingerprint(messages.project_cards({"dejabuilt": RepoInfo(5, "", False)}, {}))
        assert base != with_stars
        assert messages.fingerprint([messages.picker()], "a") != messages.fingerprint(
            [messages.picker()], "b"
        )


class TestButtons:
    def test_one_button_per_project_with_a_stable_id(self) -> None:
        view = views.picker_view()
        ids = [getattr(getattr(child, "item", child), "custom_id", None) for child in view.children]
        assert ids == [f"community:notify:{project.slug}" for project in PROJECTS]
        assert len(ids) <= 5
        assert view.timeout is None

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
