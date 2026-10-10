"""Work out what has to change on the server. Pure: data in, a list of operations out.

The bot owns only what it created, and it knows what it created by id, from its state file. A channel that
merely has the right name is someone else's: the plan reports a conflict and leaves it alone. Nothing is ever
deleted.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from .definition import ServerSpec


@dataclass(frozen=True)
class ObservedChannel:
    name: str
    topic: str
    category_id: int | None
    read_only: bool


@dataclass(frozen=True)
class Observed:
    """The parts of the server the plan needs, keyed by Discord id."""

    roles: Mapping[int, str] = field(default_factory=dict)
    categories: Mapping[int, str] = field(default_factory=dict)
    channels: Mapping[int, ObservedChannel] = field(default_factory=dict)


@dataclass(frozen=True)
class CreateRole:
    key: str
    name: str


@dataclass(frozen=True)
class RenameRole:
    key: str
    role_id: int
    name: str


@dataclass(frozen=True)
class CreateCategory:
    key: str
    name: str


@dataclass(frozen=True)
class RenameCategory:
    key: str
    category_id: int
    name: str


@dataclass(frozen=True)
class CreateChannel:
    key: str
    category_key: str
    name: str
    topic: str
    read_only: bool


@dataclass(frozen=True)
class EditChannel:
    """Bring an owned channel back in line. Only the listed fields are changed."""

    key: str
    channel_id: int
    name: str | None = None
    topic: str | None = None
    read_only: bool | None = None
    move_to_category_key: str | None = None


@dataclass(frozen=True)
class Conflict:
    """Something the bot will not touch, with the reason, for the log."""

    key: str
    reason: str


Operation = CreateRole | RenameRole | CreateCategory | RenameCategory | CreateChannel | EditChannel | Conflict


def plan(spec: ServerSpec, observed: Observed, owned: Mapping[str, int]) -> list[Operation]:
    """Operations that turn the observed server into the specified one, in the order they must run."""
    operations: list[Operation] = []
    owned_ids = set(owned.values())

    for role in spec.roles:
        role_id = owned.get(role.key)
        if role_id is not None and role_id in observed.roles:
            if observed.roles[role_id] != role.name:
                operations.append(RenameRole(role.key, role_id, role.name))
        elif _taken(role.name, observed.roles, owned_ids):
            operations.append(Conflict(role.key, f"a role named '{role.name}' exists and is not ours"))
        else:
            operations.append(CreateRole(role.key, role.name))

    for category in spec.categories:
        category_id = owned.get(category.key)
        if category_id is not None and category_id in observed.categories:
            if observed.categories[category_id] != category.name:
                operations.append(RenameCategory(category.key, category_id, category.name))
        elif _taken(category.name, observed.categories, owned_ids):
            reason = f"a category named '{category.name}' exists and is not ours"
            operations.append(Conflict(category.key, reason))
            operations.extend(
                Conflict(channel.key, f"its category '{category.name}' is not ours")
                for channel in category.channels
            )
            continue
        else:
            operations.append(CreateCategory(category.key, category.name))
            category_id = None

        for channel in category.channels:
            channel_id = owned.get(channel.key)
            current = observed.channels.get(channel_id) if channel_id is not None else None
            if channel_id is not None and current is not None:
                edit = EditChannel(
                    key=channel.key,
                    channel_id=channel_id,
                    name=channel.name if current.name != channel.name else None,
                    topic=channel.topic if current.topic != channel.topic else None,
                    read_only=channel.read_only if current.read_only != channel.read_only else None,
                    move_to_category_key=(
                        category.key if category_id is None or current.category_id != category_id else None
                    ),
                )
                if edit != EditChannel(channel.key, channel_id):
                    operations.append(edit)
            elif _taken(channel.name, _names(observed.channels), owned_ids):
                reason = f"a channel named '{channel.name}' exists and is not ours"
                operations.append(Conflict(channel.key, reason))
            else:
                operations.append(
                    CreateChannel(channel.key, category.key, channel.name, channel.topic, channel.read_only)
                )
    return operations


def _names(channels: Mapping[int, ObservedChannel]) -> dict[int, str]:
    return {channel_id: channel.name for channel_id, channel in channels.items()}


def _taken(name: str, existing: Mapping[int, str], owned_ids: set[int]) -> bool:
    """True if something we do not own already carries this name."""
    wanted = name.casefold()
    return any(
        other.casefold() == wanted and other_id not in owned_ids for other_id, other in existing.items()
    )
