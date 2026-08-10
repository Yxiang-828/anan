"""Telegram transport — the FULL platform surface, no agency attached.

Owner directive 2026-07-19: build the complete Telegram side as a clean layer
and document what works before agency layers touch it. Ability ledger:
TELEGRAM.md at the repo root.

Inbound: maximal allowed_updates (messages, edits, channel posts, reactions,
member changes, polls, callbacks, join requests) — reactions and chat_member
require the bot to be a group ADMIN, and passive group hearing requires
BotFather privacy mode OFF (both owner actions; connect() reports the privacy
state from getMe.can_read_all_group_messages).
Media: attachments downloaded via getFile (cloud cap 20MB).
Outbound: text (chunked), photo/document/voice/video/animation/sticker (path,
URL, or file_id), polls, reactions, edits, pin/unpin, delete, chat actions,
inline keyboards, commands menu.

Lore carried from keel1: identity resolved at connect (deaf-groups lesson);
offset committed only after the handler returns; retry_after respected.
"""

from __future__ import annotations

import json
import mimetypes
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Callable, Mapping

from adapter.base import ContractError, atomic_write_json
from adapter.contract import Inbound
from adapter.stamp import StampsOutbound

_MAX_MESSAGE = 4000
_MAX_CHUNKS = 5
_MAX_DOWNLOAD = 20 * 1024 * 1024  # Bot API cloud getFile ceiling

ALLOWED_UPDATES = [
    "message", "edited_message", "channel_post", "edited_channel_post",
    "message_reaction", "message_reaction_count",
    "my_chat_member", "chat_member", "chat_join_request",
    "poll", "poll_answer", "callback_query",
]

_MEDIA_KINDS = ("photo", "document", "audio", "video", "video_note", "voice", "animation", "sticker")


def _api(token: str, method: str, body: Mapping[str, Any], *, timeout: int) -> Mapping[str, Any]:
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=json.dumps(dict(body)).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read(8 * 1024 * 1024).decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read(65536)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            raise ContractError("TELEGRAM_HTTP", f"HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ContractError("TELEGRAM_NETWORK", type(exc).__name__) from exc
    if not isinstance(payload, Mapping):
        raise ContractError("TELEGRAM_RESPONSE", "response must be an object")
    return payload


def _api_multipart(token: str, method: str, fields: Mapping[str, str], file_field: str, path: Path, *, timeout: int) -> Mapping[str, Any]:
    boundary = f"telegram-{uuid.uuid4().hex}"
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    parts: list[bytes] = []
    for key, value in fields.items():
        parts.append(
            (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"\r\n\r\n{value}\r\n").encode("utf-8")
        )
    parts.append(
        (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{file_field}\"; "
         f"filename=\"{path.name}\"\r\nContent-Type: {mime}\r\n\r\n").encode("utf-8")
    )
    parts.append(path.read_bytes())
    parts.append(f"\r\n--{boundary}--\r\n".encode("utf-8"))
    body = b"".join(parts)
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read(8 * 1024 * 1024).decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read(65536)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            raise ContractError("TELEGRAM_HTTP", f"HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ContractError("TELEGRAM_NETWORK", type(exc).__name__) from exc
    if not isinstance(payload, Mapping):
        raise ContractError("TELEGRAM_RESPONSE", "response must be an object")
    return payload


def _ok(payload: Mapping[str, Any], what: str) -> Any:
    if payload.get("ok") is not True:
        raise ContractError("TELEGRAM_SEND", f"{what}: {payload.get('description') or 'failed'}")
    return payload.get("result")


class TelegramTransport(StampsOutbound):
    # Injected into the brain's instructions by the loop — each platform
    # speaks its own rendering dialect; that is why adapters are separate.
    # Corrected 2026-08-01. The previous note said "renders as PLAIN TEXT.
    # Markdown does NOT work — never write **bold** ... or # headers", and that
    # had been FALSE since 2026-07-22, when tg_format.py landed and send()
    # started posting to_telegram_html() with parse_mode=HTML (see :504-508).
    # Ten days of every agent being instructed to write worse Telegram output
    # than the adapter could already render. A style_note is a factual claim
    # about a pipe; when the pipe changes, this string is part of the change.
    style_note = (
        "FORMAT FOR TELEGRAM — this is measured against our own adapter, not assumed; "
        "do not guess beyond it. Your markdown IS translated to Telegram HTML before "
        "sending (tg_format.to_telegram_html), with a plain-text retry if Telegram "
        "rejects it, so a message is never lost to markup.\n"
        "SURVIVES: **bold** __bold__, *italics* _italics_, ~~strike~~, `inline code`, "
        "``` fenced blocks, [label](https://url) links. # ## ### headings become a BOLD "
        "LINE (Telegram has no headings). -, * and + bullets become '• ' bullets. A > "
        "quote keeps its text but LOSES the quote styling — the marker is stripped.\n"
        "DOES NOT SURVIVE — never send these: pipe tables (no table renderer), nested "
        "list indentation (it is flattened — every bullet lands at one level), task "
        "lists, --- rules, images, underline, spoilers. Bold and italics cannot span a "
        "newline. For anything columnar use a fenced block; for a real table, write a "
        ".md file and send it.\n"
        "LIMITS: chunked at 4000 characters, cut at the last newline or space (never "
        "mid-word), max 5 chunks — past ~20000 characters the rest is dropped. This is a "
        "phone chat: keep it compact, verdict first, and prefer short lines to long ones."
    )

    def __init__(
        self,
        *,
        token: str,
        owner_ids: set[str],
        allowed_chat_ids: set[str],
        remediation: str = "",
        offset_path: Path,
        media_root: Path | None = None,
    ) -> None:
        if not token:
            raise ContractError("TELEGRAM_CONFIG", "bot token is required")
        self._token = token
        self.owner_ids = {str(item) for item in owner_ids}
        self.allowed_chat_ids = {str(item) for item in allowed_chat_ids}
        # how THIS host actually allow-lists a room. Inheriting Aiko's
        # "config.telegram.allowed_chat_ids" sent owners to a key that does
        # not exist here, so the instruction was unfollowable.
        self.remediation = remediation or (
            "If this was you, add the id to `config.telegram.allowed_chat_ids` and restart.")
        self.offset_path = offset_path
        self.media_root = media_root or offset_path.parent / "media"
        self.bot_id = ""
        self.bot_username = ""
        self.hears_all_group_messages = False
        # Roster: every actor ever observed per room, bots included. Telegram
        # never streams one bot's MESSAGES to another bot and has no member
        # enumeration API, so a bot only becomes visible via a member update,
        # the admin list, or a message we are allowed to see — this accrues
        # exactly those. {room_id: {actor_id: {...}}}
        self.roster: dict[str, dict[str, dict[str, Any]]] = {}
        # message_ids I have sent, per room. "Is this a reply to ME?" cannot be
        # answered from reply.from.id in a broadcast CHANNEL, where my own posts
        # are attributed to the channel and carry no from.id at all. Bounded and
        # run-scoped: after a restart, channel reply-detection relies on from.id
        # again (which is enough in groups and supergroups).
        self._my_messages: dict[str, list[str]] = {}
        # Per-INSTANCE. This used to be a class attribute, so two transports in
        # one process shared one set and the second one to see a room stayed
        # silent about it — the alert is once per room, not once per program.
        self._refused_rooms: set[str] = set()

    def _remember_sent(self, room_id: str, message_id: str) -> None:
        if not room_id or not message_id:
            return
        recent = self._my_messages.setdefault(str(room_id), [])
        recent.append(str(message_id))
        del recent[:-500]

    def _note_actor(self, room_id: str, actor_id: str, name: str, handle: str, is_bot: bool, *, status: str = "") -> None:
        if not room_id or not actor_id:
            return
        room = self.roster.setdefault(room_id, {})
        record = room.setdefault(actor_id, {"id": actor_id, "first_seen": time.time()})
        record.update({"name": name or record.get("name", ""), "handle": handle or record.get("handle", ""),
                       "is_bot": is_bot or record.get("is_bot", False), "last_seen": time.time()})
        if status:
            record["status"] = status

    def known_actors(self, room_id: str) -> list[dict[str, Any]]:
        return list(self.roster.get(room_id, {}).values())

    def connect(self) -> dict[str, Any]:
        """Resolve own identity FIRST; report the privacy-mode state honestly."""
        result = _ok(_api(self._token, "getMe", {}, timeout=15), "getMe")
        if not isinstance(result, Mapping):
            raise ContractError("TELEGRAM_AUTH", "getMe failed — token invalid?")
        self.bot_id = str(result.get("id") or "")
        self.bot_username = str(result.get("username") or "")
        self.hears_all_group_messages = result.get("can_read_all_group_messages") is True
        if not self.bot_id or not self.bot_username:
            raise ContractError("TELEGRAM_AUTH", "getMe returned no id/username")
        return {
            "bot_id": self.bot_id,
            "bot_username": self.bot_username,
            "hears_all_group_messages": self.hears_all_group_messages,
        }

    # ── inbound ─────────────────────────────────────────────────────────
    def _load_offset(self) -> int | None:
        if not self.offset_path.is_file():
            return None
        try:
            return int(json.loads(self.offset_path.read_text(encoding="utf-8"))["offset"])
        except (ValueError, KeyError, TypeError, OSError) as exc:
            print(f"[presence] SILENT-GUARD FIRED in _load_offset: "
                  f"{type(exc).__name__}: {exc} — a Telegram message the owner never receives, with no log", flush=True)
            return None

    def _commit_offset(self, update_id: int) -> None:
        self.offset_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self.offset_path, {"offset": update_id + 1})

    def _download_attachments(self, message: Mapping[str, Any], room_id: str, event_id: str) -> tuple[dict[str, Any], ...]:
        found: list[dict[str, Any]] = []
        for kind in _MEDIA_KINDS:
            item = message.get(kind)
            if kind == "photo":
                photos = message.get("photo")
                item = photos[-1] if isinstance(photos, list) and photos else None
            if not isinstance(item, Mapping):
                continue
            file_id = item.get("file_id")
            size = item.get("file_size")
            if not isinstance(file_id, str):
                continue
            if isinstance(size, int) and size > _MAX_DOWNLOAD:
                found.append({"kind": kind, "path": None, "note": f"skipped: {size} bytes exceeds the 20MB Bot API download cap"})
                continue
            try:
                info = _ok(_api(self._token, "getFile", {"file_id": file_id}, timeout=30), "getFile")
                remote = info.get("file_path") if isinstance(info, Mapping) else None
                if not isinstance(remote, str) or ".." in remote:
                    continue
                url = f"https://api.telegram.org/file/bot{self._token}/{remote}"
                target_dir = self.media_root / room_id / event_id
                target_dir.mkdir(parents=True, exist_ok=True)
                name = (item.get("file_name") if isinstance(item.get("file_name"), str) else None) or Path(remote).name
                target = target_dir / name
                with urllib.request.urlopen(url, timeout=120) as stream:
                    data = stream.read(_MAX_DOWNLOAD + 1)
                if len(data) > _MAX_DOWNLOAD:
                    found.append({"kind": kind, "path": None, "note": "skipped: exceeded 20MB during download"})
                    continue
                target.write_bytes(data)
                found.append({
                    "kind": kind,
                    "path": str(target),
                    "mime": item.get("mime_type"),
                    "bytes": len(data),
                    "name": name,
                })
            except (ContractError, OSError) as exc:
                found.append({"kind": kind, "path": None, "note": f"download failed: {type(exc).__name__}"})
        return tuple(found)

    # ── modes of address: dm | reply | ping | passive ───────────────────
    # A DM is already directed at me, so it needs no ping. A group or channel
    # is a room full of other people's conversation, so it needs an explicit
    # reply or @mention — anything else is "passive": heard and recorded, not
    # answered. `addressed` is only "was I spoken to"; whether I am ALLOWED to
    # answer is a separate question, decided by _in_reach against the whitelist.
    def _mentions_me(self, message: Mapping[str, Any], text: str) -> bool:
        if not self.bot_username:
            return False
        handle = f"@{self.bot_username}".lower()
        for key in ("entities", "caption_entities"):
            for entity in message.get(key) or []:
                if not isinstance(entity, Mapping) or entity.get("type") != "mention":
                    continue
                offset, length = entity.get("offset"), entity.get("length")
                if isinstance(offset, int) and isinstance(length, int):
                    if text[offset:offset + length].lower() == handle:
                        return True
        # Entity offsets are UTF-16 units, so an emoji before the mention shifts
        # them out of step with Python indices — the substring check catches it.
        return handle in text.lower()

    def _is_reply_to_me(self, message: Mapping[str, Any], chat_id: str) -> bool:
        reply = message.get("reply_to_message")
        if not isinstance(reply, Mapping):
            return False
        sender = reply.get("from") if isinstance(reply.get("from"), Mapping) else {}
        if self.bot_id and str(sender.get("id") or "") == self.bot_id:
            return True
        return str(reply.get("message_id") or "") in self._my_messages.get(str(chat_id), [])

    def _address_mode(self, message: Mapping[str, Any], chat_id: str, text: str, *, private: bool) -> str:
        if private:
            return "dm"
        if self._is_reply_to_me(message, chat_id):
            return "reply"
        if self._mentions_me(message, text):
            return "ping"
        return "passive"

    def _message_inbound(self, message: Mapping[str, Any], *, kind: str, update_id: int) -> Inbound:
        chat = message.get("chat") if isinstance(message.get("chat"), Mapping) else {}
        sender = message.get("from") if isinstance(message.get("from"), Mapping) else {}
        chat_id = str(chat.get("id") or "")
        chat_type = str(chat.get("type") or "private")
        actor_id = str(sender.get("id") or "")
        text = message.get("text") if isinstance(message.get("text"), str) else ""
        if not text:
            caption = message.get("caption")
            text = caption if isinstance(caption, str) else ""
        reply = message.get("reply_to_message") if isinstance(message.get("reply_to_message"), Mapping) else None
        reply_text = (reply.get("text") if reply and isinstance(reply.get("text"), str) else "") or ""
        is_owner = actor_id in self.owner_ids
        private = chat_type == "private"
        mode = self._address_mode(message, chat_id, text, private=private)
        event_id = str(message.get("message_id") or update_id)
        room_kind = "private" if private else ("channel" if chat_type == "channel" else "group")
        self._note_actor(chat_id, actor_id, str(sender.get("first_name") or ""), str(sender.get("username") or ""), sender.get("is_bot") is True)
        attachments = ()
        if kind in ("message", "channel_post") and any(k in message for k in _MEDIA_KINDS):
            attachments = self._download_attachments(message, chat_id, event_id)
            if not text.strip() and attachments:
                kinds = sorted({str(a.get("kind")) for a in attachments})
                text = f"[attachment: {', '.join(kinds)}]"
        return Inbound(
            channel="telegram",
            room_id=chat_id,
            room_kind=room_kind,
            event_id=event_id,
            actor_id=actor_id,
            actor_name=str(sender.get("first_name") or chat.get("title") or ""),
            actor_handle=str(sender.get("username") or ""),
            actor_is_bot=sender.get("is_bot") is True,
            text=text,
            # A channel post and an edit are addressed by exactly the same three
            # modes as a fresh message. The old rule hardcoded kind == "message",
            # so an @mention of the bot in a CHANNEL could never be answered —
            # no whitelist setting could have fixed that.
            addressed=mode != "passive",
            is_owner=is_owner,
            reply_to_text=reply_text[:1000],
            kind=kind,
            detail={"mode": mode},
            attachments=attachments,
            # Telegram's own send time. After an outage the offset replays every
            # missed update at once, so this is the only thing distinguishing a
            # message sent seconds ago from one sent hours ago.
            sent_at=float(message.get("date") or 0.0),
        )

    def _normalize(self, update: Mapping[str, Any]) -> Inbound | None:
        update_id = int(update.get("update_id") or 0)
        for field, kind in (
            ("message", "message"), ("edited_message", "edited"),
            ("channel_post", "channel_post"), ("edited_channel_post", "channel_post"),
        ):
            payload = update.get(field)
            if isinstance(payload, Mapping):
                return self._message_inbound(payload, kind=kind, update_id=update_id)
        reaction = update.get("message_reaction")
        if isinstance(reaction, Mapping):
            chat = reaction.get("chat") if isinstance(reaction.get("chat"), Mapping) else {}
            user = reaction.get("user") if isinstance(reaction.get("user"), Mapping) else {}
            new = reaction.get("new_reaction")
            emoji = ""
            if isinstance(new, list) and new and isinstance(new[0], Mapping):
                emoji = str(new[0].get("emoji") or new[0].get("custom_emoji_id") or "")
            return Inbound(
                channel="telegram", room_id=str(chat.get("id") or ""), room_kind="group",
                event_id=f"react-{reaction.get('message_id')}-{update_id}",
                actor_id=str(user.get("id") or ""), actor_name=str(user.get("first_name") or ""),
                actor_handle=str(user.get("username") or ""), actor_is_bot=user.get("is_bot") is True,
                text=emoji, addressed=False, is_owner=str(user.get("id") or "") in self.owner_ids,
                kind="reaction", detail={"message_id": str(reaction.get("message_id") or "")},
            )
        member = update.get("chat_member") or update.get("my_chat_member")
        if isinstance(member, Mapping):
            chat = member.get("chat") if isinstance(member.get("chat"), Mapping) else {}
            fresh = member.get("new_chat_member") if isinstance(member.get("new_chat_member"), Mapping) else {}
            who = fresh.get("user") if isinstance(fresh.get("user"), Mapping) else {}
            self._note_actor(str(chat.get("id") or ""), str(who.get("id") or ""),
                             str(who.get("first_name") or ""), str(who.get("username") or ""),
                             who.get("is_bot") is True, status=str(fresh.get("status") or ""))
            return Inbound(
                channel="telegram", room_id=str(chat.get("id") or ""), room_kind="group",
                event_id=f"member-{update_id}",
                actor_id=str(who.get("id") or ""), actor_name=str(who.get("first_name") or ""),
                actor_handle=str(who.get("username") or ""), actor_is_bot=who.get("is_bot") is True,
                text=str(fresh.get("status") or ""), addressed=False,
                is_owner=str(who.get("id") or "") in self.owner_ids,
                kind="member", detail={"status": str(fresh.get("status") or "")},
            )
        callback = update.get("callback_query")
        if isinstance(callback, Mapping):
            user = callback.get("from") if isinstance(callback.get("from"), Mapping) else {}
            message = callback.get("message") if isinstance(callback.get("message"), Mapping) else {}
            chat = message.get("chat") if isinstance(message.get("chat"), Mapping) else {}
            # A button pressed in a DM is a PRIVATE room. Hardcoding "group" here
            # made every callback look like an uninvited group chat, so the
            # allow-list refused it and the family's [Called back] button never
            # closed an escalation — it answered the owner with a security alert
            # naming their own DM as a group.
            _ct = str(chat.get("type") or "private")
            _kind = "private" if _ct == "private" else ("channel" if _ct == "channel" else "group")
            return Inbound(
                channel="telegram", room_id=str(chat.get("id") or ""), room_kind=_kind,
                event_id=str(callback.get("id") or update_id),
                actor_id=str(user.get("id") or ""), actor_name=str(user.get("first_name") or ""),
                actor_handle=str(user.get("username") or ""), actor_is_bot=False,
                text=str(callback.get("data") or ""), addressed=True,
                is_owner=str(user.get("id") or "") in self.owner_ids,
                kind="callback", detail={"callback_id": str(callback.get("id") or "")},
            )
        poll_answer = update.get("poll_answer")
        if isinstance(poll_answer, Mapping):
            user = poll_answer.get("user") if isinstance(poll_answer.get("user"), Mapping) else {}
            return Inbound(
                channel="telegram", room_id="", room_kind="group",
                event_id=f"pollans-{update_id}",
                actor_id=str(user.get("id") or ""), actor_name=str(user.get("first_name") or ""),
                actor_handle=str(user.get("username") or ""), actor_is_bot=False,
                text=json.dumps(poll_answer.get("option_ids") or []), addressed=False,
                is_owner=str(user.get("id") or "") in self.owner_ids,
                kind="poll_answer", detail={"poll_id": str(poll_answer.get("poll_id") or "")},
            )
        poll = update.get("poll")
        if isinstance(poll, Mapping):
            return Inbound(
                channel="telegram", room_id="", room_kind="group",
                event_id=f"poll-{poll.get('id') or update_id}",
                actor_id="", actor_name="", actor_handle="", actor_is_bot=False,
                text=str(poll.get("question") or ""), addressed=False, is_owner=False,
                kind="poll", detail={
                    "poll_id": str(poll.get("id") or ""),
                    "is_closed": poll.get("is_closed") is True,
                    "options": [
                        {"text": str(o.get("text") or ""), "votes": int(o.get("voter_count") or 0)}
                        for o in (poll.get("options") or []) if isinstance(o, Mapping)
                    ],
                },
            )
        join = update.get("chat_join_request")
        if isinstance(join, Mapping):
            chat = join.get("chat") if isinstance(join.get("chat"), Mapping) else {}
            user = join.get("from") if isinstance(join.get("from"), Mapping) else {}
            return Inbound(
                channel="telegram", room_id=str(chat.get("id") or ""), room_kind="group",
                event_id=f"join-{update_id}",
                actor_id=str(user.get("id") or ""), actor_name=str(user.get("first_name") or ""),
                actor_handle=str(user.get("username") or ""), actor_is_bot=False,
                text="requested to join", addressed=False,
                is_owner=str(user.get("id") or "") in self.owner_ids,
                kind="join_request",
            )
        return None

    # A refusal the owner cannot see is indistinguishable from a dead bot
    # (owner 2026-07-26: "your bots have 0 defence mechanism… anyone can talk
    # to them?" — the defence was working perfectly and silently, which is the
    # same law we already wrote: deterministic code may decide, never in
    # silence). One line per NEW room, so a hostile flood cannot spam the log.
    def _in_reach(self, inbound: Inbound) -> bool:
        # My OWN messages come back as updates — pinning a message makes Telegram
        # emit a service message authored by me. That is not an intruder, so it
        # is dropped without a refusal log and without waking the owner. Left
        # unhandled, every /pin fired a "refused a room I was not invited to"
        # alert at the owner about their own room (live, 2026-08-04).
        if inbound.actor_id and inbound.actor_id == self.bot_id:
            return False
        allowed = self._in_reach_verdict(inbound)
        if not allowed:
            key = f"{inbound.room_kind}:{inbound.room_id}"
            # anan correction: every refusal also reaches a host-installed hook,
            # so the refused sender's id lands in the receipt store — identity
            # gets adopted from EVIDENCE, not guessed from env files.
            hook = getattr(self, "on_refused", None)
            if hook:
                try:
                    hook(inbound)
                except Exception:
                    pass
            if key not in self._refused_rooms:
                self._refused_rooms.add(key)
                reason = ("actor is not an owner" if not inbound.is_owner
                          else "chat id is not in allowed_chat_ids")
                print(f"[telegram] REFUSED {inbound.room_kind} {inbound.room_id} "
                      f"({reason}) — message dropped before the brain. {self.remediation}",
                      flush=True)
                # TELL THE OWNER (owner 2026-07-26: "should send a message to me
                # at least, there's only one owner per adaptor and it's a
                # constant"). A refusal is a security event: someone put this
                # agent somewhere it was not invited, and the owner is the only
                # one who can judge whether that is fine. Once per room, never
                # fatal — a failed alert must not take down polling.
                try:
                    owner = next(iter(self.owner_ids), "")
                    if owner:
                        who = inbound.actor_name or inbound.actor_handle or inbound.actor_id
                        # MARKDOWN, not HTML: send() runs everything through
                        # to_telegram_html(), which escapes literal tags — the
                        # old <b> here reached the owner as "&lt;b&gt;".
                        self.send(owner, "\n".join([
                            "**Refused a room I was not invited to**",
                            f"{inbound.room_kind} `{inbound.room_id}`",
                            f"added/spoken by: {who}",
                            f"reason: {reason}",
                            "Nothing reached my brain and nothing was answered.",
                            self.remediation,
                        ]))
                except Exception as exc:
                    print(f"[telegram] could not alert the owner about {inbound.room_id} "
                          f"({type(exc).__name__}) — the refusal still held", flush=True)
        return allowed

    def _in_reach_verdict(self, inbound: Inbound) -> bool:
        if inbound.room_kind == "private":
            return inbound.is_owner
        if not inbound.room_id:
            return False  # poll/poll_answer updates have no room to reply into
        # Empty means no group access, never unrestricted. A shell-capable agent
        # must not accept prompts merely because someone invited its bot token.
        return inbound.is_owner and inbound.room_id in self.allowed_chat_ids

    def poll_forever(
        self,
        handler: Callable[[Inbound, Any], str | None],
        *,
        stop: Callable[[], bool],
    ) -> None:
        """Long-poll; commit the offset only AFTER the handler returns."""
        while not stop():
            body: dict[str, Any] = {"timeout": 30, "limit": 100, "allowed_updates": ALLOWED_UPDATES}
            offset = self._load_offset()
            if offset is not None:
                body["offset"] = offset
            try:
                payload = _api(self._token, "getUpdates", body, timeout=45)
            except ContractError:
                time.sleep(3)
                continue
            if payload.get("ok") is not True or not isinstance(payload.get("result"), list):
                time.sleep(5 if str(payload.get("error_code")) == "409" else 3)
                continue
            for update in payload["result"]:
                if not isinstance(update, Mapping) or not isinstance(update.get("update_id"), int):
                    continue
                inbound = self._normalize(update)
                if inbound is not None and self._in_reach(inbound):
                    # The handler must never block or kill polling: one slow or
                    # crashing turn made the whole bot deaf (live, 2026-07-19).
                    try:
                        answer = handler(inbound, self)
                        if answer:
                            self.send(
                                inbound.room_id,
                                str(answer),
                                reply_to_event_id=inbound.event_id,
                            )
                    except Exception:
                        import traceback
                        print(f"[telegram] handler crashed on update {update['update_id']}:", flush=True)
                        traceback.print_exc()
                self._commit_offset(update["update_id"])

    # ── outbound: text ──────────────────────────────────────────────────
    def typing(self, room_id: str, action: str = "typing") -> None:
        try:
            _api(self._token, "sendChatAction", {"chat_id": room_id, "action": action}, timeout=10)
        except ContractError as exc:
            print(f"[presence] SILENT-GUARD FIRED in typing: "
                  f"{type(exc).__name__}: {exc} — a Telegram message the owner never receives, with no log", flush=True)
            pass

    def send(
        self,
        room_id: str,
        text: str,
        *,
        reply_to_event_id: str | None = None,
        buttons: list[list[dict[str, str]]] | None = None,
    ) -> list[str]:
        """Chunked text send; optional inline keyboard rides the last chunk.

        Renders the agent's markdown to Telegram HTML (owner 2026-07-22: raw
        `**`/`##` were showing as literal symbols). Chunking is done on the
        RAW markdown (so a tag never splits across a chunk), then each chunk is
        converted; a chunk Telegram rejects for a formatting reason is retried
        as plain text, so a message is never lost to markup."""
        text = text.strip() or "…"
        chunks: list[str] = []
        remaining = text
        while remaining and len(chunks) < _MAX_CHUNKS:
            if len(remaining) <= _MAX_MESSAGE:
                chunks.append(remaining)
                break
            cut = remaining.rfind("\n", 0, _MAX_MESSAGE + 1)
            if cut < _MAX_MESSAGE // 2:
                cut = remaining.rfind(" ", 0, _MAX_MESSAGE + 1)
            if cut < _MAX_MESSAGE // 2:
                cut = _MAX_MESSAGE
            chunks.append(remaining[:cut].rstrip())
            remaining = remaining[cut:].lstrip()
        # Every chunk is a message he has to attribute, so every chunk is
        # stamped — see keel/presence/stamp.py for the standard. Stamped AFTER
        # chunking so the markdown split never cuts through the stamp itself.
        chunks = [self.stamp(chunk) for chunk in chunks]
        from adapter.tg_format import to_plaintext, to_telegram_html
        message_ids: list[str] = []
        for index, chunk in enumerate(chunks):
            body: dict[str, Any] = {"chat_id": room_id, "text": to_telegram_html(chunk),
                                    "parse_mode": "HTML",
                                    "link_preview_options": {"is_disabled": True}}
            if index == 0 and reply_to_event_id:
                body["reply_parameters"] = {"message_id": int(reply_to_event_id), "allow_sending_without_reply": True}
            if buttons and index == len(chunks) - 1:
                body["reply_markup"] = {"inline_keyboard": buttons}
            try:
                message_ids.append(self._send_with_retry("sendMessage", body))
            except ContractError:
                # HTML rejected (a stray tag / entity we didn't catch) — a
                # message is never lost to formatting: resend as plain text.
                plain = dict(body)
                plain.pop("parse_mode", None)
                plain["text"] = to_plaintext(chunk)
                message_ids.append(self._send_with_retry("sendMessage", plain))
        for message_id in message_ids:
            self._remember_sent(room_id, message_id)  # so a reply to this counts as "reply" mode
        return message_ids

    def _send_with_retry(self, method: str, body: Mapping[str, Any]) -> str:
        payload = _api(self._token, method, body, timeout=30)
        if payload.get("ok") is not True:
            parameters = payload.get("parameters")
            retry_after = parameters.get("retry_after") if isinstance(parameters, Mapping) else None
            if isinstance(retry_after, (int, float)) and retry_after >= 0:
                time.sleep(min(float(retry_after), 30.0) + 0.5)
                payload = _api(self._token, method, body, timeout=30)
        result = _ok(payload, method)
        if isinstance(result, Mapping) and result.get("message_id") is not None:
            return str(result["message_id"])
        return ""

    # ── outbound: media ─────────────────────────────────────────────────
    def send_media(
        self,
        room_id: str,
        kind: str,
        source: str,
        *,
        caption: str = "",
        reply_to_event_id: str | None = None,
    ) -> str:
        """kind: photo|document|voice|video|animation|sticker.
        source: local path, https URL, or Telegram file_id."""
        methods = {
            "photo": ("sendPhoto", "photo"), "document": ("sendDocument", "document"),
            "voice": ("sendVoice", "voice"), "video": ("sendVideo", "video"),
            "animation": ("sendAnimation", "animation"), "sticker": ("sendSticker", "sticker"),
        }
        if kind not in methods:
            raise ContractError("TELEGRAM_MEDIA", f"unknown media kind {kind!r}")
        from adapter.tg_format import to_plaintext, to_telegram_html
        method, field = methods[kind]
        path = Path(source)
        fields: dict[str, str] = {"chat_id": str(room_id)}
        if reply_to_event_id:
            fields["reply_parameters"] = json.dumps({"message_id": int(reply_to_event_id), "allow_sending_without_reply": True})

        # The caption is this message's only text, so it is where the stamp
        # goes — force=True because a caption-less attachment is still a
        # message the owner has to attribute. Room for the stamp is reserved
        # inside Telegram's 1024-char caption limit.
        # BOUNDARY: a sticker has no caption field on this platform at all,
        # so it is the one outbound path here that cannot carry the stamp.
        html: dict[str, str] = {}
        plain: dict[str, str] = {}
        if kind != "sticker":
            stamped = self.stamp(caption[:950], force=True)
            if stamped:
                html = {"caption": to_telegram_html(stamped), "parse_mode": "HTML"}
                plain = {"caption": to_plaintext(stamped)}

        def _post(extra: Mapping[str, str]) -> Mapping[str, Any]:
            sending = {**fields, **extra}
            if path.is_file():
                return _api_multipart(self._token, method, sending, field, path, timeout=180)
            body: dict[str, Any] = dict(sending)
            body[field] = source  # URL or file_id pass-through
            return _api(self._token, method, body, timeout=60)

        try:
            result = _ok(_post(html), method)
        except ContractError:
            if not html:
                raise
            # never lose the media to caption formatting — same fallback send() uses
            result = _ok(_post(plain), method)
        message_id = str(result.get("message_id")) if isinstance(result, Mapping) else ""
        self._remember_sent(room_id, message_id)
        return message_id

    # ── outbound: everything else ───────────────────────────────────────
    def react(self, room_id: str, message_id: str, emoji: str | None = "👀") -> bool:
        """Set (or with emoji=None, clear) a reaction. Silently False where not permitted."""
        try:
            payload = _api(self._token, "setMessageReaction", {
                "chat_id": room_id, "message_id": int(message_id),
                "reaction": [{"type": "emoji", "emoji": emoji}] if emoji else [],
            }, timeout=10)
            return payload.get("ok") is True
        except (ContractError, ValueError) as exc:
            print(f"[presence] SILENT-GUARD FIRED in react: "
                  f"{type(exc).__name__}: {exc} — a Telegram message the owner never receives, with no log", flush=True)
            return False

    # ── read verbs (the R in CRUD) ──────────────────────────────────────
    def get_chat(self, room_id: str) -> dict[str, Any]:
        """Room info: title, kind, description, pinned message."""
        result = _ok(_api(self._token, "getChat", {"chat_id": room_id}, timeout=15), "getChat")
        if not isinstance(result, Mapping):
            return {}
        pinned = result.get("pinned_message") if isinstance(result.get("pinned_message"), Mapping) else None
        return {
            "title": str(result.get("title") or result.get("first_name") or ""),
            "kind": str(result.get("type") or ""),
            "description": str(result.get("description") or "")[:500],
            "pinned_message": {
                "message_id": str(pinned.get("message_id") or ""),
                "text": str(pinned.get("text") or pinned.get("caption") or "")[:500],
            } if pinned else None,
        }

    def get_member_count(self, room_id: str) -> int:
        result = _ok(_api(self._token, "getChatMemberCount", {"chat_id": room_id}, timeout=15), "getChatMemberCount")
        return int(result) if isinstance(result, int) else 0

    def get_admins(self, room_id: str) -> list[dict[str, Any]]:
        result = _ok(_api(self._token, "getChatAdministrators", {"chat_id": room_id}, timeout=15), "getChatAdministrators")
        admins: list[dict[str, Any]] = []
        for member in result if isinstance(result, list) else []:
            if not isinstance(member, Mapping):
                continue
            user = member.get("user") if isinstance(member.get("user"), Mapping) else {}
            entry = {
                "id": str(user.get("id") or ""),
                "name": str(user.get("first_name") or ""),
                "handle": str(user.get("username") or ""),
                "is_bot": user.get("is_bot") is True,
                "status": str(member.get("status") or ""),
            }
            admins.append(entry)
            self._note_actor(room_id, entry["id"], entry["name"], entry["handle"], entry["is_bot"], status=entry["status"])
        return admins

    def get_member(self, room_id: str, user_id: str) -> dict[str, Any]:
        result = _ok(_api(self._token, "getChatMember", {"chat_id": room_id, "user_id": int(user_id)}, timeout=15), "getChatMember")
        if not isinstance(result, Mapping):
            return {}
        user = result.get("user") if isinstance(result.get("user"), Mapping) else {}
        return {
            "id": str(user.get("id") or ""),
            "name": str(user.get("first_name") or ""),
            "handle": str(user.get("username") or ""),
            "is_bot": user.get("is_bot") is True,
            "status": str(result.get("status") or ""),
        }

    def edit(self, room_id: str, message_id: str, text: str) -> bool:
        # An edit REPLACES what the room reads, so it is a message in its own
        # right: truncate first, stamp after (exactly like send()), and render
        # the agent's markdown the same way — an unrendered edit showed literal
        # `**` and a stamp in raw backticks.
        from adapter.tg_format import to_plaintext, to_telegram_html
        stamped = self.stamp(text[:_MAX_MESSAGE])
        body: dict[str, Any] = {
            "chat_id": room_id, "message_id": int(message_id),
            "text": to_telegram_html(stamped), "parse_mode": "HTML",
        }
        payload = _api(self._token, "editMessageText", body, timeout=20)
        if payload.get("ok") is True:
            return True
        # never lose an edit to formatting — same fallback send() uses, and only
        # for a formatting refusal ("message is not modified" must not re-send).
        description = str(payload.get("description") or "").lower()
        if not any(word in description for word in ("parse", "entit", "tag")):
            return False
        plain = dict(body)
        plain.pop("parse_mode", None)
        plain["text"] = to_plaintext(stamped)
        return _api(self._token, "editMessageText", plain, timeout=20).get("ok") is True

    def delete(self, room_id: str, message_id: str) -> bool:
        payload = _api(self._token, "deleteMessage", {"chat_id": room_id, "message_id": int(message_id)}, timeout=15)
        return payload.get("ok") is True

    def pin(self, room_id: str, message_id: str, *, unpin: bool = False) -> bool:
        method = "unpinChatMessage" if unpin else "pinChatMessage"
        payload = _api(self._token, method, {
            "chat_id": room_id, "message_id": int(message_id),
            **({} if unpin else {"disable_notification": True}),
        }, timeout=15)
        return payload.get("ok") is True

    def send_poll(self, room_id: str, question: str, options: list[str], *, anonymous: bool = True) -> dict[str, str]:
        """Returns {message_id, poll_id}. Counts later need stop_poll (no getPoll API).

        BOUNDARY — the stamp: sendPoll carries no text or caption field, only a
        300-char question and its options, so a Telegram poll cannot hold the
        provenance line the way every other outbound path here does. Discord's
        poll CAN (content rides with it) and does — see discord_gw.send_poll.
        This is a platform limit, declared here and asserted by
        tools/poc_usage_header.py so it stays a known boundary rather than
        drifting back into a silent escape.
        """
        result = _ok(_api(self._token, "sendPoll", {
            "chat_id": room_id, "question": question[:300],
            "options": [{"text": o[:100]} for o in options[:10]],
            "is_anonymous": anonymous,
        }, timeout=20), "sendPoll")
        poll = result.get("poll") if isinstance(result, Mapping) else {}
        return {
            "message_id": str(result.get("message_id") or "") if isinstance(result, Mapping) else "",
            "poll_id": str(poll.get("id") or "") if isinstance(poll, Mapping) else "",
        }

    def stop_poll(self, room_id: str, message_id: str) -> list[dict[str, Any]]:
        result = _ok(_api(self._token, "stopPoll", {"chat_id": room_id, "message_id": int(message_id)}, timeout=15), "stopPoll")
        options = result.get("options") if isinstance(result, Mapping) else []
        return [
            {"text": str(o.get("text") or ""), "votes": int(o.get("voter_count") or 0)}
            for o in options if isinstance(o, Mapping)
        ]

    # ── moderation (bot must be admin with can_restrict_members) ─────────
    _MUTE_PERMS = (
        "can_send_messages", "can_send_audios", "can_send_documents", "can_send_photos",
        "can_send_videos", "can_send_video_notes", "can_send_voice_notes", "can_send_polls",
        "can_send_other_messages", "can_add_web_page_previews",
    )

    def ban_member(self, room_id: str, user_id: str, *, reason: str = "") -> str:
        del reason  # Telegram ban carries no reason field
        _ok(_api(self._token, "banChatMember", {"chat_id": room_id, "user_id": int(user_id)}, timeout=15), "banChatMember")
        return "banned (removed from the group and blocked from rejoining)"

    def unban_member(self, room_id: str, user_id: str) -> str:
        # only_if_banned so unbanning a present member doesn't force-add them.
        _ok(_api(self._token, "unbanChatMember", {"chat_id": room_id, "user_id": int(user_id), "only_if_banned": True}, timeout=15), "unbanChatMember")
        return "unbanned (may rejoin with an invite)"

    def kick_member(self, room_id: str, user_id: str) -> str:
        # Telegram has no pure kick: ban then immediately unban = removed, may rejoin.
        _ok(_api(self._token, "banChatMember", {"chat_id": room_id, "user_id": int(user_id)}, timeout=15), "banChatMember")
        _ok(_api(self._token, "unbanChatMember", {"chat_id": room_id, "user_id": int(user_id), "only_if_banned": True}, timeout=15), "unbanChatMember")
        return "kicked (removed; may rejoin with an invite)"

    def mute_member(self, room_id: str, user_id: str, *, seconds: int = 0) -> str:
        """Revoke all send permissions (Discord-timeout equivalent). seconds=0 = until lifted."""
        params: dict[str, Any] = {
            "chat_id": room_id, "user_id": int(user_id),
            "permissions": {perm: False for perm in self._MUTE_PERMS},
        }
        if seconds > 0:
            params["until_date"] = int(time.time()) + max(30, min(seconds, 366 * 24 * 3600))
        _ok(_api(self._token, "restrictChatMember", params, timeout=15), "restrictChatMember")
        return f"muted{f' for ~{seconds}s' if seconds > 0 else ' until lifted'}"

    def unmute_member(self, room_id: str, user_id: str) -> str:
        params = {
            "chat_id": room_id, "user_id": int(user_id),
            "permissions": {perm: True for perm in self._MUTE_PERMS},
        }
        _ok(_api(self._token, "restrictChatMember", params, timeout=15), "restrictChatMember")
        return "unmuted (send permissions restored)"

    def answer_callback(self, callback_id: str, text: str = "") -> None:
        try:
            _api(self._token, "answerCallbackQuery", {"callback_query_id": callback_id, **({"text": text[:200]} if text else {})}, timeout=10)
        except ContractError as exc:
            # If this fails, the button spins forever and the owner cannot tell
            # whether the press landed (#84) — the one failure that must be loud.
            print(f"[telegram] answerCallbackQuery FAILED — the button will keep "
                  f"spinning: {exc.code}: {exc.message[:150]}", flush=True)

    def set_commands(self, commands: list[tuple[str, str]]) -> bool:
        payload = _api(self._token, "setMyCommands", {
            "commands": [{"command": c, "description": d[:256]} for c, d in commands[:100]],
        }, timeout=15)
        return payload.get("ok") is True
