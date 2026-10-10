"""Read the server, apply a plan, keep the bot's own messages current. All Discord I/O for the layout is here.

The decisions are made in `plan.py`; this module only looks and does.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence

import discord

from . import plan as planning
from .state import MessageState, State

log = logging.getLogger(__name__)

REASON = "communitybot layout"


def observe(guild: discord.Guild) -> planning.Observed:
    everyone = guild.default_role
    return planning.Observed(
        roles={role.id: role.name for role in guild.roles if not role.is_default()},
        categories={category.id: category.name for category in guild.categories},
        channels={
            channel.id: planning.ObservedChannel(
                name=channel.name,
                topic=channel.topic or "",
                category_id=channel.category_id,
                read_only=channel.overwrites_for(everyone).send_messages is False,
            )
            for channel in guild.text_channels
        },
    )


def _overwrites(
    guild: discord.Guild, read_only: bool
) -> dict[discord.Role | discord.Member | discord.Object, discord.PermissionOverwrite]:
    """Read-only: everyone reads and reacts, only the bot writes. Otherwise: no overwrites at all."""
    if not read_only:
        return {}
    return {
        guild.default_role: discord.PermissionOverwrite(
            send_messages=False,
            create_public_threads=False,
            create_private_threads=False,
            send_messages_in_threads=False,
        ),
        guild.me: discord.PermissionOverwrite(
            send_messages=True, embed_links=True, attach_files=True, manage_messages=True
        ),
    }


async def apply(
    guild: discord.Guild,
    operations: Sequence[planning.Operation],
    state: State,
    save: Callable[[], None],
) -> list[planning.Conflict]:
    """Carry out the operations in order. Every created id is saved at once, so a crash cannot orphan it."""
    conflicts: list[planning.Conflict] = []
    for operation in operations:
        if isinstance(operation, planning.Conflict):
            log.warning("layout: leaving %s alone: %s", operation.key, operation.reason)
            conflicts.append(operation)
        elif isinstance(operation, planning.CreateRole):
            role = await guild.create_role(
                name=operation.name,
                permissions=discord.Permissions.none(),
                hoist=False,
                mentionable=False,
                reason=REASON,
            )
            state.resources[operation.key] = role.id
            save()
        elif isinstance(operation, planning.RenameRole):
            existing_role = guild.get_role(operation.role_id)
            if existing_role is not None:
                await existing_role.edit(name=operation.name, reason=REASON)
        elif isinstance(operation, planning.CreateCategory):
            category = await guild.create_category(operation.name, reason=REASON)
            state.resources[operation.key] = category.id
            save()
        elif isinstance(operation, planning.RenameCategory):
            existing = guild.get_channel(operation.category_id)
            if isinstance(existing, discord.CategoryChannel):
                await existing.edit(name=operation.name, reason=REASON)
        elif isinstance(operation, planning.CreateChannel):
            parent = _category(guild, state, operation.category_key)
            if parent is None:
                log.warning("layout: no category for %s yet, skipping", operation.key)
                continue
            channel = await guild.create_text_channel(
                operation.name,
                category=parent,
                topic=operation.topic,
                overwrites=_overwrites(guild, operation.read_only),
                reason=REASON,
            )
            state.resources[operation.key] = channel.id
            save()
        else:
            await _edit_channel(guild, state, operation)
    return conflicts


async def _edit_channel(guild: discord.Guild, state: State, operation: planning.EditChannel) -> None:
    channel = guild.get_channel(operation.channel_id)
    if not isinstance(channel, discord.TextChannel):
        return
    if operation.name is not None:
        await channel.edit(name=operation.name, reason=REASON)
    if operation.topic is not None:
        await channel.edit(topic=operation.topic, reason=REASON)
    if operation.move_to_category_key is not None:
        parent = _category(guild, state, operation.move_to_category_key)
        if parent is not None:
            await channel.edit(category=parent, reason=REASON)
    if operation.read_only is not None:
        for target, overwrite in _overwrites(guild, True).items():
            if isinstance(target, discord.Role | discord.Member):
                await channel.set_permissions(
                    target, overwrite=overwrite if operation.read_only else None, reason=REASON
                )


def _category(guild: discord.Guild, state: State, key: str) -> discord.CategoryChannel | None:
    found = guild.get_channel(state.resources.get(key, 0))
    return found if isinstance(found, discord.CategoryChannel) else None


def text_channel(guild: discord.Guild, state: State, key: str) -> discord.TextChannel | None:
    """A channel the bot owns, by its key; None while it does not exist."""
    found = guild.get_channel(state.resources.get(key, 0))
    return found if isinstance(found, discord.TextChannel) else None


async def ensure_message(
    channel: discord.TextChannel,
    key: str,
    state: State,
    save: Callable[[], None],
    *,
    fingerprint: str,
    embeds: Sequence[discord.Embed],
    view: discord.ui.View | None = None,
    make_file: Callable[[], discord.File] | None = None,
    verify: bool = False,
) -> None:
    """Keep exactly one message per key: post it once, edit it when its content changed, repost if deleted.

    `verify` also checks that an unchanged message still exists; used once at start-up, because a message
    somebody deleted would otherwise stay missing until its content changes.
    """
    known = state.messages.get(key)
    if known is not None:
        unchanged = known.fingerprint == fingerprint
        if unchanged and not verify:
            return
        try:
            message = await channel.fetch_message(known.message_id)
        except discord.NotFound:
            message = None
        if message is not None and unchanged:
            return
        if message is not None:
            attachments = [make_file()] if make_file else discord.utils.MISSING
            await message.edit(embeds=list(embeds), view=view, attachments=attachments)
            state.messages[key] = MessageState(message.id, fingerprint)
            save()
            return

    files = [make_file()] if make_file else discord.utils.MISSING
    sent = await channel.send(embeds=list(embeds), view=view or discord.utils.MISSING, files=files)
    state.messages[key] = MessageState(sent.id, fingerprint)
    save()
