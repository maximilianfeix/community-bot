from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from communitybot.config import MIN_POLL_SECONDS, ConfigError, Settings
from communitybot.state import STATE_VERSION, MessageState, RepoState, State, StateError, load, save

TOKEN = "discord-token-value"


class TestState:
    def sample(self) -> State:
        return State(
            resources={"channel:welcome": 123456789012345678},
            messages={"message:welcome": MessageState(42, "abc")},
            repos={"dejabuilt": RepoState(True, [1, 2, 3])},
            cache={"https://api.github.com/repos/o/r": {"etag": '"e"', "data": {"stargazers_count": 1}}},
        )

    def test_round_trip_through_a_file(self, tmp_path: Path) -> None:
        path = tmp_path / "nested" / "state.json"
        save(path, self.sample())
        assert load(path) == self.sample()
        assert json.loads(path.read_text(encoding="utf-8"))["version"] == STATE_VERSION

    def test_missing_file_is_a_first_start(self, tmp_path: Path) -> None:
        assert load(tmp_path / "nope.json") == State()

    def test_save_leaves_no_temporary_file(self, tmp_path: Path) -> None:
        save(tmp_path / "state.json", State())
        assert [p.name for p in tmp_path.iterdir()] == ["state.json"]

    def test_repo_state_is_created_on_first_use(self) -> None:
        state = State()
        assert state.repo("x") == RepoState(False, [])
        assert "x" in state.repos

    @pytest.mark.parametrize(
        "content",
        [
            "",
            "{",
            "[]",
            '{"version": 99}',
            '{"version": 1, "resources": {"a": "not a number"}}',
            '{"version": 1, "messages": {"a": {"fingerprint": "x"}}}',
            '{"version": 1, "repos": {"a": {"baselined": true}}}',
            '{"version": 1, "repos": []}',
        ],
    )
    def test_broken_file_is_an_error_not_a_fresh_start(self, tmp_path: Path, content: str) -> None:
        path = tmp_path / "state.json"
        path.write_text(content, encoding="utf-8")
        with pytest.raises(StateError):
            load(path)

    def test_error_does_not_echo_file_content(self, tmp_path: Path) -> None:
        path = tmp_path / "state.json"
        path.write_text('{"version": 1, "resources": {"a": "SECRET-LOOKING"}}', encoding="utf-8")
        with pytest.raises(StateError) as caught:
            load(path)
        assert "SECRET-LOOKING" not in str(caught.value)


BASE: dict[str, str] = {"DISCORD_TOKEN": TOKEN, "COMMUNITYBOT_GUILD_ID": "1558559118694944790"}


class TestSettings:
    def test_minimal_environment(self) -> None:
        settings = Settings.from_env(BASE)
        assert settings.guild_id == 1558559118694944790
        assert settings.poll_seconds == 900
        assert settings.github_token == ""
        assert settings.state_file == Path("state.json")

    def test_optional_values(self) -> None:
        env = {
            **BASE,
            "GITHUB_TOKEN": " gh ",
            "COMMUNITYBOT_STATE": "/var/lib/x/s.json",
            "COMMUNITYBOT_POLL_SECONDS": "1200",
        }
        settings = Settings.from_env(env)
        assert (settings.github_token, settings.poll_seconds) == ("gh", 1200)
        assert settings.state_file == Path("/var/lib/x/s.json")

    def test_polling_cannot_be_set_faster_than_the_floor(self) -> None:
        settings = Settings.from_env({**BASE, "COMMUNITYBOT_POLL_SECONDS": "5"})
        assert settings.poll_seconds == MIN_POLL_SECONDS

    @pytest.mark.parametrize(
        "change",
        [
            {"DISCORD_TOKEN": ""},
            {"DISCORD_TOKEN": "   "},
            {"COMMUNITYBOT_GUILD_ID": ""},
            {"COMMUNITYBOT_GUILD_ID": "abc"},
            {"COMMUNITYBOT_GUILD_ID": "-5"},
            {"COMMUNITYBOT_GUILD_ID": "0"},
            {"COMMUNITYBOT_POLL_SECONDS": "fast"},
        ],
    )
    def test_bad_environment_is_rejected(self, change: dict[str, Any]) -> None:
        with pytest.raises(ConfigError):
            Settings.from_env({**BASE, **change})

    def test_secrets_stay_out_of_repr_and_errors(self) -> None:
        settings = Settings.from_env({**BASE, "GITHUB_TOKEN": "gh-secret"})
        assert TOKEN not in repr(settings)
        assert "gh-secret" not in repr(settings)
        with pytest.raises(ConfigError) as caught:
            Settings.from_env({"DISCORD_TOKEN": TOKEN, "COMMUNITYBOT_GUILD_ID": TOKEN})
        assert TOKEN not in str(caught.value)
