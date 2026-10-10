from __future__ import annotations

import pytest

from communitybot.sanitize import ELLIPSIS, ZERO_WIDTH_SPACE, defuse_mentions, notes, one_line


class TestOneLine:
    def test_collapses_whitespace_and_newlines(self) -> None:
        assert one_line("a\n\n b\t c", 50) == "a b c"

    @pytest.mark.parametrize("value", [None, 5, ["x"]])
    def test_non_strings_become_empty(self, value: object) -> None:
        assert one_line(value, 50) == ""

    def test_removes_control_and_invisible_characters(self) -> None:
        assert one_line("a\x1b[2Jb‮c​d", 50) == "a[2Jbcd"

    def test_truncates_with_an_ellipsis(self) -> None:
        result = one_line("x" * 100, 10)
        assert len(result) == 10
        assert result.endswith(ELLIPSIS)


class TestMentions:
    @pytest.mark.parametrize("ping", ["@everyone", "@here"])
    def test_mass_pings_are_broken(self, ping: str) -> None:
        result = defuse_mentions(f"hello {ping}!")
        assert ping not in result
        assert ZERO_WIDTH_SPACE in result

    @pytest.mark.parametrize("raw", ["<@123456>", "<@!123456>", "<@&987654>", "<#555>"])
    def test_raw_mentions_no_longer_resolve(self, raw: str) -> None:
        result = defuse_mentions(f"cc {raw}")
        assert raw not in result
        assert "123456" in result or "987654" in result or "555" in result

    def test_ordinary_text_is_untouched(self) -> None:
        assert defuse_mentions("mail me@example.com about #42") == "mail me@example.com about #42"


class TestNotes:
    def test_plain_markdown_survives(self) -> None:
        text = "## Fixed\n\n- one\n- two\n\n**Thanks**"
        assert notes(text, 500) == text

    def test_html_and_comments_are_removed(self) -> None:
        text = "<!-- hidden -->Hello <b>world</b><img src=x onerror=alert(1)>"
        assert notes(text, 500) == "Hello world"

    def test_images_become_their_alt_text(self) -> None:
        assert notes("![a chart](https://example.com/a.png) done", 500) == "a chart done"

    def test_masked_links_show_where_they_go(self) -> None:
        result = notes("[github.com](https://evil.example/login)", 500)
        assert result == "github.com (https://evil.example/login)"

    def test_invite_links_are_removed(self) -> None:
        result = notes("join discord.gg/abc123 or https://discord.com/invite/xyz now", 500)
        assert "abc123" not in result
        assert "xyz" not in result

    def test_pings_in_release_notes_do_not_ping(self) -> None:
        result = notes("Thanks @everyone and <@&111>!", 500)
        assert "@everyone" not in result
        assert "<@&111>" not in result

    def test_blank_line_runs_are_collapsed(self) -> None:
        assert notes("a\n\n\n\n\nb\r\n\r\n\r\nc", 500) == "a\n\nb\n\nc"

    def test_long_notes_are_cut_at_a_line_break(self) -> None:
        text = "\n".join(f"- item number {n}" for n in range(200))
        result = notes(text, 300)
        assert len(result) <= 300 + 1
        assert result.endswith(ELLIPSIS)
        assert result.splitlines()[-2].startswith("- item number")

    def test_one_very_long_line_is_still_cut(self) -> None:
        result = notes("x" * 5000, 100)
        assert len(result) <= 101
        assert result.endswith(ELLIPSIS)

    @pytest.mark.parametrize("value", [None, "", "   \n  "])
    def test_empty_input_gives_empty_output(self, value: object) -> None:
        assert notes(value, 100) == ""
