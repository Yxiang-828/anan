"""AnAn — single-process demo server.

Runs the kernel on a DemoClock, serves the elderly PWA (/elder), the demo
console (/), an SSE event stream (/events), and the two injection interfaces
(time + scenario). RED LINE: injection endpoints touch the CLOCK and send
ordinary inputs; they never mutate agent state directly — the judges watch
the real agent live on a faster day.

Family channel: Telegram (TSUKUMO bot token, daughter = owner account) when
reachable; otherwise a console mirror card (storyboard §C fallback) so the
demo never dies with the network.
"""
from __future__ import annotations

import json
import os
import queue
import threading
import time as _time
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def load_env() -> None:
    """Local dev reads keys.env; in the cloud the file does not exist and
    every value arrives via real environment variables (Render dashboard)."""
    path = ROOT / "keys.env"
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"'))


load_env()

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse  # noqa: E402

from core.clock import DemoClock  # noqa: E402
from core.store import Store  # noqa: E402
from core.kernel import Kernel  # noqa: E402
from core import skills_anan  # noqa: E402

# ANAN_RUNTIME lets a dev instance run with its OWN state (port via PORT env) —
# claude's test probes must never pollute the live demo's trace again
RUNTIME = ROOT / os.environ.get("ANAN_RUNTIME", "runtime")
RUNTIME.mkdir(exist_ok=True)

clock = DemoClock()
store = Store(RUNTIME / "anan.db")

# CONFIG: config.json (live) ← config.default.json (committed, COMPLETE) ← builtin.
# The default file is the single source — local-vs-cloud config drift was a live
# defect class (the hosted map shipped with no `home` because additions were
# scripted into local config only, 2026-08-09).
_cfg_file = ROOT / "config.json"
_cfg_default = ROOT / "config.default.json"
if _cfg_file.is_file():
    CONFIG = json.loads(_cfg_file.read_text())
elif _cfg_default.is_file():
    CONFIG = json.loads(_cfg_default.read_text())
    _own = os.environ.get("OWNER_TELEGRAM_ID") or os.environ.get("TELEGRAM_OWNER_USER_ID", "")
    if _own and CONFIG.get("contact_tree") and not CONFIG["contact_tree"][0].get("telegram"):
        CONFIG["contact_tree"][0]["telegram"] = _own
    _cfg_file.write_text(json.dumps(CONFIG, ensure_ascii=False, indent=2))
else:
    CONFIG = {
        "agent_name": "安安",
        "hotline": "995",
        "profile": {"name": "陈婆婆", "address_as": "婆婆", "age": 78,
                    "conditions": ["高血压", "轻度健忘"]},
        "med": {"name": "降压药", "note": "饭后温水服用, 蓝色盒子", "arms_silence": True},
        "contact_tree": [
            {"name": "小芸", "relation": "女儿", "recipient_is": "妈妈",
             "telegram": os.environ.get("OWNER_TELEGRAM_ID") or os.environ.get("TELEGRAM_OWNER_USER_ID", "")},
            {"name": "阿强", "relation": "儿子", "recipient_is": "妈妈", "telegram": ""},
            {"name": "王阿姨", "relation": "邻居", "recipient_is": "邻居陈婆婆", "telegram": ""},
        ],
        # family-configured timings — data, not code
        "schedule": {"07:30": "greet_checkin", "08:00": "med_reminder",
                     "20:00": "med_reminder", "20:05": "family_bulletin",
                     "21:00": "care_insight"},
        "windows": {"ack_min": 60, "retry_min": 30,
                    "escalation_min": 10, "escalation_rearm_min": 30},
        "channels": ["app", "voice_call"],
        # permission envelope: autonomous / family-approval / never
        "envelope": {
            "autonomous": ["tts.speak", "notify.elder", "notify.family", "memory.write"],
            "approval": ["contact.neighbor", "config.change"],
            "never": ["call.995", "medical.advice", "finance.any"],
        },
        # shipped DEFAULTS (editable data, not agent hardcode): pack voices
        # used until a family voice clone exists, per-language only
        "voice": {"defaults": {"zh": "chinese/12_confident_woman_chinese",
                               "en": "english/15_soothing_woman"},
                  "speak": "both",  # zh | en | both — what cards read aloud
                  "asr_language": "zh", "asr_model": "base",
                  # hosted demo voice (owner doctrine: qwen = phone app,
                  # ElevenLabs = hosted demo). Sarah primary; alts listed.
                  "eleven": {"model": "eleven_multilingual_v2",
                             "en": "EXAVITQu4vr4xnSDxMaL",
                             "zh": "EXAVITQu4vr4xnSDxMaL",
                             "alts_en": {"matilda": "XrExE9yKIg1WjnnlVkGX",
                                         "bill": "pqHfZKP75CvOlQylNhV4",
                                         "bella": "hpp4J3VqNfWAUOO0d1Us"}}},
    }
    _cfg_file.write_text(json.dumps(CONFIG, ensure_ascii=False, indent=2))

from core import brain  # noqa: E402


def bounded_choice(junction: str, options: list, fsm_state: dict) -> str:
    """THINK at a junction: the model picks ONE option token. Anything else —
    timeout, chatter, an option not on the list — and the kernel's floor
    stands. The envelope is the options list itself."""
    text, _lane = brain.think(
        f"照护 agent 到达节点 '{junction}'。当前状态: {json.dumps(fsm_state, ensure_ascii=False)}\n"
        f"可选动作: {options}\n只回其中一个动作的原文, 不要任何其他字。",
        system="你是照护 agent 内核的决策器。只输出选项原文。")
    return text.strip().splitlines()[0].strip()


kernel = Kernel(clock, store, CONFIG, chooser=bounded_choice)
skills_anan.register_all(kernel)
kernel.crons_from_config()

# --- channels ---------------------------------------------------------------
subscribers: list[queue.Queue] = []
elder_feed: list[dict] = []


def _broadcast(payload: dict) -> None:
    for q in list(subscribers):
        try:
            q.put_nowait(payload)
        except queue.Full:
            pass


def elder_send(text: str, card: dict) -> dict:
    entry = {**card, "at": clock.now().strftime("%H:%M")}
    elder_feed.append(entry)
    del elder_feed[:-30]
    _broadcast({"kind": "elder_card", "card": entry})
    return {"ok": True, "surface": "elder_app"}


kernel.channel("elder", elder_send)

# Telegram family channel — real transport if token resolves, mirror otherwise.
_tg = None
_tg_error = ""
try:
    from adapter.telegram import TelegramTransport

    _token = "" if os.environ.get("ANAN_DISABLE_TG") else (
        os.environ.get("ANAN_BOT_TOKEN") or os.environ.get("ANAN_TG_TOKEN")
        or os.environ.get("TSUKUMO_TG_BOT_TOKEN", ""))
    _owner = os.environ.get("OWNER_TELEGRAM_ID") or os.environ.get("TELEGRAM_OWNER_USER_ID", "")
    _family_ids = {str(c.get("telegram", "")) for c in CONFIG.get("contact_tree", [])}
    _family_ids |= set(CONFIG.get("family_extra_ids", []))
    _family_ids |= {_owner} if _owner else set()
    _family_ids.discard("")
    if _token and _family_ids:
        _tg = TelegramTransport(token=_token, owner_ids=_family_ids,
                                allowed_chat_ids=set(), offset_path=RUNTIME / "tg-offset.json")
        _refused_replied: set = set()

        def _on_refused(ib) -> None:
            store.event(clock.now().strftime("%Y-%m-%d %H:%M:%S"), "telegram_refused",
                        "family_adapter",
                        {"actor_id": ib.actor_id, "name": ib.actor_name,
                         "handle": ib.actor_handle, "text": ib.text[:80]},
                        effect=f"UNKNOWN SENDER id={ib.actor_id} — reply sent with setup instructions")
            # onboarding: tell the stranger their own id ONCE, so "what's my
            # telegram id" never needs a third-party bot
            if ib.room_kind == "private" and ib.room_id not in _refused_replied:
                _refused_replied.add(ib.room_id)
                try:
                    _tg.send(ib.room_id,
                             f"您好, 我是安安, 但我还不认识您。\n"
                             f"您的 Telegram ID: `{ib.actor_id}`\n"
                             f"请家人把这个 ID 填进设置页 (/family), 我就能为您服务了。\n"
                             f"Hi, I'm AnAn — I don't know you yet. Your Telegram ID is "
                             f"`{ib.actor_id}`. Enter it on the family setup page and "
                             f"I'll be able to talk to you.")
                except Exception:
                    pass

        _tg.on_refused = _on_refused
        _tg.connect()
except Exception as exc:  # noqa: BLE001
    _tg, _tg_error = None, str(exc)


def family_send(text: str, opts: dict) -> dict:
    mirror = {"kind": "family_card", "text": text,
              "buttons": opts.get("buttons"), "at": clock.now().strftime("%H:%M")}
    if _tg is not None:
        try:
            # route by the addressed contact; contacts without their own chat
            # fall back to the primary (demo: every contact = owner's phone)
            target = opts.get("to") or CONFIG["contact_tree"][0]["telegram"]
            ids = _tg.send(target, text, buttons=opts.get("buttons"))
            _broadcast({**mirror, "delivered": "telegram"})
            return {"ok": True, "surface": "telegram", "message_ids": ids}
        except Exception as exc:  # noqa: BLE001
            _broadcast({**mirror, "delivered": f"mirror (telegram failed: {exc})"})
            return {"ok": True, "surface": "mirror", "error": str(exc)}
    _broadcast({**mirror, "delivered": "mirror"})
    return {"ok": True, "surface": "mirror", "note": _tg_error or "no telegram configured"}


kernel.channel("family", family_send)


_handled_escalations: set[str] = set()


def _tg_handler(inbound, transport) -> None:
    if inbound.kind == "callback" and inbound.text.startswith("anan:"):
        parts = inbound.text.split(":")          # anan:<action>:<esc_id>
        action = parts[1] if len(parts) > 1 else ""
        esc_id = parts[2] if len(parts) > 2 else "esc-0"
        if esc_id in _handled_escalations:       # idempotent: double-tap = once
            transport.answer_callback(inbound.detail.get("callback_id", ""), "已处理过 ✓")
            return None
        _handled_escalations.add(esc_id)
        transport.answer_callback(inbound.detail.get("callback_id", ""), "安安收到 ✓")
        tree = CONFIG.get("contact_tree", [{}])
        who = tree[kernel.loop.contact_idx % len(tree)].get("name", "家人")
        if action == "called":
            kernel.submit("family_callback", "telegram", {"who": who, "esc_id": esc_id})
        elif action == "neighbor":
            kernel.submit("family_callback", "telegram", {"who": "neighbor", "esc_id": esc_id})
        return None
    if inbound.kind == "message" and inbound.text.strip():
        # family texting AnAn gets a real answer: model-composed from facts
        store.event(clock.now().strftime("%Y-%m-%d %H:%M:%S"), "wake", "telegram",
                    {"event": "family_message", "from": inbound.actor_name,
                     "text": inbound.text[:80]})
        sender = next((c for c in CONFIG.get("contact_tree", [])
                       if str(c.get("telegram", "")) == inbound.actor_id), None)
        p = CONFIG.get("profile", {})
        meds = store.rows("SELECT med, status FROM med_log ORDER BY id DESC LIMIT 3")
        insight = store.rows("SELECT text FROM insights ORDER BY id DESC LIMIT 1")
        facts = {
            "发信人": {"称呼": (sender or {}).get("name", inbound.actor_name),
                       "关系": (sender or {}).get("relation", "家人")},
            "被照顾者": {"名字": p.get("name"), "当前状态": kernel.loop.state},
            "最近用药": [{"药": m, "状态": s} for m, s in meds],
            "最近观察": insight[0][0] if insight else "无",
            "TA问": inbound.text[:300],
        }
        try:
            reply, _lane = brain.think(
                "意图: 回复家人在 Telegram 上的消息, 按事实回答, 不知道就说不知道。\n"
                f"事实:\n{json.dumps(facts, ensure_ascii=False, indent=1)}\n"
                "形式: 先中文后英文各一两行, 两种语言不同行。",
                system=f"你是{CONFIG.get('agent_name', '安安')}, "
                       f"{p.get('name', '')}的照护伴侣 agent, 正在和TA的家人说话。"
                       "你没有身体; 你能做的是陪伴、提醒、观察和联系家人。")
            store.log("conversations", at=clock.now().strftime("%H:%M"),
                      role="family_chat", text=inbound.text[:120])
            return reply
        except brain.BrainError as exc:
            store.event(clock.now().strftime("%Y-%m-%d %H:%M:%S"), "error", "family_chat",
                        {"error": str(exc)[:100]})
            return None
    return None


if _tg is not None:
    threading.Thread(target=lambda: _tg.poll_forever(_tg_handler, stop=lambda: False),
                     daemon=True).start()

# every store event -> SSE (with a fresh snapshot so the FSM view never lags)
store.listen(lambda ev: _broadcast({"kind": "event", "event": ev, "state": kernel.snapshot()}))

kernel.start()

# CAPABILITY RECEIPT (owner law 2026-08-09: differences between hosted and
# local must be VISIBLE, never silently discovered by the user): every boot
# states what this instance has and lacks, in its own trace.
import shutil as _shutil0  # noqa: E402
CAPS = {
    "qwen_tts": _VOICE_GEN.is_file() if "_VOICE_GEN" in dir() else (ROOT / "skills" / "voice-gen" / "run.py").is_file(),
    "whisper_asr": bool(_shutil0.which("whisper")),
    "eleven_keys": sum(1 for n in ("DINOSAUR_ELEVEN_LABS_API_KEY", "MY_ELEVEN_LABS_API_KEY",
                                   "HOLO_ELEVEN_LABS_API_KEY") if os.environ.get(n)),
    "agy_brain": Path("/home/dinosaur/.local/bin/agy").is_file(),
    "nvidia_brain": bool(os.environ.get("NVIDIA_API_KEY")),
    "telegram": bool(_tg),
    "home_geofence": bool(CONFIG.get("home", {}).get("lat")),
    "voice_clone": bool(CONFIG.get("voice", {}).get("clone")),
}
store.event(kernel.clock.now().strftime("%Y-%m-%d %H:%M:%S"), "wake", "environment",
            CAPS, effect="capability receipt — what THIS instance has and lacks")


def _warm_praise_tts() -> None:
    """Pre-render the praise lines so the reward beat's voice is INSTANT —
    a celebration that arrives four seconds late is not a celebration."""
    import urllib.request as _rq
    for pair in CONFIG.get("voice", {}).get("praise", []):
        for lang, line in zip(("zh", "en"), pair):
            try:
                req = _rq.Request("http://127.0.0.1:" + os.environ.get("PORT", "8801") + "/tts",
                                  data=json.dumps({"text": line, "lang": lang}).encode(),
                                  headers={"Content-Type": "application/json"}, method="POST")
                _rq.urlopen(req, timeout=120).read()
            except Exception:
                pass


threading.Thread(target=lambda: (_time.sleep(6), _warm_praise_tts()), daemon=True).start()

app = FastAPI(title="AnAn 安安")


@app.get("/", response_class=HTMLResponse)
def console() -> str:
    return (ROOT / "web" / "console.html").read_text()


@app.get("/elder", response_class=HTMLResponse)
def elder() -> str:
    return (ROOT / "web" / "elder.html").read_text()


@app.get("/state")
def state() -> dict:
    return {**kernel.snapshot(), "elder_feed": elder_feed[-10:], "profile": CONFIG["profile"],
            "agent_name": CONFIG.get("agent_name", ""),
            "med": CONFIG.get("med", {}),
            "voice_speak": CONFIG.get("voice", {}).get("speak", "both"),
            "praise": CONFIG.get("voice", {}).get("praise", []),
            "home": CONFIG.get("home", {}),
            "last_location": store.get("last_location"),
            # elder surface needs names/relations only — chat ids stay server-side
            "contact_tree": [{"name": c.get("name", ""), "relation": c.get("relation", ""),
                              "phone": c.get("phone", "")}
                             for c in CONFIG.get("contact_tree", [])],
            "telegram": bool(_tg), "telegram_error": _tg_error}


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok", "fsm": kernel.loop.state, "uptime_h": kernel.snapshot()["uptime_h"],
            "capabilities": CAPS}


@app.get("/version")
def version() -> dict:
    import subprocess
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                             capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:
        sha = ""
    return {"version": sha or "dev", "agent": CONFIG.get("agent_name", "")}


import hashlib  # noqa: E402
import subprocess as _sp  # noqa: E402

TTS_DIR = RUNTIME / "tts"
TTS_DIR.mkdir(exist_ok=True)
_VOICE_GEN = ROOT / "skills" / "voice-gen" / "run.py"


# Three equal keys, no priority. Sticky rotation (owner 2026-08-09): use the
# current one until it FAILS, then rotate to whoever works and stay there.
_ELEVEN_KEY_NAMES = ["DINOSAUR_ELEVEN_LABS_API_KEY", "MY_ELEVEN_LABS_API_KEY",
                     "HOLO_ELEVEN_LABS_API_KEY"]
_eleven_sticky = {"idx": 0}


def _eleven_tts(text: str, lang: str, voice_override: str = "") -> str | None:
    """ElevenLabs lane — the HOSTED demo voice (owner's two-tier doctrine:
    qwen3-TTS is the phone app's voice, ElevenLabs voices the hosted demo)."""
    import urllib.request as _rq
    pool = [(n, os.environ.get(n, "")) for n in _ELEVEN_KEY_NAMES]
    pool = [(n, v) for n, v in pool if v]
    ev = CONFIG.get("voice", {}).get("eleven", {})
    voice_id = voice_override or ev.get(lang) or ev.get("en", "")
    if not pool or not voice_id:
        return None
    key = hashlib.sha1(f"11:{lang}:{voice_id}:{text}".encode()).hexdigest()[:16]
    out = TTS_DIR / f"{key}.mp3"
    if out.is_file():
        return f"/tts/{key}.mp3"
    body = json.dumps({"text": text[:600],
                       "model_id": ev.get("model", "eleven_multilingual_v2"),
                       "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}}).encode()
    start = _eleven_sticky["idx"] % len(pool)
    for hop in range(len(pool)):
        idx = (start + hop) % len(pool)
        name, api_key = pool[idx]
        req = _rq.Request(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
            data=body, headers={"xi-api-key": api_key, "Content-Type": "application/json"},
            method="POST")
        try:
            with _rq.urlopen(req, timeout=30) as resp:
                audio = resp.read(8 * 1024 * 1024)
            if len(audio) < 500:
                raise ValueError("empty audio")
            if idx != _eleven_sticky["idx"]:
                store.event(kernel.clock.now().strftime("%Y-%m-%d %H:%M:%S"), "wake", "tts-eleven",
                            {"event": "key_rotated", "to": name},
                            effect=f"sticky key -> {name}")
            _eleven_sticky["idx"] = idx
            out.write_bytes(audio)
            return f"/tts/{key}.mp3"
        except Exception as exc:  # noqa: BLE001
            store.event(kernel.clock.now().strftime("%Y-%m-%d %H:%M:%S"), "error", "tts-eleven",
                        {"key": name, "why": str(exc)[:100]},
                        effect="rotating to next key" if hop + 1 < len(pool) else "ALL keys failed")
    return None


@app.post("/tts")
async def tts(request: Request) -> dict:
    """Voice lanes, in doctrine order: qwen3-TTS (phone app / local GPU) →
    ElevenLabs (hosted demo) → null (client falls to browser voice/silence)."""
    body = await request.json()
    text = (body.get("text") or "").strip()
    lang = "zh" if body.get("lang", "zh") == "zh" else "en"
    if not text:
        return {"url": None}
    if not _VOICE_GEN.is_file():
        return {"url": _eleven_tts(text, lang), "lane": "elevenlabs"}
    voice = (CONFIG.get("voice", {}).get("clone", {}).get(lang)
             or CONFIG.get("voice", {}).get("defaults", {}).get(lang, ""))
    if not voice:
        return {"url": _eleven_tts(text, lang), "lane": "elevenlabs"}
    key = hashlib.sha1(f"{lang}:{voice}:{text}".encode()).hexdigest()[:16]
    out = TTS_DIR / f"{key}.wav"
    if not out.is_file():
        env = {**os.environ,
               "KEEL_INPUT_TEXT": text, "KEEL_INPUT_VOICE": voice,
               "KEEL_INPUT_LANG": "chinese" if lang == "zh" else "english",
               "KEEL_INPUT_VERIFY": "off", "KEEL_INPUT_OUT": str(out),
               "KEEL_JOB_DIR": str(TTS_DIR)}
        # cloned refs live outside the pack: pass their transcript explicitly
        # (ICL cloning conditions on the (clip, text) pair)
        sidecar = Path(voice).with_suffix(".txt") if voice.startswith("/") else None
        if sidecar and sidecar.is_file():
            env["KEEL_INPUT_REF_TEXT"] = sidecar.read_text().strip()
        try:
            r = _sp.run(["python3", str(_VOICE_GEN)], env=env, cwd=_VOICE_GEN.parent,
                        capture_output=True, text=True, timeout=90)
            if not out.is_file():
                store.event(kernel.clock.now().strftime("%Y-%m-%d %H:%M:%S"), "error", "tts",
                            {"why": (r.stdout or r.stderr)[-200:]})
                return {"url": _eleven_tts(text, lang), "lane": "elevenlabs-fallback"}
        except Exception as exc:  # noqa: BLE001
            return {"url": _eleven_tts(text, lang), "lane": "elevenlabs-fallback", "error": str(exc)[:100]}
    return {"url": f"/tts/{key}.wav", "lane": "qwen3-tts"}


@app.get("/tts/{name}")
def tts_file(name: str):
    from fastapi.responses import FileResponse
    path = TTS_DIR / name
    if not path.is_file() or "/" in name or ".." in name:
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(path, media_type="audio/mpeg" if name.endswith(".mp3") else "audio/wav")


ASR_DIR = RUNTIME / "asr"
ASR_DIR.mkdir(exist_ok=True)


def _eleven_asr(blob: bytes, content_type: str) -> dict:
    """Hosted ears: ElevenLabs scribe_v1, same sticky key pool as the voice.
    Verified on this project's own test clip: character-perfect Chinese."""
    import urllib.request as _rq
    import uuid as _uuid
    pool = [(n, os.environ.get(n, "")) for n in _ELEVEN_KEY_NAMES]
    pool = [(n, v) for n, v in pool if v]
    if not pool:
        return {"text": "", "error": "no ASR on this host"}
    boundary = f"anan-{_uuid.uuid4().hex}"
    ext = "webm" if "webm" in content_type else ("ogg" if "ogg" in content_type else "wav")
    parts = [
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"model_id\"\r\n\r\nscribe_v1\r\n".encode(),
        (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
         f"filename=\"talk.{ext}\"\r\nContent-Type: {content_type or 'audio/webm'}\r\n\r\n").encode(),
        blob, b"\r\n", f"--{boundary}--\r\n".encode(),
    ]
    body = b"".join(parts)
    start = _eleven_sticky["idx"] % len(pool)
    for hop in range(len(pool)):
        idx = (start + hop) % len(pool)
        name, api_key = pool[idx]
        req = _rq.Request("https://api.elevenlabs.io/v1/speech-to-text", data=body,
                          headers={"xi-api-key": api_key,
                                   "Content-Type": f"multipart/form-data; boundary={boundary}"},
                          method="POST")
        try:
            with _rq.urlopen(req, timeout=45) as resp:
                payload = json.load(resp)
            _eleven_sticky["idx"] = idx
            return {"text": (payload.get("text") or "").strip(), "lane": "eleven-scribe"}
        except Exception as exc:  # noqa: BLE001
            store.event(kernel.clock.now().strftime("%Y-%m-%d %H:%M:%S"), "error", "asr-eleven",
                        {"key": name, "why": str(exc)[:100]})
    return {"text": "", "error": "all ASR lanes failed"}


@app.post("/asr")
async def asr(request: Request) -> dict:
    """Hold-to-talk audio → local Whisper (aiko's contract) → ElevenLabs
    scribe (hosted) → honest error. Browser records webm/ogg."""
    import shutil as _shutil
    blob = await request.body()
    if not blob or len(blob) < 200:
        return {"text": "", "error": "empty audio"}
    whisper_bin = os.environ.get("AIKO_WHISPER_BIN") or _shutil.which("whisper")
    if not whisper_bin:
        return _eleven_asr(blob, request.headers.get("content-type", ""))
    stamp = hashlib.sha1(blob).hexdigest()[:12]
    src = ASR_DIR / f"{stamp}.webm"
    src.write_bytes(blob)
    lang = CONFIG.get("voice", {}).get("asr_language", "auto")
    model = CONFIG.get("voice", {}).get("asr_model", "base")
    lang_args = ["--language", lang] if lang != "auto" else []
    try:
        r = _sp.run([whisper_bin, str(src), "--model", model, "--output_format", "txt",
                     "--output_dir", str(ASR_DIR), *lang_args],
                    capture_output=True, text=True, timeout=120)
    except Exception as exc:  # noqa: BLE001
        return {"text": "", "error": str(exc)[:100]}
    txt = ASR_DIR / f"{stamp}.txt"
    if r.returncode != 0 or not txt.is_file():
        return {"text": "", "error": (r.stderr or "no transcript")[:120]}
    text = txt.read_text().strip()
    store.event(kernel.clock.now().strftime("%Y-%m-%d %H:%M:%S"), "wake", "asr",
                {"event": "voice_transcribed", "chars": len(text)}, effect=f"heard: {text[:60]}")
    return {"text": text}


CLONE_DIR = RUNTIME / "voices"
CLONE_DIR.mkdir(exist_ok=True)


@app.get("/family", response_class=HTMLResponse)
def family_page() -> str:
    return (ROOT / "web" / "family.html").read_text()


@app.get("/voice/scripts")
def voice_scripts() -> dict:
    return CONFIG.get("voice", {}).get("scripts", {})


@app.get("/config/contact")
def get_contact() -> dict:
    c = (CONFIG.get("contact_tree") or [{}])[0]
    return {"name": c.get("name", ""), "relation": c.get("relation", ""),
            "telegram": c.get("telegram", ""), "phone": c.get("phone", "")}


@app.post("/config/contact")
async def set_contact(request: Request) -> dict:
    """Family setup: the primary contact is DATA the family enters — never a
    developer's env archaeology. Hot-reloads the Telegram allowlist."""
    b = await request.json()
    tree = CONFIG.setdefault("contact_tree", [{}])
    if not tree:
        tree.append({})
    for k in ("name", "relation", "telegram", "phone"):
        if b.get(k) is not None:
            tree[0][k] = str(b[k]).strip()
    _cfg_file.write_text(json.dumps(CONFIG, ensure_ascii=False, indent=2))
    if _tg is not None and tree[0].get("telegram"):
        _tg.owner_ids.add(str(tree[0]["telegram"]))
    store.event(kernel.clock.now().strftime("%Y-%m-%d %H:%M:%S"), "receipt", "config",
                {"contact": {k: tree[0].get(k, "") for k in ("name", "relation")},
                 "telegram_set": bool(tree[0].get("telegram"))},
                effect="primary family contact updated + telegram allowlist hot-reloaded")
    return {"ok": True}


@app.get("/voice/options")
def voice_options() -> dict:
    """Auditionable test voices on THIS host. Local = qwen pack + any clone;
    hosted = the ElevenLabs roster. Sample lines included for prefill."""
    v = CONFIG.get("voice", {})
    out: dict = {"sample_lines": v.get("sample_lines", {}), "voices": [],
                 # capability honesty: cloning needs the local qwen GPU rig —
                 # the hosted page must SAY so, not show broken buttons
                 "can_clone": _VOICE_GEN.is_file()}
    if _VOICE_GEN.is_file():
        for lang, ref in (v.get("clone") or {}).items():
            out["voices"].append({"lane": "qwen", "id": ref, "lang": lang,
                                  "label": "您的声音 Your voice" if lang == "zh" else "Your voice (EN)"})
        out["voices"] += [
            {"lane": "qwen", "id": "chinese/12_confident_woman_chinese", "lang": "zh", "label": "默认·温暖女声 Warm F"},
            {"lane": "qwen", "id": "chinese/8_cute_chinese", "lang": "zh", "label": "活泼女声 Bright F"},
            {"lane": "qwen", "id": "chinese/13_confident_male_chinese", "lang": "zh", "label": "男声 Male"},
            {"lane": "qwen", "id": "english/15_soothing_woman", "lang": "en", "label": "Soothing F"},
            {"lane": "qwen", "id": "english/3_warm", "lang": "en", "label": "Warm"},
        ]
    ev = v.get("eleven", {})
    if any(os.environ.get(n) for n in _ELEVEN_KEY_NAMES) and ev:
        pairs = [("Sarah", ev.get("en", ""))] + [
            (n.capitalize(), i) for n, i in (ev.get("alts_en") or {}).items()]
        for label, vid in pairs:
            if vid:
                out["voices"].append({"lane": "eleven", "id": vid, "lang": "any",
                                      "label": f"{label} (demo)"})
    return out


@app.post("/voice/preview")
async def voice_preview(request: Request) -> dict:
    """Render an EXACT text line in a chosen test voice — the audition."""
    body = await request.json()
    text = (body.get("text") or "").strip()[:620]
    lang = "zh" if body.get("lang", "zh") == "zh" else "en"
    lane = body.get("lane", "")
    vid = body.get("id", "")
    if not text or not vid:
        return {"url": None, "error": "need text and a voice"}
    if lane == "eleven":
        return {"url": _eleven_tts(text, lang, voice_override=vid)}
    if lane == "qwen" and _VOICE_GEN.is_file():
        key = hashlib.sha1(f"pv:{lang}:{vid}:{text}".encode()).hexdigest()[:16]
        out = TTS_DIR / f"{key}.wav"
        if not out.is_file():
            env = {**os.environ, "KEEL_INPUT_TEXT": text, "KEEL_INPUT_VOICE": vid,
                   "KEEL_INPUT_LANG": "chinese" if lang == "zh" else "english",
                   "KEEL_INPUT_VERIFY": "off", "KEEL_INPUT_OUT": str(out),
                   "KEEL_JOB_DIR": str(TTS_DIR)}
            sidecar = Path(vid).with_suffix(".txt") if vid.startswith("/") else None
            if sidecar and sidecar.is_file():
                env["KEEL_INPUT_REF_TEXT"] = sidecar.read_text().strip()
            try:
                _sp.run(["python3", str(_VOICE_GEN)], env=env, cwd=_VOICE_GEN.parent,
                        capture_output=True, text=True, timeout=120)
            except Exception as exc:  # noqa: BLE001
                return {"url": None, "error": str(exc)[:80]}
        return {"url": f"/tts/{key}.wav" if out.is_file() else None}
    return {"url": None, "error": "voice lane unavailable on this host"}


@app.post("/voice/clone")
async def voice_clone(request: Request, lang: str = "zh") -> dict:
    """The daughter reads the fixed script ONCE, in ONE language. The pair
    (recording, known script) becomes the qwen reference for that language
    only — never used cross-language (owner law). Hot-reloads into config."""
    lang = "zh" if lang == "zh" else "en"
    script = CONFIG.get("voice", {}).get("scripts", {}).get(lang, "")
    blob = await request.body()
    if not script or not blob or len(blob) < 3000:
        return {"ok": False, "error": "no script or recording too short"}
    raw = CLONE_DIR / f"{lang}.webm"
    wav = CLONE_DIR / f"{lang}.wav"
    raw.write_bytes(blob)
    conv = _sp.run(["ffmpeg", "-y", "-i", str(raw), "-ar", "24000", "-ac", "1", str(wav)],
                   capture_output=True, text=True, timeout=60)
    if conv.returncode != 0 or not wav.is_file():
        return {"ok": False, "error": "audio conversion failed"}
    (CLONE_DIR / f"{lang}.txt").write_text(script)
    CONFIG.setdefault("voice", {}).setdefault("clone", {})[lang] = str(wav)
    _cfg_file.write_text(json.dumps(CONFIG, ensure_ascii=False, indent=2))
    store.event(kernel.clock.now().strftime("%Y-%m-%d %H:%M:%S"), "receipt", "voice_clone",
                {"lang": lang, "ref": str(wav), "bytes": len(blob)},
                effect=f"family voice becomes the {lang} voice — hot-reloaded")
    # instant proof: the agent's next words, in the family's voice
    sample_line = CONFIG.get("voice", {}).get("sample_lines", {}).get(
        lang, script)
    key = hashlib.sha1(f"clone:{lang}:{sample_line}".encode()).hexdigest()[:16]
    out = TTS_DIR / f"{key}.wav"
    env = {**os.environ, "KEEL_INPUT_TEXT": sample_line, "KEEL_INPUT_VOICE": str(wav),
           "KEEL_INPUT_REF_TEXT": script,
           "KEEL_INPUT_LANG": "chinese" if lang == "zh" else "english",
           "KEEL_INPUT_VERIFY": "off", "KEEL_INPUT_OUT": str(out),
           "KEEL_JOB_DIR": str(TTS_DIR)}
    try:
        _sp.run(["python3", str(_VOICE_GEN)], env=env, cwd=_VOICE_GEN.parent,
                capture_output=True, text=True, timeout=120)
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, "sample": f"/tts/{key}.wav" if out.is_file() else None}


@app.get("/mascot/{name}")
def mascot_asset(name: str):
    """Codex sprite contract: web/mascot/<state>-atlas.png, 4 frames, 256px
    cells. 404 until an atlas lands; the console falls back to emoji."""
    from fastapi.responses import FileResponse
    path = ROOT / "web" / "mascot" / name
    if not path.is_file() or "/" in name or ".." in name:
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(path)


@app.get("/manifest.json")
def manifest() -> JSONResponse:
    icon = ("data:image/svg+xml," +
            "%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E"
            "%3Crect width='100' height='100' rx='22' fill='%23faf6ef'/%3E"
            "%3Ctext x='50' y='66' font-size='48' text-anchor='middle'%3E%E5%AE%89%3C/text%3E%3C/svg%3E")
    return JSONResponse({
        "name": "安安 AnAn", "short_name": "安安", "start_url": "/elder",
        "display": "standalone", "background_color": "#faf6ef", "theme_color": "#faf6ef",
        "icons": [{"src": icon, "sizes": "any", "type": "image/svg+xml"}],
    })


@app.get("/events")
def events() -> StreamingResponse:
    q: queue.Queue = queue.Queue(maxsize=200)
    subscribers.append(q)
    q.put_nowait({"kind": "hello", "state": kernel.snapshot(),
                  "history": store.recent_events(60), "elder_feed": elder_feed[-10:]})

    def gen():
        try:
            while True:
                try:
                    item = q.get(timeout=15)
                    yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
                except queue.Empty:
                    yield ": keepalive\n\n"
        finally:
            subscribers.remove(q)

    return StreamingResponse(gen(), media_type="text/event-stream")


# --- injection interfaces (time + scenario ONLY) ----------------------------
@app.post("/inject/time")
async def inject_time(request: Request) -> dict:
    body = await request.json()
    if "skip_to" in body:
        hh, mm = int(body["skip_to"][0]), int(body["skip_to"][1])
        now = clock.skip_to(hh, mm)
    elif "advance" in body:
        now = clock.advance(float(body["advance"]))
    else:
        now = clock.reset()
    store.event(kernel.clock.now().strftime("%Y-%m-%d %H:%M:%S"), "inject", "console",
                {"time": body}, effect=f"clock -> {now.strftime('%H:%M')}")
    return {"now": now.strftime("%H:%M")}


@app.post("/inject/scenario")
async def inject_scenario(request: Request) -> dict:
    """Scenarios are TIME jumps + ordinary INPUTS — never state writes."""
    name = (await request.json()).get("name", "")
    win = CONFIG.get("windows", {})
    if name == "morning":
        clock.skip_to(7, 29)
        clock.advance(1.05)
    elif name == "silence_1":
        clock.advance(float(win.get("ack_min", 60)) + 1)
    elif name == "silence_2":
        clock.advance(float(win.get("retry_min", 30)) + 1)
    elif name == "escalation_timeout":
        clock.advance(float(win.get("escalation_min", 10)) + 1)
    elif name == "recover":
        kernel.submit("heartbeat", "elder_app", {"via": "scenario_tap"})
    elif name == "evening":
        clock.skip_to(19, 59)
        clock.advance(1.05)
    elif name == "insight":
        clock.skip_to(20, 59)
        clock.advance(1.05)
    elif name == "wander":
        # simulated sensor input: a position ~500m from home (scenario, not behavior)
        h = CONFIG.get("home", {})
        kernel.submit("location", "scenario",
                      {"lat": h.get("lat", 0) + 0.0045, "lng": h.get("lng", 0), "accuracy": 10})
    elif name == "come_home":
        h = CONFIG.get("home", {})
        kernel.submit("location", "scenario",
                      {"lat": h.get("lat", 0), "lng": h.get("lng", 0), "accuracy": 10})
    elif name == "health_demo":
        # fixture result (labeled demo): a LOW face-symmetry score exercising
        # the anomaly path without a camera — the FAST-droop relay on stage
        kernel.submit("health_score", "scenario",
                      {"kind": "face_symmetry", "score": 42,
                       "metrics": {"demo_fixture": True, "median": 42, "variance": 18}})
    store.event(kernel.clock.now().strftime("%Y-%m-%d %H:%M:%S"), "inject", "console",
                {"scenario": name}, effect="time/scenario injection only")
    return {"ok": True, "now": clock.now().strftime("%H:%M")}


# --- elder surface inputs (real inputs, also usable by the demo) ------------
@app.post("/elder/heartbeat")
async def elder_heartbeat(request: Request) -> dict:
    body = await request.json()
    kernel.submit("heartbeat", "elder_app", body)
    return {"ok": True}


@app.post("/elder/say")
async def elder_say(request: Request) -> dict:
    text = (await request.json()).get("text", "")
    kernel.submit("user_text", "elder_app", {"text": text})
    return {"ok": True}


@app.post("/health/score")
async def health_score(request: Request) -> dict:
    """CV runs entirely on the elder's device (Synapxe privacy property kept:
    frames never leave the phone). Only {kind, score, metrics} arrives, and
    the AGENT decides what to reflect and whether the guardian hears."""
    b = await request.json()
    kind = b.get("kind", "")
    if kind not in ("heart_rate", "face_symmetry", "fitness"):
        return {"ok": False, "error": "unknown kind"}
    kernel.submit("health_score", "elder_app",
                  {"kind": kind, "score": float(b.get("score", 0)),
                   "metrics": b.get("metrics", {})})
    return {"ok": True}


@app.get("/health-lab", response_class=HTMLResponse)
def health_lab() -> str:
    """Synapxe's finished CV pages, served near-verbatim (owner order: copy
    and open a separate page, don't rebuild weaker versions)."""
    return (ROOT / "web" / "health-lab" / "index.html").read_text()


@app.get("/health-lab/{name}")
def health_lab_asset(name: str):
    from fastapi.responses import FileResponse
    path = ROOT / "web" / "health-lab" / name
    if not path.is_file() or "/" in name or ".." in name:
        return JSONResponse({"error": "not found"}, status_code=404)
    media = "text/javascript" if name.endswith(".js") else "text/plain"
    return FileResponse(path, media_type=media)


@app.post("/api/score")
async def api_score(request: Request) -> dict:
    """The transplanted pages POST their original shape here — their UI now
    drives AnAn's full agent loop (reflect to elder, fanout to guardian)."""
    b = await request.json()
    gmap = {"heart_rate": "heart_rate", "face_symmetry_score": "face_symmetry",
            "mobility_score": "fitness"}
    kind = gmap.get(b.get("game_type", ""))
    if not kind:
        return {"status": "ignored"}
    kernel.submit("health_score", "health_lab",
                  {"kind": kind, "score": float(b.get("score", 0)),
                   "metrics": b.get("metrics", {})})
    return {"status": "ok"}


@app.post("/elder/location")
async def elder_location(request: Request) -> dict:
    """The elder phone streams position (browser geolocation, HTTPS only).
    The kernel owns the geofence judgement."""
    b = await request.json()
    if b.get("lat") is None or b.get("lng") is None:
        return {"ok": False}
    kernel.submit("location", "elder_app",
                  {"lat": float(b["lat"]), "lng": float(b["lng"]),
                   "accuracy": float(b.get("accuracy", 0))})
    return {"ok": True}


@app.post("/elder/sos")
async def elder_sos() -> dict:
    kernel.submit("heartbeat", "elder_app", {"via": "SOS"})
    family_send("🆘 妈妈按了 SOS 按钮! 请立刻回电。", {})
    return {"ok": True}


@app.post("/reset")
def reset() -> dict:
    """One-key demo reset: wipe events/logs, FSM to IDLE, clock to real time.
    Storyboard §6.4's 一键重置 — the next judge starts from a known state."""
    with store._lock:
        for table in ("events", "med_log", "mood_log", "conversations",
                      "insights", "escalation_log", "kv"):
            store._conn.execute(f"DELETE FROM {table}")
        store._conn.commit()
    kernel.loop.state = "IDLE"
    kernel.loop.deadline = None
    kernel.loop.channel_idx = 0
    kernel.loop.contact_idx = 0
    kernel.loop.extended = False
    clock.reset()
    kernel.reset_crons()
    elder_feed.clear()
    store.event(kernel.clock.now().strftime("%Y-%m-%d %H:%M:%S"), "inject", "console",
                {"reset": True}, effect="demo reset: state wiped, FSM IDLE, clock realtime")
    _broadcast({"kind": "reset"})
    return {"ok": True}


@app.post("/seed")
def seed() -> dict:
    """Seed 6 days of history so Day-7 bulletins visibly know more than Day-1."""
    day_data = [
        (1, "平稳", "第一天认识, 话不多。"),
        (2, "平稳", "喜欢聊天气和买菜。"),
        (3, "低落", "提到膝盖疼, 上楼费劲。"),
        (4, "平稳", "对粤剧话题反应积极, 聊了很久。"),
        (5, "低落", "又提到膝盖疼——本周第二次。"),
        (6, "平稳", "女儿打过电话后心情明显变好。"),
    ]
    for day, mood, insight in day_data:
        store.log("med_log", at=f"day{day}", med="降压药", status="taken")
        store.log("mood_log", at=f"day{day}", label=mood, note="")
        store.log("insights", at=f"day{day}", day=day, kind="daily", text=insight)
    store.put("day_no", 7)
    store.event(kernel.clock.now().strftime("%Y-%m-%d %H:%M:%S"), "inject", "seed",
                {"days": 6}, effect="6 days of history seeded; today is day 7")
    return {"ok": True, "day": 7}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8801")),
                log_level="warning")
