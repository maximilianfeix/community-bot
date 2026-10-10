"""Everything the bot posts, built with Discord's layout components. Nothing here talks to Discord.

Layout components instead of embeds: a container is as wide as the channel allows, so the cards line up,
a picture can sit at the top, and buttons can stand next to the text they belong to. A message built this
way has no separate text or embeds, so a ping has to be written into the layout itself.

Every card starts with a picture from `assets/`. A layout only names its pictures; `files` turns the names
into uploads, so a card and its attachments cannot drift apart.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import discord
from discord import ui

from . import sanitize
from .definition import ACCENT, HELP
from .github import RepoInfo
from .projects import PROJECTS, Project
from .releases import Release

PROFILE = "https://github.com/maximilianfeix"
NOTES_LIMIT = 1500
FORMAT = "layout-2"
"""Part of every fingerprint. Change it to have all maintained messages rebuilt."""

CORAL, SKY, AMBER, VIOLET = 0xF7927A, 0x7AD7F7, 0xF7D27A, 0xB49AF7

ART = Path(__file__).with_name("assets")
PICTURES: dict[str, Path] = {
    "banner.png": ART / "banner.png",
    **{f"head-{name}.png": ART / "headings" / f"{name}.png" for name in ("rules", "notify", "help", "hello")},
    **{f"{project.slug}.png": ART / "projects" / f"{project.slug}.png" for project in PROJECTS},
}
"""Attachment name to file. Names are unique, because one message can carry several."""

ICONS: dict[str, str] = {}
"""Project slug to the markup of its custom emoji. Filled by the bot once the emojis exist; while it is
empty, everything is simply shown without icons."""

RULES = (
    "Be respectful. No harassment, hate or personal attacks.",
    "No spam, advertising or unsolicited DMs.",
    "Keep it legal and within Discord's Terms. The tools are for lawful use only.",
    "Never post secrets, tokens, credentials or other people's personal data.",
    "Bugs and feature requests go to GitHub. Security problems are reported privately there.",
)

PLACES = (
    ("channel:announcements", "new releases, posted automatically"),
    ("channel:general", "talk about the projects"),
    ("channel:help", "questions about using them"),
)


def picture(name: str, description: str) -> ui.MediaGallery[ui.LayoutView]:
    """A picture across the full width of a card. The description is what a screen reader says."""
    return ui.MediaGallery(discord.MediaGalleryItem(f"attachment://{name}", description=description))


def icon(slug: str) -> str:
    """The project's emoji for running text, with the space after it; empty while there is none."""
    return f"{ICONS[slug]} " if slug in ICONS else ""


def button_icon(slug: str) -> discord.PartialEmoji | None:
    return discord.PartialEmoji.from_str(ICONS[slug]) if slug in ICONS else None


def welcome(channels: Mapping[str, int]) -> ui.LayoutView:
    """The first thing a new member reads: what this is and where to go."""
    container: ui.Container[ui.LayoutView] = ui.Container(accent_colour=ACCENT)
    container.add_item(picture("banner.png", "maximilianfeix open source"))
    container.add_item(
        ui.TextDisplay(
            "# Welcome\n"
            f"This is the home of the open-source tools by [maximilianfeix]({PROFILE}): "
            "small developer tools that do one job and show their work.\n\n"
            "Ask questions, share what you built, or just follow the releases."
        )
    )
    where = [f"<#{channels[key]}>  {text}" for key, text in PLACES if key in channels]
    if where:
        container.add_item(ui.Separator(spacing=discord.SeparatorSpacing.large))
        container.add_item(ui.TextDisplay("### Where things are\n" + "\n".join(where)))
    return _view(container)


def rules() -> ui.LayoutView:
    container: ui.Container[ui.LayoutView] = ui.Container(accent_colour=CORAL)
    container.add_item(picture("head-rules.png", "Rules"))
    container.add_item(ui.TextDisplay("\n".join(f"{number}. {rule}" for number, rule in enumerate(RULES, 1))))
    container.add_item(ui.TextDisplay("-# Chat here is public. Anything worth keeping is copied to GitHub."))
    return _view(container)


def project_line(project: Project, info: RepoInfo | None, latest: Release | None) -> str:
    """The small line under a project: stars, language, latest release."""
    parts = [project.language]
    if info is not None:
        parts.insert(0, f"★ {info.stars:,}")
    if latest and latest.url:
        when = _relative(latest.published_at)
        tag = f"[{sanitize.one_line(latest.tag, 40)}]({latest.url})"
        parts.append(f"{tag} {when}".strip())
    else:
        parts.append("no release yet")
    return " · ".join(parts)


def _project_card(
    project: Project, info: RepoInfo | None, latest: Release | None
) -> ui.Container[ui.LayoutView]:
    """One project in its own colour: picture, what it does, where to go."""
    container: ui.Container[ui.LayoutView] = ui.Container(accent_colour=project.colour)
    container.add_item(picture(f"{project.slug}.png", f"{project.name}: {project.short}"))
    container.add_item(ui.TextDisplay(f"{project.tagline}\n-# {project_line(project, info, latest)}"))
    row: ui.ActionRow[ui.LayoutView] = ui.ActionRow()
    row.add_item(
        ui.Button(
            label="GitHub", url=project.url, style=discord.ButtonStyle.link, emoji=button_icon(project.slug)
        )
    )
    row.add_item(ui.Button(label="Releases", url=f"{project.url}/releases", style=discord.ButtonStyle.link))
    row.add_item(ui.Button(label="Issues", url=f"{project.url}/issues", style=discord.ButtonStyle.link))
    container.add_item(row)
    return container


def projects(info: Mapping[str, RepoInfo], latest: Mapping[str, Release | None]) -> ui.LayoutView:
    """Every project as its own card, all in one message."""
    return _view(
        *(_project_card(project, info.get(project.slug), latest.get(project.slug)) for project in PROJECTS)
    )


def project(item: Project, info: RepoInfo | None, latest: Release | None) -> ui.LayoutView:
    """One project, for the /project command."""
    return _view(_project_card(item, info, latest))


def release(item_project: Project, item: Release, role_mention: str = "") -> ui.LayoutView:
    """The announcement for one release. Notes are cleaned and shortened; the full text is one click away.

    `role_mention` is written into the layout, because a message of this kind has no separate text. Who it
    may actually ping is decided by the allowed mentions of the send call, not here.
    """
    tag = sanitize.one_line(item.tag, 60)
    name = sanitize.one_line(item.name, 120)
    heading = f"## {icon(item_project.slug)}{item_project.name} {tag}".strip()
    if name and name != tag:
        heading += f"\n-# {name}"
    container: ui.Container[ui.LayoutView] = ui.Container(accent_colour=item_project.colour)
    container.add_item(picture(f"{item_project.slug}.png", f"{item_project.name}: {item_project.short}"))
    container.add_item(ui.TextDisplay(heading))
    container.add_item(ui.TextDisplay(sanitize.notes(item.body, NOTES_LIMIT) or "No release notes."))
    container.add_item(ui.Separator())
    link: ui.Button[ui.LayoutView] = ui.Button(
        label="Full release notes", url=item.url or item_project.url, style=discord.ButtonStyle.link
    )
    footer = [role_mention, item_project.repo, _absolute(item.published_at)]
    container.add_item(
        ui.Section(ui.TextDisplay("-# " + " · ".join(part for part in footer if part)), accessory=link)
    )
    return _view(container)


def hello(channels: Mapping[str, int]) -> ui.LayoutView:
    """The first message in the chat channel, so that it does not start empty."""
    text = "Tell us what you are building, show something you made with one of the tools, or just read along."
    if HELP in channels:
        text += f"\n-# Questions go to <#{channels[HELP]}>, where they are easier to find later."
    container: ui.Container[ui.LayoutView] = ui.Container(accent_colour=VIOLET)
    container.add_item(picture("head-hello.png", "Say hello"))
    container.add_item(ui.TextDisplay(text))
    return _view(container)


def ask() -> ui.LayoutView:
    """How to ask a question that can be answered, and where bugs go instead."""
    container: ui.Container[ui.LayoutView] = ui.Container(accent_colour=AMBER)
    container.add_item(picture("head-help.png", "Help"))
    container.add_item(
        ui.TextDisplay(
            "A question gets a useful answer faster when it says:\n"
            "- which project and which version\n"
            "- what you ran and what you expected\n"
            "- what happened instead, with the output as text in a code block\n\n"
            "Remove tokens, keys and private addresses before you paste."
        )
    )
    container.add_item(ui.Separator())
    container.add_item(
        ui.TextDisplay("-# Found a bug or want a feature? Open an issue, so it is not lost in chat.")
    )
    row: ui.ActionRow[ui.LayoutView] = ui.ActionRow()
    for item in PROJECTS:
        row.add_item(
            ui.Button(
                label=item.name,
                url=f"{item.url}/issues",
                style=discord.ButtonStyle.link,
                emoji=button_icon(item.slug),
            )
        )
    container.add_item(row)
    return _view(container)


def pictures(view: ui.LayoutView) -> list[str]:
    """The attachment names a layout refers to, in order, each once."""
    names: list[str] = []
    for child in view.walk_children():
        if isinstance(child, ui.MediaGallery):
            for item in child.items:
                name = item.media.url.removeprefix("attachment://")
                if name != item.media.url and name not in names:
                    names.append(name)
    return names


def files(view: ui.LayoutView) -> list[discord.File]:
    """The uploads a layout needs. Send them with it, or its pictures stay empty."""
    return [discord.File(PICTURES[name], filename=name) for name in pictures(view)]


def fingerprint(view: ui.LayoutView, extra: str = "") -> str:
    """A stable hash of what a message shows, pictures included, to tell whether it has to be edited."""
    payload = json.dumps(components(view), sort_keys=True, default=str)
    sizes = [PICTURES[name].stat().st_size for name in pictures(view)]
    return hashlib.sha256(f"{FORMAT}\n{payload}\n{sizes}\n{extra}".encode()).hexdigest()[:32]


def components(view: ui.LayoutView) -> list[dict[str, Any]]:
    """The layout exactly as it is sent to Discord."""
    return view.to_components()  # type: ignore[no-untyped-call, no-any-return]


def text_of(view: ui.LayoutView) -> str:
    """All text a layout shows, joined. For tests and for checking Discord's length limit."""
    return "\n".join(child.content for child in view.walk_children() if isinstance(child, ui.TextDisplay))


def _view(*containers: ui.Container[ui.LayoutView]) -> ui.LayoutView:
    view = ui.LayoutView(timeout=None)
    for container in containers:
        view.add_item(container)
    return view


def _parse(timestamp: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _relative(timestamp: str) -> str:
    """Discord's relative time tag ("3 days ago"), rendered in each reader's own language."""
    parsed = _parse(timestamp)
    return f"<t:{int(parsed.timestamp())}:R>" if parsed else ""


def _absolute(timestamp: str) -> str:
    parsed = _parse(timestamp)
    return f"<t:{int(parsed.timestamp())}:D>" if parsed else ""
