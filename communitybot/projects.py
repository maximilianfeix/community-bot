"""The projects this server is about. Adding one here adds its card, its role and its announcements."""

from __future__ import annotations

from dataclasses import dataclass

OWNER = "maximilianfeix"


@dataclass(frozen=True)
class Project:
    slug: str
    """Repository name; also the stable key in the state file and in button ids."""
    name: str
    tagline: str
    language: str
    short: str
    """The tagline in a few words, for the project's picture."""
    colour: int
    """The project's own colour: its card, its picture, its sign and its role."""

    @property
    def repo(self) -> str:
        return f"{OWNER}/{self.slug}"

    @property
    def url(self) -> str:
        return f"https://github.com/{self.repo}"

    @property
    def role_key(self) -> str:
        return f"role:{self.slug}"

    @property
    def role_name(self) -> str:
        return f"{self.name} releases"


PROJECTS: tuple[Project, ...] = (
    Project(
        "proxy-scraper",
        "proxy-scraper",
        "Free proxies that actually work: 700+ sources, every hit verified, a live list every hour.",
        "Python",
        "Free proxies that actually work.",
        0x7AD7F7,
    ),
    Project(
        "dejabuilt",
        "dejabuilt",
        "An agent skill that checks GitHub before you build.",
        "Python",
        "Checks GitHub before you build.",
        0xD4F77A,
    ),
    Project(
        "spillage",
        "spillage",
        "Keeps API keys out of your coding agents: blocks the leak and scans what already leaked.",
        "Python",
        "Keeps API keys out of your coding agents.",
        0xF7927A,
    ),
    Project(
        "repoatlas",
        "RepoAtlas",
        "Understand any TypeScript repo in one interactive map, every connection linked to source.",
        "TypeScript",
        "Any TypeScript repo as one interactive map.",
        0xB49AF7,
    ),
    Project(
        "gha-preview",
        "gha-preview",
        "Preview and explore GitHub Actions workflows before you push.",
        "TypeScript",
        "Preview GitHub Actions before you push.",
        0xF7D27A,
    ),
)

BY_SLUG: dict[str, Project] = {project.slug: project for project in PROJECTS}
