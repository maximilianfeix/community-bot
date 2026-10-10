"""The Discord client: lays out the server, keeps its messages current, announces releases."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from pathlib import Path

import aiohttp
import discord
from discord import app_commands
from discord.ext import tasks

from . import definition, layout, messages, releases, views
from . import plan as planning
from . import state as statefile
from .config import Settings
from .github import GitHub, GitHubError, Reply, RepoInfo
from .projects import BY_SLUG, PROJECTS, Project

log = logging.getLogger(__name__)

BANNER = Path(__file__).with_name("assets") / messages.BANNER_NAME
AVATAR = Path(__file__).with_name("assets") / "avatar.png"

WELCOME_MESSAGE = "message:welcome:2"
PROJECTS_MESSAGE = "message:projects:2"
PICKER_MESSAGE = "message:picker:2"
HELLO_MESSAGE = "message:hello:1"
ASK_MESSAGE = "message:ask:1"
CATCH_UP = "catch-up:announcements"
RETIRED_MESSAGES = ("message:welcome", "message:projects", "message:picker")
"""Keys of the embed messages the first version posted. They are deleted once and then forgotten."""
REQUIRED_PERMISSIONS = discord.Permissions(
    view_channel=True,
    send_messages=True,
    embed_links=True,
    attach_files=True,
    read_message_history=True,
    manage_messages=True,
    manage_channels=True,
    manage_roles=True,
    # The notification roles are not mentionable by members, so that nobody can ping them for fun.
    # Discord then lets only someone with this permission ping them. What the bot actually pings is
    # limited separately, by the allowed mentions on every message it sends.
    mention_everyone=True,
)
"""Exactly what the invite link in the README asks for."""

STOP_ROUND = frozenset({"rate_limit", "auth", "network"})
"""After one of these the rest of the round would fail the same way."""


class CommunityBot(discord.Client):
    def __init__(self, settings: Settings) -> None:
        # Guilds only: slash commands and buttons arrive as interactions and need no privileged intent.
        intents = discord.Intents.none()
        intents.guilds = True
        # Nothing the bot posts may ping anyone unless a call says so explicitly.
        super().__init__(intents=intents, allowed_mentions=discord.AllowedMentions.none())
        self.settings = settings
        self.state = statefile.load(settings.state_file)
        self.tree = app_commands.CommandTree(self)
        self.info: dict[str, RepoInfo] = {}
        self.latest: dict[str, releases.Release | None] = {}
        self._session: aiohttp.ClientSession | None = None
        self._github: GitHub | None = None
        self._prepared = False
        self._lock: asyncio.Lock | None = None
        register_commands(self)

    def save(self) -> None:
        statefile.save(self.settings.state_file, self.state)

    async def setup_hook(self) -> None:
        self._lock = asyncio.Lock()
        self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))
        self._github = GitHub(self._fetch, self.state.cache, self.settings.github_token)
        self.add_dynamic_items(views.NotifyButton)
        self.watch.change_interval(seconds=self.settings.poll_seconds)
        self.watch.start()

    async def close(self) -> None:
        self.watch.cancel()
        if self._session:
            await self._session.close()
        await super().close()

    async def _fetch(self, url: str, headers: Mapping[str, str]) -> Reply:
        """One GET for the GitHub client. Redirects are not followed, so the token stays with GitHub."""
        assert self._session is not None
        try:
            async with self._session.get(url, headers=headers, allow_redirects=False) as response:
                data = await response.json(content_type=None) if response.status == 200 else None
                return Reply(response.status, dict(response.headers), data)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
            raise GitHubError("network", "could not reach GitHub") from None

    async def on_ready(self) -> None:
        log.info("logged in, in %d server(s)", len(self.guilds))

    async def prepare(self, guild: discord.Guild) -> bool:
        """Commands, layout and messages. Returns False if it has to be tried again later."""
        missing = [
            name
            for name, wanted in REQUIRED_PERMISSIONS
            if wanted and not getattr(guild.me.guild_permissions, name)
        ]
        if missing:
            log.error(
                "missing permissions (%s); re-invite the bot with the link from the README",
                ", ".join(missing),
            )
            return False
        try:
            await self.tree.sync(guild=discord.Object(id=guild.id))
            await self.reconcile(guild)
        except discord.HTTPException as error:
            log.warning("set-up failed, will try again: %s", type(error).__name__)
            return False
        return True

    async def reconcile(self, guild: discord.Guild) -> None:
        """Bring roles, channels and the bot's own messages in line with `definition.SERVER`."""
        operations = planning.plan(definition.SERVER, layout.observe(guild), self.state.resources)
        await layout.apply(guild, operations, self.state, self.save)
        await layout.order_categories(
            guild, self.state, [category.key for category in definition.SERVER.categories]
        )
        await layout.tint_roles(guild, self.state, definition.SERVER.roles)
        await self._set_avatar()
        await self._update_messages(guild, verify=True)

    async def _set_avatar(self) -> None:
        """Give the bot its picture once. Avatar changes are rate limited, so a failure is only logged."""
        if self.user is None or self.user.avatar is not None or not AVATAR.exists():
            return
        try:
            await self.user.edit(avatar=AVATAR.read_bytes())
        except discord.HTTPException as error:
            log.warning("could not set the avatar: %s", type(error).__name__)

    async def _update_messages(self, guild: discord.Guild, verify: bool = False) -> None:
        channel = layout.text_channel(guild, self.state, definition.WELCOME)
        if channel is None:
            return
        # Messages from before the layout format: remove them, so the new ones appear in order.
        for old_key in RETIRED_MESSAGES:
            await layout.retire_message(channel, old_key, self.state, self.save)
        channel_ids = {
            key: self.state.resources[key]
            for key in definition.SERVER.channel_keys()
            if key in self.state.resources
        }
        has_banner = BANNER.exists()
        await layout.ensure_message(
            channel,
            WELCOME_MESSAGE,
            self.state,
            self.save,
            fingerprint=messages.fingerprint(
                messages.welcome(channel_ids, has_banner),
                extra=str(BANNER.stat().st_size) if has_banner else "",
            ),
            make_view=lambda: messages.welcome(channel_ids, has_banner),
            make_file=(lambda: discord.File(BANNER, filename=messages.BANNER_NAME)) if has_banner else None,
            verify=verify,
        )
        await layout.ensure_message(
            channel,
            PROJECTS_MESSAGE,
            self.state,
            self.save,
            fingerprint=messages.fingerprint(messages.projects(self.info, self.latest)),
            make_view=lambda: messages.projects(self.info, self.latest),
            verify=verify,
        )
        await layout.ensure_message(
            channel,
            PICKER_MESSAGE,
            self.state,
            self.save,
            fingerprint=messages.fingerprint(views.picker()),
            make_view=views.picker,
            verify=verify,
        )
        # One card at the top of each open channel, so that neither starts empty.
        for key, channel_key, make in (
            (HELLO_MESSAGE, definition.GENERAL, lambda: messages.hello(channel_ids)),
            (ASK_MESSAGE, definition.HELP, messages.ask),
        ):
            target = layout.text_channel(guild, self.state, channel_key)
            if target is not None:
                await layout.ensure_message(
                    target,
                    key,
                    self.state,
                    self.save,
                    fingerprint=messages.fingerprint(make()),
                    make_view=make,
                    verify=verify,
                )

    @tasks.loop(seconds=900)
    async def watch(self) -> None:
        """Set up if that has not worked yet; then look at GitHub, refresh the cards, announce what is new."""
        guild = self.get_guild(self.settings.guild_id)
        if guild is None:
            log.error("the bot is not a member of the configured server; invite it")
            return
        if self._lock is None or self._lock.locked():
            return
        async with self._lock:
            if not self._prepared:
                # Only marked done after it worked, so a failed start is retried on the next round
                # instead of leaving the bot connected but idle.
                self._prepared = await self.prepare(guild)
                if not self._prepared:
                    return
            try:
                await self._round(guild)
            except discord.HTTPException as error:
                log.warning("round failed on Discord's side: %s", type(error).__name__)

    @watch.before_loop
    async def _before_watch(self) -> None:
        await self.wait_until_ready()

    async def _round(self, guild: discord.Guild) -> None:
        assert self._github is not None
        complete = True
        for project in PROJECTS:
            try:
                self.info[project.slug] = await self._github.repo(project.repo)
                found = await self._github.releases(project.repo)
            except GitHubError as error:
                log.warning("github: %s: %s", project.slug, error.kind)
                complete = False
                if error.kind in STOP_ROUND:
                    break
                continue
            self.latest[project.slug] = releases.latest(found)
            await self._announce(guild, project, found)
        self.save()  # the HTTP cache changed even if nothing was announced
        if complete:
            await self._catch_up(guild)
        await self._update_messages(guild)

    async def _catch_up(self, guild: discord.Guild) -> None:
        """Once per server: post the latest release of every project, oldest first and without a ping.

        A new server has nothing to announce yet; without this, the channel would stay empty until
        the next release. Waits for a round in which every project could be read, so nothing is left out.
        """
        if CATCH_UP in self.state.done:
            return
        channel = layout.text_channel(guild, self.state, definition.ANNOUNCEMENTS)
        if channel is None:
            return
        # Remember first, then post, as with announcements: rather an incomplete list than a double one.
        self.state.done.add(CATCH_UP)
        self.save()
        found = [(item, project) for project in PROJECTS if (item := self.latest.get(project.slug))]
        found.sort(key=lambda pair: (pair[0].published_at, pair[0].id))
        for item, project in found:
            await channel.send(view=messages.release(project, item))

    async def _announce(self, guild: discord.Guild, project: Project, found: list[releases.Release]) -> None:
        repo = self.state.repo(project.slug)
        if not repo.baselined:
            repo.seen = releases.baseline(found)
            repo.baselined = True
            self.save()
            return
        channel = layout.text_channel(guild, self.state, definition.ANNOUNCEMENTS)
        if channel is None:
            return
        role = guild.get_role(self.state.resources.get(project.role_key, 0))
        for item in releases.new_releases(found, repo.seen):
            # Remember first, then post: after a crash in between, a release is skipped rather than
            # announced twice. A missed post can be made by hand; a double ping cannot be taken back.
            repo.seen.append(item.id)
            self.save()
            # Explicit on every field: AllowedMentions() on its own would allow @everyone and user pings.
            mentions = discord.AllowedMentions(
                everyone=False, users=False, roles=[role] if role else False, replied_user=False
            )
            await channel.send(
                view=messages.release(project, item, role.mention if role else ""),
                allowed_mentions=mentions,
            )
            log.info("announced a release of %s", project.slug)


def register_commands(bot: CommunityBot) -> None:
    guild = discord.Object(id=bot.settings.guild_id)
    choices = [app_commands.Choice(name=project.name, value=project.slug) for project in PROJECTS]

    @bot.tree.command(name="projects", description="All projects with stars and latest release", guild=guild)
    @app_commands.checks.cooldown(1, 5.0)
    async def projects(interaction: discord.Interaction) -> None:
        await interaction.response.send_message(view=messages.projects(bot.info, bot.latest), ephemeral=True)

    @bot.tree.command(name="project", description="One project in detail", guild=guild)
    @app_commands.describe(name="Which project")
    @app_commands.choices(name=choices)
    @app_commands.checks.cooldown(1, 5.0)
    async def project(interaction: discord.Interaction, name: app_commands.Choice[str]) -> None:
        chosen = BY_SLUG.get(name.value)
        if chosen is None:
            await interaction.response.send_message("That project is not listed.", ephemeral=True)
            return
        card = messages.project(chosen, bot.info.get(chosen.slug), bot.latest.get(chosen.slug))
        await interaction.response.send_message(view=card, ephemeral=True)

    @bot.tree.error
    async def on_error(interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        if isinstance(error, app_commands.CommandOnCooldown):
            text = "One moment, then try again."
        else:
            log.warning("command failed: %s", type(error).__name__)
            text = "That did not work."
        if not interaction.response.is_done():
            await interaction.response.send_message(text, ephemeral=True)
