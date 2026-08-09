"""Small Discord gateway adapter built on discord.py 2.x."""

from __future__ import annotations

import asyncio
from typing import Any, Callable

from adapter.base import ContractError
from adapter.contract import Inbound
from adapter.stamp import StampsOutbound


class DiscordTransport(StampsOutbound):
    subtext_prefix = "-# "

    def __init__(
        self,
        *,
        token: str,
        owner_ids: set[str],
        allowed_guild_ids: set[str],
        allowed_channel_ids: set[str],
    ) -> None:
        if not token:
            raise ContractError("DISCORD_CONFIG", "bot token is required")
        if not owner_ids:
            raise ContractError("DISCORD_CONFIG", "at least one owner id is required")
        self._token = token
        self.owner_ids = {str(item) for item in owner_ids}
        self.allowed_guild_ids = {str(item) for item in allowed_guild_ids}
        self.allowed_channel_ids = {str(item) for item in allowed_channel_ids}
        self.bot_id = ""
        self.bot_username = ""

    @staticmethod
    def is_addressed(*, is_dm: bool, is_owner: bool, mentioned: bool, reply_to_bot: bool) -> bool:
        return (is_dm and is_owner) or mentioned or reply_to_bot

    def in_reach(self, *, is_dm: bool, is_owner: bool, guild_id: str, channel_id: str) -> bool:
        if not is_owner:
            return False
        if is_dm:
            return True
        if not self.allowed_guild_ids or guild_id not in self.allowed_guild_ids:
            return False
        return not self.allowed_channel_ids or channel_id in self.allowed_channel_ids

    def run(self, handler: Callable[[Inbound, Any], str | None], *, stop: Callable[[], bool]) -> None:
        try:
            import discord
        except ImportError as exc:
            raise ContractError("DISCORD_DEPENDENCY", "install requirements.txt first") from exc

        intents = discord.Intents.none()
        intents.guilds = True
        intents.guild_messages = True
        intents.dm_messages = True
        intents.message_content = True
        client = discord.Client(intents=intents)
        tree = discord.app_commands.CommandTree(client)
        transport = self
        synced = False

        def interaction_inbound(interaction: Any, command_text: str) -> Inbound:
            guild = getattr(interaction, "guild", None)
            user = interaction.user
            return Inbound(
                channel="discord",
                room_id=str(interaction.channel_id or ""),
                room_kind="private" if guild is None else "group",
                event_id=str(interaction.id),
                actor_id=str(user.id),
                actor_name=str(getattr(user, "display_name", user.name)),
                actor_handle=str(user.name),
                actor_is_bot=bool(getattr(user, "bot", False)),
                text=command_text,
                addressed=True,
                is_owner=str(user.id) in transport.owner_ids,
                server_id=str(guild.id) if guild else "",
            )

        async def handle_slash(interaction: Any, command_text: str) -> None:
            inbound = interaction_inbound(interaction, command_text)
            if not transport.in_reach(
                is_dm=inbound.room_kind == "private",
                is_owner=inbound.is_owner,
                guild_id=inbound.server_id,
                channel_id=inbound.room_id,
            ):
                await interaction.response.send_message("This command is owner-only here.", ephemeral=True)
                return
            await interaction.response.defer(thinking=True)
            try:
                answer = await asyncio.to_thread(handler, inbound, transport)
            except Exception as exc:
                print(f"[discord] slash handler failed ({type(exc).__name__})", flush=True)
                answer = "The command failed; check the local bot log."
            if not answer:
                answer = "Done."
            for chunk in transport.split_message(transport.stamp(str(answer)), 1900):
                await interaction.followup.send(chunk)

        @tree.command(name="helpo", description="List every Ponytail command")
        async def slash_helpo(interaction: Any) -> None:
            await handle_slash(interaction, "/helpo")

        @tree.command(name="help", description="Alias for /helpo")
        async def slash_help(interaction: Any) -> None:
            await handle_slash(interaction, "/help")

        @tree.command(name="status", description="Show Ponytail mode, backend, and uptime")
        async def slash_status(interaction: Any) -> None:
            await handle_slash(interaction, "/status")

        @tree.command(name="models", description="List every available provider and model")
        async def slash_models(interaction: Any) -> None:
            await handle_slash(interaction, "/models")

        @tree.command(name="model", description="Switch Ponytail to a model from /models")
        @discord.app_commands.describe(model_id="Full model id shown by /models")
        async def slash_model(interaction: Any, model_id: str) -> None:
            await handle_slash(interaction, f"/model {model_id}")

        @tree.command(name="effort", description="Switch effort when this model family supports it")
        @discord.app_commands.describe(level="low, medium, high, or xhigh")
        async def slash_effort(interaction: Any, level: str) -> None:
            await handle_slash(interaction, f"/effort {level}")

        @tree.command(name="gain", description="Show the honest Ponytail benchmark card")
        async def slash_gain(interaction: Any) -> None:
            await handle_slash(interaction, "/gain")

        @tree.command(name="reset", description="Forget this room's conversation")
        async def slash_reset(interaction: Any) -> None:
            await handle_slash(interaction, "/reset")

        @tree.command(name="sleep", description="Pause Ponytail for a number of minutes")
        @discord.app_commands.describe(minutes="Minutes to sleep; zero pauses until /on")
        async def slash_sleep(interaction: Any, minutes: float = 0.0) -> None:
            await handle_slash(interaction, f"/sleep {minutes:g}")

        @tree.command(name="on", description="Resume Ponytail replies")
        async def slash_on(interaction: Any) -> None:
            await handle_slash(interaction, "/on")

        @tree.command(name="off", description="Pause Ponytail until /on")
        async def slash_off(interaction: Any) -> None:
            await handle_slash(interaction, "/off")

        @tree.command(name="kill", description="Stop the local Ponytail bot process")
        async def slash_kill(interaction: Any) -> None:
            await handle_slash(interaction, "/kill")

        async def watch_stop() -> None:
            while not stop():
                await asyncio.sleep(0.5)
            await client.close()

        @client.event
        async def on_ready() -> None:
            nonlocal synced
            transport.bot_id = str(client.user.id)
            transport.bot_username = str(client.user)
            print(f"[discord] connected as {transport.bot_username} ({transport.bot_id})", flush=True)
            if not synced:
                await tree.sync()
                for guild_id in sorted(transport.allowed_guild_ids):
                    guild = discord.Object(id=int(guild_id))
                    tree.copy_global_to(guild=guild)
                    await tree.sync(guild=guild)
                synced = True
                print("[discord] slash commands synced", flush=True)
            asyncio.create_task(watch_stop())

        @client.event
        async def on_message(message: Any) -> None:
            if not client.user:
                return
            # BOTS ARE IGNORED — EXCEPT ONES EXPLICITLY LISTED AS OWNERS.
            #
            # The blanket `message.author.bot` drop ran BEFORE the owner check, so
            # Disco (1524266643340005446) sat in owner_ids as dead config: declared
            # an owner, structurally unable to be heard, no log line to say why.
            # Proven live 2026-08-09 — an owner-bot mention produced no reply and
            # no journal entry at all.
            #
            # Never itself, which is what actually prevents a loop: a bot that
            # cannot hear its own voice cannot talk itself into one. Any other bot
            # still has to be on the owner allowlist, which is a deliberate act.
            if message.author.bot and str(message.author.id) not in transport.owner_ids:
                return
            if str(message.author.id) == transport.bot_id:
                return
            guild = getattr(message, "guild", None)
            is_dm = guild is None
            actor_id = str(message.author.id)
            channel_id = str(message.channel.id)
            guild_id = str(guild.id) if guild else ""
            is_owner = actor_id in transport.owner_ids
            if not transport.in_reach(
                is_dm=is_dm, is_owner=is_owner, guild_id=guild_id, channel_id=channel_id
            ):
                return
            mentioned = any(str(user.id) == transport.bot_id for user in message.mentions)
            reference = getattr(message, "reference", None)
            resolved = getattr(reference, "resolved", None) if reference else None
            reply_to_bot = bool(resolved) and str(getattr(getattr(resolved, "author", None), "id", "")) == transport.bot_id
            if reference and resolved is None and getattr(reference, "message_id", None):
                try:
                    resolved = await message.channel.fetch_message(reference.message_id)
                    reply_to_bot = str(resolved.author.id) == transport.bot_id
                except Exception:
                    reply_to_bot = True  # owner replied; silence is worse than one extra answer
            text = str(message.content or "")
            text = text.replace(f"<@{transport.bot_id}>", "").replace(f"<@!{transport.bot_id}>", "").strip()
            inbound = Inbound(
                channel="discord",
                room_id=channel_id,
                room_kind="private" if is_dm else "group",
                event_id=str(message.id),
                actor_id=actor_id,
                actor_name=str(getattr(message.author, "display_name", message.author.name)),
                actor_handle=str(message.author.name),
                actor_is_bot=False,
                text=text,
                addressed=transport.is_addressed(
                    is_dm=is_dm, is_owner=is_owner, mentioned=mentioned, reply_to_bot=reply_to_bot
                ),
                is_owner=is_owner,
                reply_to_text=str(getattr(resolved, "content", "") or "")[:1000] if resolved else "",
                server_id=guild_id,
                attachments=tuple({
                    "kind": str(item.content_type or "file").split("/")[0],
                    "name": item.filename,
                    "bytes": item.size,
                    "url": item.url,
                } for item in list(message.attachments)[:5]),
                sent_at=float(message.created_at.timestamp()),
            )
            # TYPING ONLY WHEN IT WILL ACTUALLY ANSWER.
            #
            # This wrapped EVERY handler call, including the ones that return
            # None immediately because the message was not addressed to it. So
            # aedrion appeared to be typing every time the owner spoke to someone
            # else in the room — 2026-08-09: "whenever I send message to aiko in
            # discord I see aedrion typing idk why". A typing indicator is a
            # promise of a reply; showing one it will not keep is a lie about
            # what the bot is doing.
            #
            # The handler is still CALLED either way: an Inbound is recorded
            # always and only triggers work if addressed, and that observation is
            # worth keeping.
            will_answer = bool(inbound.addressed) or inbound.text.strip().startswith(("/", "!"))
            try:
                if will_answer:
                    async with message.channel.typing():
                        answer = await asyncio.to_thread(handler, inbound, transport)
                else:
                    answer = await asyncio.to_thread(handler, inbound, transport)
            except Exception as exc:
                print(f"[discord] handler failed ({type(exc).__name__})", flush=True)
                answer = "The agent turn failed; check the local bot log."
            if answer:
                chunks = self.split_message(self.stamp(str(answer)), 1900)
                for index, chunk in enumerate(chunks):
                    if index == 0:
                        await message.reply(chunk, mention_author=False)
                    else:
                        await message.channel.send(chunk)

        client.run(self._token, log_handler=None)

    @staticmethod
    def split_message(text: str, budget: int) -> list[str]:
        pieces: list[str] = []
        remaining = text.strip() or "…"
        while remaining:
            if len(remaining) <= budget:
                pieces.append(remaining)
                break
            cut = remaining.rfind("\n", 0, budget + 1)
            if cut < budget // 2:
                cut = remaining.rfind(" ", 0, budget + 1)
            if cut < budget // 2:
                cut = budget
            pieces.append(remaining[:cut].rstrip())
            remaining = remaining[cut:].lstrip()
        return pieces
