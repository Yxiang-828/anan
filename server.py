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

RUNTIME = ROOT / "runtime"
RUNTIME.mkdir(exist_ok=True)

clock = DemoClock()
store = Store(RUNTIME / "anan.db")

# DEMO SEED CONFIG — the only place the demo persona exists. In the product
# this whole block is what the family fills in remotely at onboarding
# (storyboard §6.2 screen 1). Swap it and AnAn cares for someone else.
_cfg_file = ROOT / "config.json"
if _cfg_file.is_file():
    CONFIG = json.loads(_cfg_file.read_text())
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
                               "en": "english/15_soothing_woman"}},
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
        _tg.on_refused = lambda ib: store.event(
            clock.now().strftime("%Y-%m-%d %H:%M:%S"), "telegram_refused", "family_adapter",
            {"actor_id": ib.actor_id, "name": ib.actor_name, "handle": ib.actor_handle,
             "text": ib.text[:80]},
            effect=f"UNKNOWN SENDER id={ib.actor_id} — add to config family_extra_ids to adopt")
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
            # elder surface needs names/relations only — chat ids stay server-side
            "contact_tree": [{"name": c.get("name", ""), "relation": c.get("relation", ""),
                              "phone": c.get("phone", "")}
                             for c in CONFIG.get("contact_tree", [])],
            "telegram": bool(_tg), "telegram_error": _tg_error}


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok", "fsm": kernel.loop.state, "uptime_h": kernel.snapshot()["uptime_h"]}


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


@app.post("/tts")
async def tts(request: Request) -> dict:
    """Server-side qwen3-TTS (local GPU, voice-gen skill). Renders the zh or en
    line with the per-language reference from config (family clone when it
    exists, pack default otherwise). Returns {url:null} when the rig is absent
    (cloud) — the client then stays SILENT rather than garbling."""
    body = await request.json()
    text = (body.get("text") or "").strip()
    lang = "zh" if body.get("lang", "zh") == "zh" else "en"
    if not text or not _VOICE_GEN.is_file():
        return {"url": None}
    voice = (CONFIG.get("voice", {}).get("clone", {}).get(lang)
             or CONFIG.get("voice", {}).get("defaults", {}).get(lang, ""))
    if not voice:
        return {"url": None}
    key = hashlib.sha1(f"{lang}:{voice}:{text}".encode()).hexdigest()[:16]
    out = TTS_DIR / f"{key}.wav"
    if not out.is_file():
        env = {**os.environ,
               "KEEL_INPUT_TEXT": text, "KEEL_INPUT_VOICE": voice,
               "KEEL_INPUT_LANG": "chinese" if lang == "zh" else "english",
               "KEEL_INPUT_VERIFY": "off", "KEEL_INPUT_OUT": str(out),
               "KEEL_JOB_DIR": str(TTS_DIR)}
        try:
            r = _sp.run(["python3", str(_VOICE_GEN)], env=env, cwd=_VOICE_GEN.parent,
                        capture_output=True, text=True, timeout=90)
            if not out.is_file():
                store.event(kernel.clock.now().strftime("%Y-%m-%d %H:%M:%S"), "error", "tts",
                            {"why": (r.stdout or r.stderr)[-200:]})
                return {"url": None}
        except Exception as exc:  # noqa: BLE001
            return {"url": None, "error": str(exc)[:100]}
    return {"url": f"/tts/{key}.wav"}


@app.get("/tts/{name}")
def tts_file(name: str):
    from fastapi.responses import FileResponse
    path = TTS_DIR / name
    if not path.is_file() or "/" in name or ".." in name:
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(path, media_type="audio/wav")


ASR_DIR = RUNTIME / "asr"
ASR_DIR.mkdir(exist_ok=True)


@app.post("/asr")
async def asr(request: Request) -> dict:
    """Hold-to-talk audio → Whisper (aiko's transcribe contract) → text.
    Browser records webm/ogg; whisper's own ffmpeg handles the container."""
    import shutil as _shutil
    blob = await request.body()
    if not blob or len(blob) < 200:
        return {"text": "", "error": "empty audio"}
    whisper_bin = os.environ.get("AIKO_WHISPER_BIN") or _shutil.which("whisper")
    if not whisper_bin:
        return {"text": "", "error": "no ASR on this host"}
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


@app.post("/elder/sos")
async def elder_sos() -> dict:
    kernel.submit("heartbeat", "elder_app", {"via": "SOS"})
    family_send("🆘 妈妈按了 SOS 按钮! 请立刻回电。", {})
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
