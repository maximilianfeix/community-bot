"""What the bot has to remember across restarts, in one JSON file.

- which roles, categories and channels it created (the only ones it will ever change),
- which messages it keeps up to date,
- which releases it has already seen per repository,
- which one-off jobs are done,
- the last answer from GitHub per URL, so unchanged data is not downloaded again.

A file that cannot be read is an error, never a fresh start: forgetting which releases were announced would
announce them all again.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

STATE_VERSION = 1


class StateError(Exception):
    """The state file exists but cannot be used."""


@dataclass
class RepoState:
    baselined: bool = False
    seen: list[int] = field(default_factory=list)


@dataclass
class MessageState:
    message_id: int
    fingerprint: str


@dataclass
class State:
    resources: dict[str, int] = field(default_factory=dict)
    messages: dict[str, MessageState] = field(default_factory=dict)
    repos: dict[str, RepoState] = field(default_factory=dict)
    cache: dict[str, dict[str, Any]] = field(default_factory=dict)
    done: set[str] = field(default_factory=set)
    """Names of jobs that run once per server and never again."""

    def repo(self, slug: str) -> RepoState:
        return self.repos.setdefault(slug, RepoState())

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": STATE_VERSION,
            "resources": dict(self.resources),
            "messages": {
                key: {"message_id": m.message_id, "fingerprint": m.fingerprint}
                for key, m in self.messages.items()
            },
            "repos": {
                slug: {"baselined": r.baselined, "seen": list(r.seen)} for slug, r in self.repos.items()
            },
            "cache": self.cache,
            "done": sorted(self.done),
        }

    @classmethod
    def from_dict(cls, data: Any) -> State:
        if not isinstance(data, dict):
            raise StateError("state must be a JSON object")
        if data.get("version") != STATE_VERSION:
            raise StateError(f"unsupported state version {data.get('version')!r}")
        try:
            return cls(
                resources={str(k): int(v) for k, v in data.get("resources", {}).items()},
                messages={
                    str(k): MessageState(int(v["message_id"]), str(v["fingerprint"]))
                    for k, v in data.get("messages", {}).items()
                },
                repos={
                    str(k): RepoState(bool(v["baselined"]), [int(i) for i in v["seen"]])
                    for k, v in data.get("repos", {}).items()
                },
                cache={str(k): dict(v) for k, v in data.get("cache", {}).items()},
                done={str(name) for name in data.get("done", [])},
            )
        except (AttributeError, KeyError, TypeError, ValueError) as error:
            raise StateError(f"state file has an unexpected shape ({type(error).__name__})") from None


def load(path: Path) -> State:
    """Read the state file. A missing file is a first start; a broken one is an error."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return State()
    try:
        return State.from_dict(json.loads(text))
    except json.JSONDecodeError:
        raise StateError(f"{path} is not valid JSON") from None


def save(path: Path, state: State) -> None:
    """Write the whole file to a temporary name and swap it in, so a crash never leaves half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(state.to_dict(), handle, indent=1, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)
