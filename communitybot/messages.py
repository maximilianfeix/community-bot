"""Everything the bot posts, built with Discord's layout components. Nothing here talks to Discord.

Layout components instead of embeds: a container is as wide as the channel allows, so the cards line up,
a banner can sit at the top, and buttons can stand next to the text they belong to. A message built this
way has no separate text or embeds, so a ping has to be written into the layout itself.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

import discord
from discord import ui

from . import sanitize
from .definition import ACCENT, HELP
from .github import RepoInfo
from .projects import PROJECTS, Project
from .releases import Release

PROFILE = "https://github.com/maximilianfeix"
BANNER_NAME = "banner.png"
NOTES_LIMIT = 1500
FORMAT = "layout-1"
"""Part of every fingerprint. Change it to have all maintained messages rebuilt."""

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


def welcome(channels: Mapping[str, int], with_banner: bool = True) -> ui.LayoutView:
    """The first thing a new member reads: what this is, where to go, the rules."""
    container: ui.Container[ui.LayoutView] = ui.Container(accent_colour=ACCENT)
    if with_banner:
        banner = discord.MediaGalleryItem(
            f"attachment://{BANNER_NAME}", description="maximilianfeix open source"
        )
        container.add_item(ui.MediaGallery(banner))
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
    container.add_item(ui.Separator(spacing=discord.SeparatorSpacing.large))
    rules = "\n".join(f"{number}. {rule}" for number, rule in enumerate(RULES, 1))
    container.add_item(ui.TextDisplay("### Rules\n" + rules))
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


def _project_section(
    project: Project, info: RepoInfo | None, latest: Release | None
) -> ui.Section[ui.LayoutView]:
    text = f"### {project.name}\n{project.tagline}\n-# {project_line(project, info, latest)}"
    button: ui.Button[ui.LayoutView] = ui.Button(
        label="GitHub", url=project.url, style=discord.ButtonStyle.link
    )
    return ui.Section(ui.TextDisplay(text), accessory=button)


def projects(info: Mapping[str, RepoInfo], latest: Mapping[str, Release | None]) -> ui.LayoutView:
    """Every project in one card, each with its own link."""
    container: ui.Container[ui.LayoutView] = ui.Container(accent_colour=ACCENT)
    container.add_item(ui.TextDisplay("## Projects"))
    for index, project in enumerate(PROJECTS):
        if index:
            container.add_item(ui.Separator())
        container.add_item(_project_section(project, info.get(project.slug), latest.get(project.slug)))
    return _view(container)


def project(item: Project, info: RepoInfo | None, latest: Release | None) -> ui.LayoutView:
    """One project, for the /project command."""
    container: ui.Container[ui.LayoutView] = ui.Container(accent_colour=ACCENT)
    container.add_item(_project_section(item, info, latest))
    return _view(container)


def release(item_project: Project, item: Release, role_mention: str = "") -> ui.LayoutView:
    """The announcement for one release. Notes are cleaned and shortened; the full text is one click away.

    `role_mention` is written into the layout, because a message of this kind has no separate text. Who it
    may actually ping is decided by the allowed mentions of the send call, not here.
    """
    tag = sanitize.one_line(item.tag, 60)
    name = sanitize.one_line(item.name, 120)
    heading = f"## {item_project.name} {tag}".strip()
    if name and name != tag:
        heading += f"\n-# {name}"
    container: ui.Container[ui.LayoutView] = ui.Container(accent_colour=ACCENT)
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
    text = (
        "## Say hello\n"
        "Tell us what you are building, show something you made with one of the tools, "
        "or just read along."
    )
    if HELP in channels:
        text += f"\n-# Questions go to <#{channels[HELP]}>, where they are easier to find later."
    container: ui.Container[ui.LayoutView] = ui.Container(accent_colour=ACCENT)
    container.add_item(ui.TextDisplay(text))
    return _view(container)


def ask() -> ui.LayoutView:
    """How to ask a question that can be answered, and where bugs go instead."""
    container: ui.Container[ui.LayoutView] = ui.Container(accent_colour=ACCENT)
    container.add_item(
        ui.TextDisplay(
            "## Asking for help\n"
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
        row.add_item(ui.Button(label=item.name, url=f"{item.url}/issues", style=discord.ButtonStyle.link))
    container.add_item(row)
    return _view(container)


def fingerprint(view: ui.LayoutView, extra: str = "") -> str:
    """A stable hash of what a message shows, to tell whether it has to be edited."""
    payload = json.dumps(components(view), sort_keys=True, default=str)
    return hashlib.sha256(f"{FORMAT}\n{payload}\n{extra}".encode()).hexdigest()[:32]


def components(view: ui.LayoutView) -> list[dict[str, Any]]:
    """The layout exactly as it is sent to Discord."""
    return view.to_components()  # type: ignore[no-untyped-call, no-any-return]


def text_of(view: ui.LayoutView) -> str:
    """All text a layout shows, joined. For tests and for checking Discord's length limit."""
    return "\n".join(child.content for child in view.walk_children() if isinstance(child, ui.TextDisplay))


def _view(container: ui.Container[ui.LayoutView]) -> ui.LayoutView:
    view = ui.LayoutView(timeout=None)
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
