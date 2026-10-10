"""Everything the bot posts, as embeds. Building them touches nothing outside this module."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone

import discord

from . import sanitize
from .github import RepoInfo
from .projects import PROJECTS, Project
from .releases import Release

ACCENT = 0xD4F77A
PROFILE = "https://github.com/maximilianfeix"
BANNER_NAME = "banner.png"
NOTES_LIMIT = 1500
NO_DATA = "n/a"

RULES = (
    "Be respectful. No harassment, hate or personal attacks.",
    "No spam, advertising or unsolicited DMs.",
    "Keep it legal and within Discord's Terms. The tools are for lawful use only.",
    "Never post secrets, tokens, credentials or other people's personal data.",
    "Bugs and feature requests go to GitHub. Security problems are reported privately there.",
)


def welcome(channels: Mapping[str, int]) -> discord.Embed:
    """The first thing a new member reads: what this is, where to go, the rules."""
    embed = discord.Embed(
        title="Welcome",
        description=(
            "This is the home of the open-source tools by "
            f"[maximilianfeix]({PROFILE}): small developer tools that do one job and show their work.\n\n"
            "Ask questions, share what you built, or just follow the releases."
        ),
        color=ACCENT,
    )
    places = [
        ("channel:announcements", "new releases, posted automatically"),
        ("channel:general", "talk about the projects"),
        ("channel:help", "questions about using them"),
    ]
    where = [f"<#{channels[key]}>  {text}" for key, text in places if key in channels]
    if where:
        embed.add_field(name="Where things are", value="\n".join(where), inline=False)
    rules = "\n".join(f"{number}. {rule}" for number, rule in enumerate(RULES, 1))
    embed.add_field(name="Rules", value=rules, inline=False)
    embed.set_image(url=f"attachment://{BANNER_NAME}")
    embed.set_footer(text="Chat here is public. Anything worth keeping is copied to GitHub.")
    return embed


def project_card(project: Project, info: RepoInfo | None, latest: Release | None) -> discord.Embed:
    """One project: what it is, how many stars, the latest release."""
    embed = discord.Embed(title=project.name, url=project.url, description=project.tagline, color=ACCENT)
    embed.add_field(name="Language", value=project.language)
    embed.add_field(name="Stars", value=f"{info.stars:,}" if info else NO_DATA)
    if latest and latest.url:
        when = _relative(latest.published_at)
        value = f"[{sanitize.one_line(latest.tag, 40)}]({latest.url})" + (f" · {when}" if when else "")
    else:
        value = "No release yet"
    embed.add_field(name="Latest release", value=value)
    return embed


def project_cards(info: Mapping[str, RepoInfo], latest: Mapping[str, Release | None]) -> list[discord.Embed]:
    return [project_card(p, info.get(p.slug), latest.get(p.slug)) for p in PROJECTS]


def picker() -> discord.Embed:
    return discord.Embed(
        title="Release notifications",
        description=(
            "Press a button to be pinged when that project ships a release. "
            "Press it again to stop. Only you see the answer."
        ),
        color=ACCENT,
    )


def release(project: Project, item: Release) -> discord.Embed:
    """The announcement for one release. Notes are cleaned and shortened; the full text is one click away."""
    tag = sanitize.one_line(item.tag, 60)
    embed = discord.Embed(
        title=f"{project.name} {tag}".strip(),
        url=item.url or project.url,
        description=sanitize.notes(item.body, NOTES_LIMIT) or "No release notes.",
        color=ACCENT,
    )
    name = sanitize.one_line(item.name, 120)
    if name and name != tag:
        embed.set_author(name=name)
    published = _parse(item.published_at)
    if published:
        embed.timestamp = published
    embed.set_footer(text=f"{project.repo} · full notes on GitHub")
    return embed


def fingerprint(embeds: Sequence[discord.Embed], extra: str = "") -> str:
    """A stable hash of what a message shows, to tell whether it has to be edited."""
    payload = json.dumps([embed.to_dict() for embed in embeds], sort_keys=True, default=str)
    return hashlib.sha256((payload + "\n" + extra).encode("utf-8")).hexdigest()[:32]


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
