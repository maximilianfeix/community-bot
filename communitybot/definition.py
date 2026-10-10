"""What the server should look like. Change this file and the bot changes the server on its next start.

Deliberately small: an empty server with a dozen silent channels looks dead. One place to read, one place to
talk, one place to ask. Add a channel here when a conversation keeps happening that has no home.
"""

from __future__ import annotations

from dataclasses import dataclass

from .projects import PROJECTS

ACCENT = 0xD4F77A
"""The one colour of the server: cards, banner, avatar and roles."""


@dataclass(frozen=True)
class RoleSpec:
    key: str
    name: str
    colour: int = ACCENT
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
    roles=tuple(RoleSpec(project.role_key, project.role_name) for project in PROJECTS),
    categories=(
        CategorySpec(
            "category:info",
            "info",
            (
                ChannelSpec(
                    WELCOME,
                    "welcome",
                    "What this server is, the projects, and how to get release notifications.",
                    read_only=True,
                ),
                ChannelSpec(
                    ANNOUNCEMENTS,
                    "announcements",
                    "New releases of every project, posted automatically.",
                    read_only=True,
                ),
            ),
        ),
        CategorySpec(
            "category:community",
            "community",
            (
                ChannelSpec(GENERAL, "general", "Talk about the projects, or anything near them."),
                ChannelSpec(
                    HELP,
                    "help",
                    "Questions about using a project. Bugs and feature requests go to GitHub.",
                ),
            ),
        ),
    ),
)
