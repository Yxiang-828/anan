"""Presence — provenance stamp mixin."""

from __future__ import annotations

from typing import Any, Callable


class StampsOutbound:
    """Mixin: `self.usage_stamp` (injected by host/runner) -> stamp line on chunk."""

    usage_stamp: Callable[[], str] | None = None
    subtext_prefix: str = ""

    def stamp_head(self) -> str:
        reader: Any = getattr(self, "usage_stamp", None)
        if reader is None:
            return ""
        try:
            reading = " ".join(str(reader() or "").split())
        except Exception as exc:
            print(f"[presence] usage stamp unreadable ({type(exc).__name__}) — "
                  "message sent without it", flush=True)
            return ""
        if not reading:
            return ""
        return f"{self.subtext_prefix}`[{reading}]`"

    def stamp(self, text: str, *, force: bool = False) -> str:
        if not text and not force:
            return text
        head = self.stamp_head()
        if not head:
            return text
        if text.lstrip().startswith(head):
            return text
        return f"{head}\n{text}" if text else head


__all__ = ["StampsOutbound"]
