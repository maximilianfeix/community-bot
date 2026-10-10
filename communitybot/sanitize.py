"""Make text from GitHub safe to post. Pure.

Release notes are written by whoever can publish a release, and a description can be edited by any
maintainer. Posted as-is they could ping the whole server, hide links behind other text or flood a channel.
"""

from __future__ import annotations

import re
import unicodedata

ELLIPSIS = "…"
ZERO_WIDTH_SPACE = "​"

_COMMENT = re.compile(r"<!--.*?-->", re.S)
_TAG = re.compile(r"</?[A-Za-z][^>]*>")
_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_MASKED_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)[^)]*\)")
_MENTION = re.compile(r"<(@[!&]?|#)(\d+)>")
_INVITE = re.compile(r"(?i)\b(discord\.gg|discord(?:app)?\.com/invite)/\S+")
_BLANK_RUN = re.compile(r"\n{3,}")


def one_line(text: object, limit: int) -> str:
    """Printable text on a single line, at most `limit` characters."""
    return _truncate(" ".join(_visible(text).split()), limit)


def notes(text: object, limit: int) -> str:
    """Release notes fit for an embed: no HTML, no pings, no hidden links, no flood."""
    cleaned = _visible(text).replace("\r\n", "\n").replace("\r", "\n")
    cleaned = _COMMENT.sub("", cleaned)
    cleaned = _IMAGE.sub(lambda match: match.group(1), cleaned)
    cleaned = _MASKED_LINK.sub(lambda match: f"{match.group(1)} ({match.group(2)})", cleaned)
    cleaned = _TAG.sub("", cleaned)
    cleaned = defuse_mentions(cleaned)
    cleaned = _INVITE.sub("[invite link removed]", cleaned)
    lines = [line.rstrip() for line in cleaned.split("\n")]
    cleaned = _BLANK_RUN.sub("\n\n", "\n".join(lines)).strip()
    return _truncate_lines(cleaned, limit)


def defuse_mentions(text: str) -> str:
    """Stop @everyone, @here and raw <@id> mentions from resolving, while keeping them readable."""
    text = _MENTION.sub(lambda match: f"<{match.group(1)}{ZERO_WIDTH_SPACE}{match.group(2)}>", text)
    return re.sub(r"@(everyone|here)", lambda match: f"@{ZERO_WIDTH_SPACE}{match.group(1)}", text)


def _visible(text: object) -> str:
    """Drop control and invisible format characters; keep newlines and tabs as whitespace."""
    if not isinstance(text, str):
        return ""
    return "".join(
        ch for ch in text if ch in "\n\r\t" or not unicodedata.category(ch).startswith("C")
    ).replace("\t", " ")


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(limit - 1, 0)].rstrip() + ELLIPSIS


def _truncate_lines(text: str, limit: int) -> str:
    """Cut at a line break where possible, so a list item or sentence is not left half-finished."""
    if len(text) <= limit:
        return text
    head = text[: max(limit - 1, 0)]
    cut = head.rfind("\n")
    if cut >= limit // 2:
        head = head[:cut]
    return head.rstrip() + "\n" + ELLIPSIS
