"""Settings from environment variables. On the server they come from /etc/communitybot.env."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

MIN_POLL_SECONDS = 300


class ConfigError(Exception):
    """A required setting is missing or malformed. The message never contains a secret."""


@dataclass(frozen=True)
class Settings:
    token: str = field(repr=False)
    guild_id: int
    github_token: str = field(default="", repr=False)
    state_file: Path = Path("state.json")
    poll_seconds: int = 900

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> Settings:
        token = env.get("DISCORD_TOKEN", "").strip()
        if not token:
            raise ConfigError("DISCORD_TOKEN is not set")
        return cls(
            token=token,
            guild_id=_positive_int(env, "COMMUNITYBOT_GUILD_ID"),
            github_token=env.get("GITHUB_TOKEN", "").strip(),
            state_file=Path(env.get("COMMUNITYBOT_STATE", "state.json")),
            poll_seconds=max(MIN_POLL_SECONDS, _positive_int(env, "COMMUNITYBOT_POLL_SECONDS", 900)),
        )


def _positive_int(env: Mapping[str, str], name: str, default: int | None = None) -> int:
    raw = env.get(name, "").strip()
    if not raw:
        if default is None:
            raise ConfigError(f"{name} is not set")
        return default
    if not raw.isdigit() or int(raw) <= 0:
        raise ConfigError(f"{name} must be a positive whole number")
    return int(raw)
