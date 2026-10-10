"""What the server should look like. Change this file and the bot changes the server on its next start.

Channel names carry an emoji and a dot, so the list reads at a glance.

Deliberately small: an empty server with a dozen silent channels looks dead. One place to read, one place to
talk, one place to ask. Add a channel here when a conversation keeps happening that has no home.
"""

from __future__ import annotations

from dataclasses import dataclass

from .projects import PROJECTS

ACCENT = 0xD4F77A
"""The colour of the server itself. Each project has its own next to it."""


@dataclass(frozen=True)
class RoleSpec:
    key: str
    name: str
    colour: int
    """Shown wherever the role is mentioned, so a release ping is recognisable at a glance."""


@dataclass(frozen=True)
class ChannelSpec:
    key: str
    name: str
    topic: str
    read_only: bool = False
    """Only the bot writes here; everyone can read and react."""


@dataclass(frozen=True)
class CategorySpec:
    key: str
    name: str
    channels: tuple[ChannelSpec, ...]


@dataclass(frozen=True)
class ServerSpec:
    roles: tuple[RoleSpec, ...]
    categories: tuple[CategorySpec, ...]

    def channel_keys(self) -> tuple[str, ...]:
        return tuple(channel.key for category in self.categories for channel in category.channels)


WELCOME = "channel:welcome"
ANNOUNCEMENTS = "channel:announcements"
GENERAL = "channel:general"
HELP = "channel:help"

SERVER = ServerSpec(
    roles=tuple(RoleSpec(project.role_key, project.role_name, project.colour) for project in PROJECTS),
    categories=(
        CategorySpec(
            "category:info",
            "\u2726 info",
            (
                ChannelSpec(
                    WELCOME,
                    "\U0001f44b\u30fbwelcome",
                    "What this server is, the projects, and how to get release notifications.",
                    read_only=True,
                ),
                ChannelSpec(
                    ANNOUNCEMENTS,
                    "\U0001f4e3\u30fbannouncements",
                    "New releases of every project, posted automatically.",
                    read_only=True,
                ),
            ),
        ),
        CategorySpec(
            "category:community",
            "\u2726 community",
            (
                ChannelSpec(
                    GENERAL, "\U0001f4ac\u30fbgeneral", "Talk about the projects, or anything near them."
                ),
                ChannelSpec(
                    HELP,
                    "\U0001f6df\u30fbhelp",
                    "Questions about using a project. Bugs and feature requests go to GitHub.",
                ),
            ),
        ),
    ),
)
