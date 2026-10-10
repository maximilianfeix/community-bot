"""The parts that talk to Discord, driven with stand-ins. No network, no real client connection."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from communitybot import definition, layout, messages, views
from communitybot import plan as planning
from communitybot.bot import CommunityBot
from communitybot.config import Settings
from communitybot.github import GitHubError, RepoInfo
from communitybot.projects import BY_SLUG, PROJECTS
from communitybot.releases import Release
from communitybot.state import MessageState, State

GUILD_ID = 100000000000000001
PROJECT = BY_SLUG["dejabuilt"]


def not_found() -> discord.NotFound:
    return discord.NotFound(MagicMock(status=404, reason="Not Found"), "unknown message")


def http_error() -> discord.HTTPException:
    return discord.HTTPException(MagicMock(status=500, reason="Server Error"), "boom")


class FakeGuild:
    """Just enough of a guild: creates things with fresh ids and finds them again."""

    def __init__(self) -> None:
        self.id = GUILD_ID
        self.default_role = MagicMock(spec=discord.Role)
        self.me = MagicMock(spec=discord.Member)
        self.me.top_role = MagicMock()
        self._next = 100
        self.things: dict[int, Any] = {}
        self.created: list[tuple[str, str, dict[str, Any]]] = []

    def _new(self, spec: type, name: str, kind: str, **options: Any) -> Any:
        self._next += 1
        thing = MagicMock(spec=spec)
        thing.id, thing.name = self._next, name
        self.things[thing.id] = thing
        self.created.append((kind, name, options))
        return thing

    async def create_role(self, *, name: str, **options: Any) -> Any:
        return self._new(discord.Role, name, "role", **options)

    async def create_category(self, name: str, **options: Any) -> Any:
        return self._new(discord.CategoryChannel, name, "category", **options)

    async def create_text_channel(self, name: str, **options: Any) -> Any:
        return self._new(discord.TextChannel, name, "channel", **options)

    def get_role(self, role_id: int) -> Any:
        return self.things.get(role_id)

    def get_channel(self, channel_id: int) -> Any:
        return self.things.get(channel_id)


class Saves:
    def __init__(self) -> None:
        self.count = 0

    def __call__(self) -> None:
        self.count += 1


class TestApply:
    async def test_empty_server_is_built_and_every_id_is_saved_at_once(self) -> None:
        guild, state, save = FakeGuild(), State(), Saves()
        operations = planning.plan(definition.SERVER, planning.Observed(), {})
        conflicts = await layout.apply(guild, operations, state, save)  # type: ignore[arg-type]
        assert conflicts == []
        wanted = [r.key for r in definition.SERVER.roles]
        wanted += [c.key for c in definition.SERVER.categories]
        wanted += list(definition.SERVER.channel_keys())
        assert sorted(state.resources) == sorted(wanted)
        assert save.count == len(wanted)

    async def test_roles_are_created_without_any_permission(self) -> None:
        guild = FakeGuild()
        await layout.apply(guild, [planning.CreateRole("role:x", "x releases")], State(), Saves())  # type: ignore[arg-type]
        _, name, options = guild.created[0]
        assert name == "x releases"
        assert options["permissions"].value == 0
        assert options["mentionable"] is False
        assert options["hoist"] is False

    async def test_read_only_channel_denies_writing_to_everyone_but_the_bot(self) -> None:
        guild, state = FakeGuild(), State()
        operations = [
            planning.CreateCategory("category:info", "info"),
            planning.CreateChannel("channel:welcome", "category:info", "welcome", "Start", True),
            planning.CreateChannel("channel:general", "category:info", "general", "Talk", False),
        ]
        await layout.apply(guild, operations, state, Saves())  # type: ignore[arg-type]
        read_only, writable = guild.created[1][2], guild.created[2][2]
        assert read_only["overwrites"][guild.default_role].send_messages is False
        assert read_only["overwrites"][guild.me].send_messages is True
        assert read_only["category"].id == state.resources["category:info"]
        assert writable["overwrites"] == {}

    async def test_conflicts_are_reported_and_nothing_is_touched(self) -> None:
        guild, state = FakeGuild(), State()
        conflict = planning.Conflict("channel:general", "a channel named 'general' exists and is not ours")
        assert await layout.apply(guild, [conflict], state, Saves()) == [conflict]  # type: ignore[arg-type]
        assert guild.created == []
        assert state.resources == {}

    async def test_channel_without_its_category_is_skipped_not_misplaced(self) -> None:
        guild, state = FakeGuild(), State()
        operation = planning.CreateChannel("channel:welcome", "category:missing", "welcome", "Start", True)
        await layout.apply(guild, [operation], state, Saves())  # type: ignore[arg-type]
        assert guild.created == []

    async def test_owned_things_are_edited_by_id(self) -> None:
        guild, state = FakeGuild(), State()
        await layout.apply(
            guild,  # type: ignore[arg-type]
            [
                planning.CreateRole("role:x", "old"),
                planning.CreateCategory("category:info", "old"),
                planning.CreateChannel("channel:welcome", "category:info", "old", "old", False),
            ],
            state,
            Saves(),
        )
        role = guild.get_role(state.resources["role:x"])
        category = guild.get_channel(state.resources["category:info"])
        channel = guild.get_channel(state.resources["channel:welcome"])
        await layout.apply(
            guild,  # type: ignore[arg-type]
            [
                planning.RenameRole("role:x", role.id, "new"),
                planning.RenameCategory("category:info", category.id, "new"),
                planning.EditChannel(
                    "channel:welcome",
                    channel.id,
                    name="welcome",
                    topic="Start",
                    read_only=True,
                    move_to_category_key="category:info",
                ),
            ],
            state,
            Saves(),
        )
        role.edit.assert_awaited_once()
        category.edit.assert_awaited_once()
        assert channel.edit.await_count == 3
        assert channel.set_permissions.await_count == 2

    async def test_edits_for_things_that_vanished_do_nothing(self) -> None:
        guild = FakeGuild()
        operations = [
            planning.RenameRole("role:x", 1, "n"),
            planning.RenameCategory("category:info", 2, "n"),
            planning.EditChannel("channel:welcome", 3, name="n"),
        ]
        assert await layout.apply(guild, operations, State(), Saves()) == []  # type: ignore[arg-type]


def test_observe_reads_names_topics_and_read_only_state() -> None:
    guild = MagicMock(spec=discord.Guild)
    role, everyone = MagicMock(), MagicMock()
    role.id, role.name = 5, "x releases"
    role.is_default.return_value, everyone.is_default.return_value = False, True
    category = MagicMock()
    category.id, category.name = 20, "info"
    channel = MagicMock()
    channel.id, channel.name, channel.topic, channel.category_id = 30, "welcome", None, 20
    channel.overwrites_for.side_effect = lambda target: MagicMock(send_messages=target is not everyone)
    guild.roles, guild.categories, guild.text_channels = [everyone, role], [category], [channel]
    guild.default_role = everyone
    seen = layout.observe(guild)
    assert seen.roles == {5: "x releases"}
    assert seen.categories == {20: "info"}
    assert seen.channels == {30: planning.ObservedChannel("welcome", "", 20, True)}


class TestEnsureMessage:
    def channel(self, *, existing: Any = None, missing: bool = False) -> MagicMock:
        channel = MagicMock(spec=discord.TextChannel)
        channel.send = AsyncMock(return_value=MagicMock(id=900))
        channel.fetch_message = AsyncMock(side_effect=not_found() if missing else None, return_value=existing)
        return channel

    async def run(self, channel: MagicMock, state: State, fingerprint: str, verify: bool = False) -> None:
        await layout.ensure_message(
            channel,
            "message:x",
            state,
            Saves(),
            fingerprint=fingerprint,
            make_view=views.picker,
            verify=verify,
        )

    async def test_first_time_it_is_posted_and_remembered(self) -> None:
        channel, state = self.channel(), State()
        await self.run(channel, state, "f1")
        channel.send.assert_awaited_once()
        assert state.messages["message:x"] == MessageState(900, "f1")

    async def test_unchanged_message_costs_no_request(self) -> None:
        channel, state = self.channel(), State(messages={"message:x": MessageState(7, "f1")})
        await self.run(channel, state, "f1")
        channel.fetch_message.assert_not_awaited()
        channel.send.assert_not_awaited()

    async def test_changed_content_edits_the_same_message(self) -> None:
        existing = MagicMock(id=7)
        existing.edit = AsyncMock()
        channel, state = self.channel(existing=existing), State(messages={"message:x": MessageState(7, "f1")})
        await self.run(channel, state, "f2")
        existing.edit.assert_awaited_once()
        channel.send.assert_not_awaited()
        assert state.messages["message:x"] == MessageState(7, "f2")

    async def test_deleted_message_is_posted_again(self) -> None:
        channel, state = self.channel(missing=True), State(messages={"message:x": MessageState(7, "f1")})
        await self.run(channel, state, "f2")
        channel.send.assert_awaited_once()
        assert state.messages["message:x"] == MessageState(900, "f2")

    async def test_verify_finds_a_deleted_message_even_when_nothing_changed(self) -> None:
        channel, state = self.channel(missing=True), State(messages={"message:x": MessageState(7, "f1")})
        await self.run(channel, state, "f1", verify=True)
        channel.send.assert_awaited_once()

    async def test_verify_leaves_an_existing_unchanged_message_alone(self) -> None:
        existing = MagicMock(id=7)
        existing.edit = AsyncMock()
        channel, state = self.channel(existing=existing), State(messages={"message:x": MessageState(7, "f1")})
        await self.run(channel, state, "f1", verify=True)
        existing.edit.assert_not_awaited()
        channel.send.assert_not_awaited()


def make_bot(tmp_path: Path) -> CommunityBot:
    return CommunityBot(Settings(token="t", guild_id=GUILD_ID, state_file=tmp_path / "state.json"))


def make_release(release_id: int, **changes: Any) -> Release:
    fields: dict[str, Any] = {
        "id": release_id,
        "tag": f"v{release_id}",
        "name": f"v{release_id}",
        "url": f"https://github.com/maximilianfeix/dejabuilt/releases/tag/v{release_id}",
        "published_at": f"2026-10-{release_id:02d}T10:00:00Z",
        "body": "notes",
    }
    return Release(**{**fields, **changes})


class TestToggle:
    def setup(self, tmp_path: Path, *, has_role: bool, permissions: int = 0) -> tuple[Any, Any, Any]:
        bot = make_bot(tmp_path)
        bot.state.resources[PROJECT.role_key] = 55
        guild = FakeGuild()
        role = MagicMock(spec=discord.Role)
        role.permissions.value, role.managed = permissions, False
        role.__lt__.return_value = True
        guild.things[55] = role
        member = MagicMock(spec=discord.Member)
        member.roles = [role] if has_role else []
        member.add_roles, member.remove_roles = AsyncMock(), AsyncMock()
        interaction = MagicMock(guild=guild, user=member)
        return bot, interaction, member

    async def test_adds_the_role(self, tmp_path: Path) -> None:
        bot, interaction, member = self.setup(tmp_path, has_role=False)
        answer = await views.toggle(bot, interaction, "dejabuilt")
        member.add_roles.assert_awaited_once()
        assert "pinged" in answer

    async def test_removes_the_role(self, tmp_path: Path) -> None:
        bot, interaction, member = self.setup(tmp_path, has_role=True)
        answer = await views.toggle(bot, interaction, "dejabuilt")
        member.remove_roles.assert_awaited_once()
        assert "are off" in answer

    async def test_refuses_a_role_that_carries_permissions(self, tmp_path: Path) -> None:
        bot, interaction, member = self.setup(tmp_path, has_role=False, permissions=8)
        answer = await views.toggle(bot, interaction, "dejabuilt")
        member.add_roles.assert_not_awaited()
        assert "not set up" in answer

    async def test_refuses_clicks_from_another_server(self, tmp_path: Path) -> None:
        bot, interaction, member = self.setup(tmp_path, has_role=False)
        interaction.guild.id = 1
        assert "inside the server" in await views.toggle(bot, interaction, "dejabuilt")
        member.add_roles.assert_not_awaited()

    @pytest.mark.parametrize("slug", ["unknown", "../etc", ""])
    async def test_refuses_unknown_projects(self, tmp_path: Path, slug: str) -> None:
        bot, interaction, member = self.setup(tmp_path, has_role=False)
        assert "no longer listed" in await views.toggle(bot, interaction, slug)
        member.add_roles.assert_not_awaited()

    async def test_role_not_created_yet(self, tmp_path: Path) -> None:
        bot, interaction, _ = self.setup(tmp_path, has_role=False)
        bot.state.resources.clear()
        assert "not set up" in await views.toggle(bot, interaction, "dejabuilt")

    async def test_discord_error_gives_a_plain_answer(self, tmp_path: Path) -> None:
        bot, interaction, member = self.setup(tmp_path, has_role=False)
        member.add_roles.side_effect = http_error()
        assert "did not work" in await views.toggle(bot, interaction, "dejabuilt")


class TestAnnounce:
    def guild_with_channel(self, bot: CommunityBot) -> tuple[FakeGuild, MagicMock, MagicMock]:
        guild = FakeGuild()
        channel = MagicMock(spec=discord.TextChannel)
        channel.send = AsyncMock()
        role = MagicMock(spec=discord.Role)
        role.mention = "<@&77>"
        guild.things[66], guild.things[77] = channel, role
        bot.state.resources[definition.ANNOUNCEMENTS] = 66
        bot.state.resources[PROJECT.role_key] = 77
        return guild, channel, role

    async def test_first_look_is_a_baseline_and_pings_nobody(self, tmp_path: Path) -> None:
        bot = make_bot(tmp_path)
        guild, channel, _ = self.guild_with_channel(bot)
        await bot._announce(guild, PROJECT, [make_release(1), make_release(2)])  # type: ignore[arg-type]
        assert all("allowed_mentions" not in call.kwargs for call in channel.send.await_args_list)
        assert bot.state.repo("dejabuilt").baselined is True
        assert bot.state.repo("dejabuilt").seen == [1, 2]

    async def test_new_release_is_announced_once_with_only_its_role_pinged(self, tmp_path: Path) -> None:
        bot = make_bot(tmp_path)
        guild, channel, role = self.guild_with_channel(bot)
        await bot._announce(guild, PROJECT, [make_release(1)])  # type: ignore[arg-type]
        channel.send.reset_mock()
        found = [make_release(2, body="@everyone new"), make_release(1)]
        await bot._announce(guild, PROJECT, found)  # type: ignore[arg-type]
        await bot._announce(guild, PROJECT, found)  # type: ignore[arg-type]
        channel.send.assert_awaited_once()
        sent = channel.send.await_args.kwargs
        assert "content" not in sent
        assert "embed" not in sent
        shown = messages.text_of(sent["view"])
        assert shown.count("<@&77>") == 1
        assert sent["allowed_mentions"].roles == [role]
        assert sent["allowed_mentions"].everyone is False
        assert sent["allowed_mentions"].users is False
        assert sent["allowed_mentions"].to_dict() == {"parse": [], "roles": [role.id]}
        assert "@everyone" not in shown
        assert bot.state.repo("dejabuilt").seen == [1, 2]

    async def test_release_is_remembered_before_it_is_posted(self, tmp_path: Path) -> None:
        bot = make_bot(tmp_path)
        guild, channel, _ = self.guild_with_channel(bot)
        await bot._announce(guild, PROJECT, [])  # type: ignore[arg-type]
        channel.send.side_effect = http_error()
        with pytest.raises(discord.HTTPException):
            await bot._announce(guild, PROJECT, [make_release(3)])  # type: ignore[arg-type]
        assert 3 in bot.state.repo("dejabuilt").seen
        assert 3 in CommunityBot(bot.settings).state.repo("dejabuilt").seen

    async def test_without_the_role_nobody_is_pinged(self, tmp_path: Path) -> None:
        bot = make_bot(tmp_path)
        guild, channel, _ = self.guild_with_channel(bot)
        del guild.things[77]
        await bot._announce(guild, PROJECT, [])  # type: ignore[arg-type]
        await bot._announce(guild, PROJECT, [make_release(4)])  # type: ignore[arg-type]
        sent = channel.send.await_args.kwargs
        assert "<@" not in messages.text_of(sent["view"])
        assert sent["allowed_mentions"].to_dict() == {"parse": []}

    async def test_without_the_channel_the_release_stays_unannounced(self, tmp_path: Path) -> None:
        bot = make_bot(tmp_path)
        guild, _, _ = self.guild_with_channel(bot)
        await bot._announce(guild, PROJECT, [])  # type: ignore[arg-type]
        del guild.things[66]
        await bot._announce(guild, PROJECT, [make_release(5)])  # type: ignore[arg-type]
        assert bot.state.repo("dejabuilt").seen == []


class FakeGitHub:
    def __init__(self, fail_on: str | None = None, kind: str = "server") -> None:
        self.fail_on, self.kind = fail_on, kind
        self.asked: list[str] = []

    async def repo(self, repo: str) -> RepoInfo:
        self.asked.append(repo)
        if self.fail_on and repo.endswith(self.fail_on):
            raise GitHubError(self.kind, "x")
        return RepoInfo(7, "", False)

    async def releases(self, repo: str) -> list[Release]:
        return [make_release(1)]


class TestRound:
    async def run(self, tmp_path: Path, github: FakeGitHub) -> CommunityBot:
        bot = make_bot(tmp_path)
        bot._github = github  # type: ignore[assignment]
        bot._update_messages = AsyncMock()  # type: ignore[method-assign]
        await bot._round(FakeGuild())  # type: ignore[arg-type]
        return bot

    async def test_every_project_is_read_and_the_cards_are_refreshed(self, tmp_path: Path) -> None:
        bot = await self.run(tmp_path, FakeGitHub())
        assert set(bot.info) == {p.slug for p in PROJECTS}
        assert all(release is not None for release in bot.latest.values())
        bot._update_messages.assert_awaited_once()  # type: ignore[attr-defined]
        assert (tmp_path / "state.json").exists()

    async def test_one_failing_repository_does_not_stop_the_others(self, tmp_path: Path) -> None:
        bot = await self.run(tmp_path, FakeGitHub(fail_on="dejabuilt", kind="not_found"))
        assert "dejabuilt" not in bot.info
        assert len(bot.info) == len(PROJECTS) - 1

    @pytest.mark.parametrize("kind", ["rate_limit", "auth", "network"])
    async def test_a_failure_that_would_repeat_ends_the_round(self, tmp_path: Path, kind: str) -> None:
        github = FakeGitHub(fail_on=PROJECTS[1].slug, kind=kind)
        bot = await self.run(tmp_path, github)
        assert len(github.asked) == 2
        assert list(bot.info) == [PROJECTS[0].slug]


async def test_bot_never_pings_by_default_and_asks_for_no_privileged_intent(tmp_path: Path) -> None:
    bot = make_bot(tmp_path)
    assert bot.allowed_mentions is not None
    assert bot.allowed_mentions.everyone is False
    assert bot.allowed_mentions.roles is False
    assert bot.allowed_mentions.users is False
    assert bot.intents.guilds is True
    assert bot.intents.members is False
    assert bot.intents.message_content is False
    assert bot.intents.presences is False
    assert {command.name for command in bot.tree.get_commands(guild=discord.Object(id=GUILD_ID))} == {
        "projects",
        "project",
    }


class TestPrepare:
    def guild(self, permissions: discord.Permissions) -> MagicMock:
        guild = MagicMock(spec=discord.Guild)
        guild.id = GUILD_ID
        guild.me.guild_permissions = permissions
        return guild

    def bot(self, tmp_path: Path) -> CommunityBot:
        bot = make_bot(tmp_path)
        bot.tree.sync = AsyncMock()  # type: ignore[method-assign]
        bot.reconcile = AsyncMock()  # type: ignore[method-assign]
        return bot

    async def test_succeeds_with_the_documented_permissions(self, tmp_path: Path) -> None:
        from communitybot.bot import REQUIRED_PERMISSIONS

        bot = self.bot(tmp_path)
        assert await bot.prepare(self.guild(REQUIRED_PERMISSIONS)) is True
        bot.tree.sync.assert_awaited_once()  # type: ignore[attr-defined]
        bot.reconcile.assert_awaited_once()  # type: ignore[attr-defined]

    async def test_missing_permission_is_reported_and_nothing_is_changed(self, tmp_path: Path) -> None:
        from communitybot.bot import REQUIRED_PERMISSIONS

        lacking = discord.Permissions(REQUIRED_PERMISSIONS.value)
        lacking.manage_roles = False
        bot = self.bot(tmp_path)
        assert await bot.prepare(self.guild(lacking)) is False
        bot.reconcile.assert_not_awaited()  # type: ignore[attr-defined]

    async def test_failure_on_discords_side_means_try_again(self, tmp_path: Path) -> None:
        from communitybot.bot import REQUIRED_PERMISSIONS

        bot = self.bot(tmp_path)
        bot.reconcile.side_effect = http_error()  # type: ignore[attr-defined]
        assert await bot.prepare(self.guild(REQUIRED_PERMISSIONS)) is False


def test_invite_link_in_the_readme_asks_for_exactly_the_required_permissions() -> None:
    from communitybot.bot import REQUIRED_PERMISSIONS

    readme = (Path(__file__).resolve().parent.parent / "README.md").read_text(encoding="utf-8")
    assert f"permissions={REQUIRED_PERMISSIONS.value}" in readme
    assert REQUIRED_PERMISSIONS.administrator is False
    assert REQUIRED_PERMISSIONS.manage_guild is False
    assert REQUIRED_PERMISSIONS.manage_webhooks is False
    assert REQUIRED_PERMISSIONS.kick_members is False
    assert REQUIRED_PERMISSIONS.ban_members is False


async def test_button_acknowledges_before_it_changes_the_role(tmp_path: Path) -> None:
    order: list[str] = []
    bot = make_bot(tmp_path)
    interaction = MagicMock()
    interaction.client = bot
    interaction.guild = None
    interaction.response.defer = AsyncMock(side_effect=lambda **_: order.append("defer"))
    interaction.followup.send = AsyncMock(side_effect=lambda *_, **__: order.append("answer"))
    await views.NotifyButton("dejabuilt").callback(interaction)
    assert order == ["defer", "answer"]
    assert interaction.response.defer.await_args.kwargs["ephemeral"] is True
    assert interaction.followup.send.await_args.kwargs["ephemeral"] is True


class TestRetireMessage:
    async def test_old_message_is_deleted_and_forgotten(self) -> None:
        old = MagicMock(id=7)
        old.delete = AsyncMock()
        channel = MagicMock(spec=discord.TextChannel)
        channel.fetch_message = AsyncMock(return_value=old)
        state, save = State(messages={"message:welcome": MessageState(7, "f")}), Saves()
        await layout.retire_message(channel, "message:welcome", state, save)
        old.delete.assert_awaited_once()
        assert state.messages == {}
        assert save.count == 1

    async def test_message_that_is_already_gone_is_just_forgotten(self) -> None:
        channel = MagicMock(spec=discord.TextChannel)
        channel.fetch_message = AsyncMock(side_effect=not_found())
        state = State(messages={"message:welcome": MessageState(7, "f")})
        await layout.retire_message(channel, "message:welcome", state, Saves())
        assert state.messages == {}

    async def test_unknown_key_costs_no_request(self) -> None:
        channel = MagicMock(spec=discord.TextChannel)
        channel.fetch_message = AsyncMock()
        save = Saves()
        await layout.retire_message(channel, "message:nope", State(), save)
        channel.fetch_message.assert_not_awaited()
        assert save.count == 0


class TestOrderCategories:
    def guild_with(self, positions: dict[str, int]) -> tuple[FakeGuild, State, dict[str, Any]]:
        guild, state, categories = FakeGuild(), State(), {}
        for index, (key, position) in enumerate(positions.items()):
            category = MagicMock(spec=discord.CategoryChannel)
            category.position = position
            guild.things[500 + index] = category
            state.resources[key] = 500 + index
            categories[key] = category
        return guild, state, categories

    async def test_owned_categories_are_moved_to_the_top_in_order(self) -> None:
        guild, state, categories = self.guild_with({"category:info": 3, "category:community": 4})
        await layout.order_categories(guild, state, ["category:info", "category:community"])  # type: ignore[arg-type]
        assert categories["category:info"].edit.await_args.kwargs["position"] == 0
        assert categories["category:community"].edit.await_args.kwargs["position"] == 1

    async def test_categories_already_in_place_are_not_edited(self) -> None:
        guild, state, categories = self.guild_with({"category:info": 0, "category:community": 1})
        await layout.order_categories(guild, state, ["category:info", "category:community"])  # type: ignore[arg-type]
        categories["category:info"].edit.assert_not_awaited()
        categories["category:community"].edit.assert_not_awaited()

    async def test_missing_category_is_skipped(self) -> None:
        guild, state, categories = self.guild_with({"category:info": 5})
        await layout.order_categories(guild, state, ["category:gone", "category:info"])  # type: ignore[arg-type]
        assert categories["category:info"].edit.await_args.kwargs["position"] == 1


class TestAvatar:
    def bot_with_user(self, tmp_path: Path, avatar: object) -> tuple[CommunityBot, MagicMock]:
        bot = make_bot(tmp_path)
        user = MagicMock()
        user.avatar = avatar
        user.edit = AsyncMock()
        bot._connection.user = user
        return bot, user

    async def test_set_once_when_the_bot_has_none(self, tmp_path: Path) -> None:
        bot, user = self.bot_with_user(tmp_path, None)
        await bot._set_avatar()
        user.edit.assert_awaited_once()
        assert user.edit.await_args.kwargs["avatar"].startswith(b"\x89PNG")

    async def test_existing_avatar_is_left_alone(self, tmp_path: Path) -> None:
        bot, user = self.bot_with_user(tmp_path, object())
        await bot._set_avatar()
        user.edit.assert_not_awaited()

    async def test_rate_limit_is_only_logged(self, tmp_path: Path) -> None:
        bot, user = self.bot_with_user(tmp_path, None)
        user.edit.side_effect = http_error()
        await bot._set_avatar()


async def test_messages_are_posted_as_layouts_and_old_embed_messages_are_retired(tmp_path: Path) -> None:
    bot = make_bot(tmp_path)
    guild = FakeGuild()
    channel = MagicMock(spec=discord.TextChannel)
    old = MagicMock()
    old.delete = AsyncMock()
    channel.fetch_message = AsyncMock(return_value=old)
    counter = iter(range(900, 999))
    channel.send = AsyncMock(side_effect=lambda **_: MagicMock(id=next(counter)))
    guild.things[66] = channel
    bot.state.resources[definition.WELCOME] = 66
    bot.state.messages["message:welcome"] = MessageState(1, "old")
    bot.state.messages["message:projects"] = MessageState(2, "old")
    bot.state.messages["message:picker"] = MessageState(3, "old")

    await bot._update_messages(guild)  # type: ignore[arg-type]

    assert old.delete.await_count == 3
    assert sorted(bot.state.messages) == ["message:picker:2", "message:projects:2", "message:welcome:2"]
    assert channel.send.await_count == 3
    for call in channel.send.await_args_list:
        assert isinstance(call.kwargs["view"], discord.ui.LayoutView)
        assert "embeds" not in call.kwargs
    assert channel.send.await_args_list[0].kwargs["files"][0].filename == "banner.png"

    await bot._update_messages(guild)  # type: ignore[arg-type]
    assert channel.send.await_count == 3  # nothing changed, nothing is sent again


class TestTintRoles:
    def guild_with_role(self, colour: int) -> tuple[FakeGuild, State, MagicMock]:
        guild, state = FakeGuild(), State()
        role = MagicMock(spec=discord.Role)
        role.colour = discord.Colour(colour)
        guild.things[41] = role
        state.resources[PROJECT.role_key] = 41
        return guild, state, role

    async def test_owned_role_gets_the_colour(self) -> None:
        guild, state, role = self.guild_with_role(0)
        await layout.tint_roles(guild, state, definition.SERVER.roles)  # type: ignore[arg-type]
        assert role.edit.await_args.kwargs["colour"].value == definition.ROLE_COLOUR

    async def test_role_with_the_right_colour_is_not_edited(self) -> None:
        guild, state, role = self.guild_with_role(definition.ROLE_COLOUR)
        await layout.tint_roles(guild, state, definition.SERVER.roles)  # type: ignore[arg-type]
        role.edit.assert_not_awaited()


class TestStarterCards:
    async def test_open_channels_get_one_card_each_and_keep_it(self, tmp_path: Path) -> None:
        bot = make_bot(tmp_path)
        guild = FakeGuild()
        channels = {}
        for index, key in enumerate((definition.WELCOME, definition.GENERAL, definition.HELP)):
            channel = MagicMock(spec=discord.TextChannel)
            channel.send = AsyncMock(return_value=MagicMock(id=700 + index))
            guild.things[60 + index] = channel
            bot.state.resources[key] = 60 + index
            channels[key] = channel

        await bot._update_messages(guild)  # type: ignore[arg-type]
        await bot._update_messages(guild)  # type: ignore[arg-type]

        general, help_channel = channels[definition.GENERAL], channels[definition.HELP]
        assert general.send.await_count == 1
        assert help_channel.send.await_count == 1
        assert "<#62>" in messages.text_of(general.send.await_args.kwargs["view"])
        assert "Asking for help" in messages.text_of(help_channel.send.await_args.kwargs["view"])


class TestCatchUp:
    def bot_with_channel(self, tmp_path: Path) -> tuple[CommunityBot, FakeGuild, MagicMock]:
        bot, guild = make_bot(tmp_path), FakeGuild()
        channel = MagicMock(spec=discord.TextChannel)
        channel.send = AsyncMock()
        guild.things[55] = channel
        bot.state.resources[definition.ANNOUNCEMENTS] = 55
        return bot, guild, channel

    async def test_first_look_shows_the_latest_release_once_without_a_ping(self, tmp_path: Path) -> None:
        bot, guild, channel = self.bot_with_channel(tmp_path)
        found = [make_release(1), make_release(2)]
        await bot._announce(guild, PROJECT, found)  # type: ignore[arg-type]
        await bot._announce(guild, PROJECT, found)  # type: ignore[arg-type]

        assert channel.send.await_count == 1
        sent = channel.send.await_args.kwargs
        assert messages.text_of(sent["view"]).startswith("## dejabuilt v2")
        assert "<@" not in messages.text_of(sent["view"])
        assert "allowed_mentions" not in sent

    async def test_it_is_remembered_across_a_restart(self, tmp_path: Path) -> None:
        bot, guild, channel = self.bot_with_channel(tmp_path)
        await bot._announce(guild, PROJECT, [make_release(1)])  # type: ignore[arg-type]
        again = make_bot(tmp_path)
        await again._announce(guild, PROJECT, [make_release(1)])  # type: ignore[arg-type]
        assert channel.send.await_count == 1

    async def test_a_release_that_is_announced_is_not_shown_a_second_time(self, tmp_path: Path) -> None:
        # An installation from before this job existed, with a release waiting.
        bot, guild, channel = self.bot_with_channel(tmp_path)
        repo = bot.state.repo(PROJECT.slug)
        repo.baselined, repo.seen = True, [1]
        found = [make_release(1), make_release(2)]
        await bot._announce(guild, PROJECT, found)  # type: ignore[arg-type]
        await bot._announce(guild, PROJECT, found)  # type: ignore[arg-type]
        assert channel.send.await_count == 1
        assert "allowed_mentions" in channel.send.await_args.kwargs

    async def test_project_without_a_release_shows_nothing_and_is_done(self, tmp_path: Path) -> None:
        bot, guild, channel = self.bot_with_channel(tmp_path)
        await bot._announce(guild, PROJECT, [])  # type: ignore[arg-type]
        channel.send.assert_not_awaited()
        assert bot.state.done == {"catch-up:dejabuilt"}

    async def test_without_the_channel_it_waits(self, tmp_path: Path) -> None:
        bot = make_bot(tmp_path)
        await bot._announce(FakeGuild(), PROJECT, [make_release(1)])  # type: ignore[arg-type]
        assert bot.state.done == set()
