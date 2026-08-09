"""Markdown → Telegram-safe HTML (owner 2026-07-22: "telegram still full of
markdowns that can't be supported").

The agent writes GitHub-flavoured markdown (**bold**, ## headers, `code`, fenced
blocks, - bullets, [links](url)). Telegram's default send renders NONE of it —
the raw ``**`` and ``##`` show as literal symbols. Telegram supports parse_mode
HTML with a SMALL tag set (<b> <i> <u> <s> <code> <pre> <a>); anything else, or
an unescaped < & >, makes the send FAIL. So this converts the common markdown to
that tag set and escapes everything else — and the caller falls back to plain
text if Telegram still rejects it, so a message is never lost to a formatting
error.

Stdlib only. Deterministic; never raises.
"""
from __future__ import annotations

import html
import re

_ALLOWED = ("b", "i", "u", "s", "code", "pre", "a")


def _esc(text: str) -> str:
    return html.escape(text, quote=False)


def to_telegram_html(md: str) -> str:
    """Convert markdown to the Telegram HTML subset. Escapes all literal text;
    only the whitelisted tags survive."""
    if not md:
        return ""
    text = md.replace("\r\n", "\n")

    # Fenced code blocks first — protect their contents from all other rules.
    blocks: list[str] = []

    def _stash_fence(m: re.Match) -> str:
        blocks.append(m.group(1))
        return f"\x00FENCE{len(blocks) - 1}\x00"

    text = re.sub(r"```[a-zA-Z0-9_+-]*\n?(.*?)```", _stash_fence, text, flags=re.DOTALL)

    # Inline code — protect too.
    inlines: list[str] = []

    def _stash_code(m: re.Match) -> str:
        inlines.append(m.group(1))
        return f"\x00CODE{len(inlines) - 1}\x00"

    text = re.sub(r"`([^`\n]+)`", _stash_code, text)

    # Links [label](url) → capture before escaping.
    links: list[tuple[str, str]] = []

    def _stash_link(m: re.Match) -> str:
        links.append((m.group(1), m.group(2)))
        return f"\x00LINK{len(links) - 1}\x00"

    text = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", _stash_link, text)

    # Now escape ALL remaining literal text.
    text = _esc(text)

    # Headers → bold line (Telegram has no headings).
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s+(.+?)\s*$", lambda m: f"<b>{m.group(1)}</b>", text)
    # Bold **x** / __x__
    text = re.sub(r"\*\*([^\n*]+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<!\w)__([^\n_]+?)__(?!\w)", r"<b>\1</b>", text)
    # Italic *x* / _x_  (after bold so ** is gone)
    text = re.sub(r"(?<!\*)\*([^\n*]+?)\*(?!\*)", r"<i>\1</i>", text)
    text = re.sub(r"(?<!\w)_([^\n_]+?)_(?!\w)", r"<i>\1</i>", text)
    # Strikethrough ~~x~~
    text = re.sub(r"~~([^\n~]+?)~~", r"<s>\1</s>", text)
    # Bullets - / * / + → •
    text = re.sub(r"(?m)^\s{0,4}[-*+]\s+", "• ", text)
    # Blockquote > line → keep the text, drop the marker
    text = re.sub(r"(?m)^\s{0,3}>\s?", "", text)

    # Restore links / code / fences (their contents were captured pre-escape).
    def _restore(text: str) -> str:
        for i, (label, url) in enumerate(links):
            text = text.replace(f"\x00LINK{i}\x00", f'<a href="{_esc(url)}">{_esc(label)}</a>')
        for i, code in enumerate(inlines):
            text = text.replace(f"\x00CODE{i}\x00", f"<code>{_esc(code)}</code>")
        for i, block in enumerate(blocks):
            body = _esc(block.rstrip("\n"))
            text = text.replace(f"\x00FENCE{i}\x00", f"<pre>{body}</pre>")
        return text

    return _restore(text)


def to_plaintext(md: str) -> str:
    """Strip markdown to clean readable plain text — the guaranteed-safe
    fallback if Telegram rejects the HTML for any reason."""
    if not md:
        return ""
    text = md.replace("\r\n", "\n")
    text = re.sub(r"```[a-zA-Z0-9_+-]*\n?(.*?)```", r"\1", text, flags=re.DOTALL)
    text = re.sub(r"`([^`\n]+)`", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r"\1 (\2)", text)
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s+", "", text)
    text = re.sub(r"\*\*([^\n*]+?)\*\*", r"\1", text)
    text = re.sub(r"(?<!\w)__([^\n_]+?)__(?!\w)", r"\1", text)
    text = re.sub(r"(?<!\*)\*([^\n*]+?)\*(?!\*)", r"\1", text)
    text = re.sub(r"~~([^\n~]+?)~~", r"\1", text)
    text = re.sub(r"(?m)^\s{0,4}[-*+]\s+", "• ", text)
    text = re.sub(r"(?m)^\s{0,3}>\s?", "", text)
    return text


__all__ = ["to_telegram_html", "to_plaintext"]
