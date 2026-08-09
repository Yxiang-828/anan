"""Shapes shared by transport layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class Inbound:
    """One observed platform event. Recorded always; triggers work only if addressed.

    kind: "message" | "edited" | "channel_post" | "reaction" | "member" |
          "poll" | "poll_answer" | "callback" | "join_request"
    actor_handle is the platform handle (@username), stored beside the display name.
    attachments: downloaded media descriptors ({kind, path, mime, bytes, name}).
    """

    channel: str          # "telegram" | "discord"
    room_id: str          # CHANNEL id (the conversation)
    room_kind: str        # "private" | "group" | "channel"
    event_id: str
    actor_id: str         # MEMBER id
    actor_name: str
    actor_handle: str
    actor_is_bot: bool
    text: str
    addressed: bool
    is_owner: bool
    reply_to_text: str = ""
    kind: str = "message"
    server_id: str = ""   # "" for Telegram
    attachments: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)
    detail: Mapping[str, Any] = field(default_factory=dict)
    sent_at: float = 0.0
