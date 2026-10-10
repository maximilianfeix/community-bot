"""The buttons under "Release notifications". They keep working after a restart.

Each button carries the project in its custom id. Discord sends that id back on a click, so nothing about
the button has to be remembered. The role comes from the state file, never from the click.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

import discord

from .projects import BY_SLUG, PROJECTS

if TYPE_CHECKING:
    from .bot import CommunityBot

log = logging.getLogger(__name__)

PREFIX = "community:notify:"


def safe_to_toggle(role: discord.Role, me: discord.Member) -> bool:
    """Only a plain notification role may be handed out: no permissions, not managed, below the bot."""
    return role.permissions.value == 0 and not role.managed and role < me.top_role


class NotifyButton(
    discord.ui.DynamicItem[discord.ui.Button[Any]],
    template=r"community:notify:(?P<slug>[a-z0-9-]{1,40})",
):
    def __init__(self, slug: str) -> None:
        project = BY_SLUG.get(slug)
        super().__init__(
            discord.ui.Button(
                label=project.name if project else slug,
                style=discord.ButtonStyle.secondary,
                custom_id=f"{PREFIX}{slug}",
            )
        )
        self.slug = slug

    @classmethod
    async def from_custom_id(
        cls, interaction: discord.Interaction, item: discord.ui.Item[Any], match: re.Match[str]
    ) -> NotifyButton:
        return cls(match["slug"])

    async def callback(self, interaction: discord.Interaction) -> None:
        bot: CommunityBot = interaction.client  # type: ignore[assignment]
        # Acknowledge first: Discord gives three seconds, and changing a role can take longer. Answering
        # late would show "interaction failed" although the role changed, and invite a second click.
        await interaction.response.defer(ephemeral=True, thinking=True)
        await interaction.followup.send(await toggle(bot, interaction, self.slug), ephemeral=True)


async def toggle(bot: CommunityBot, interaction: discord.Interaction, slug: str) -> str:
    """Add or remove the project's notification role for whoever clicked. Returns the answer text."""
    guild, member, project = interaction.guild, interaction.user, BY_SLUG.get(slug)
    if guild is None or guild.id != bot.settings.guild_id or not isinstance(member, discord.Member):
        return "This only works inside the server."
    if project is None:
        return "That project is no longer listed."
    role = guild.get_role(bot.state.resources.get(project.role_key, 0))
    if role is None or not safe_to_toggle(role, guild.me):
        log.warning("notification role for %s is missing or not safe to hand out", slug)
        return "Notifications for this project are not set up right now."
    try:
        if role in member.roles:
            await member.remove_roles(role, reason="release notifications off")
            return f"Release notifications for **{project.name}** are off."
        await member.add_roles(role, reason="release notifications on")
        return f"You will be pinged when **{project.name}** ships a release."
    except discord.HTTPException:
        log.warning("could not change the notification role for %s", slug)
        return "That did not work. Please try again in a moment."


def picker_view() -> discord.ui.View:
    """One button per project, in the order of the project list."""
    view = discord.ui.View(timeout=None)
    for project in PROJECTS:
        view.add_item(NotifyButton(project.slug))
    return view
