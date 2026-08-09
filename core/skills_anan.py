"""AnAn's product skills — intent + facts to the model; never scripted lines.

Doctrine (owner): words belong to the MODEL, facts and actions belong to CODE.
- A skill assembles an intent name and a facts dict from config + store, and
  the brain composes the utterance. No sentence in this file is agent speech.
- Deterministic floor covers ACTIONS (escalation fires at deadline with or
  without an LLM), not language. When both model lanes are down, surfaces
  render facts as labeled data — degraded honestly, never puppeteered.
- The system prompt is owner-record facts + transport contract (bilingual,
  line budget). No tone adjectives; personality is emergent.
"""
from __future__ import annotations

import json

from core import brain
from core.kernel import Kernel, Skill


def _system(kernel: Kernel) -> str:
    p = kernel.config.get("profile", {})
    agent = kernel.config.get("agent_name", "安安")
    facts = [
        f"你是{agent}, 一个照护伴侣 agent。",
        f"你照顾的人: {p.get('name', '?')}, {p.get('age', '?')}岁, "
        f"称呼TA为{p.get('address_as', p.get('name', ''))}, "
        f"健康情况: {', '.join(p.get('conditions', [])) or '未知'}。",
        "你没有身体, 不能亲手做事; 你能做的是: 说话陪伴、提醒、联系家人。不要承诺物理动作。",
        "绝不口头承诺'我会转告/我会联系家人'——真正给家人发消息是另一个技能干的, 有回执为证。"
        "你只负责当下这句回应。",
        "输出契约: 先中文一到两行, 然后换行, 再英文一到两行。中文行里只有中文, "
        "英文行里只有英文, 两种语言绝不混在同一行。口语, 简短, 无列表符号无引号。",
    ]
    return "\n".join(facts)


def _say(kernel: Kernel, intent: str, facts: dict, contract: str = "") -> tuple[str | None, str]:
    """Model composes from intent+facts. Returns (text, lane); text=None means
    both lanes down — caller degrades to data rendering, never to a script."""
    prompt = f"意图: {intent}\n事实:\n{json.dumps(facts, ensure_ascii=False, indent=1)}"
    if contract:
        prompt += f"\n形式: {contract}"
    try:
        text, lane = brain.think(prompt, system=_system(kernel))
        return text.strip()[:500], lane
    except brain.BrainError as exc:
        return None, f"degraded (LLM down: {str(exc)[:80]})"


def _elder(kernel: Kernel, card: dict) -> dict:
    send = kernel.channels.get("elder")
    return send(card.get("text", ""), card) if send else {"ok": False, "error": "no elder channel"}


def _family(kernel: Kernel, text: str, opts: dict | None = None) -> dict:
    send = kernel.channels.get("family")
    return send(text, opts or {}) if send else {"ok": False, "error": "no family channel"}


def _fmt(pairs: list[tuple[str, str]]) -> str:
    """Degraded mode: labeled facts. Labels are UI chrome, values are stored
    data (much of it typed by the family themselves) — no synthetic voice."""
    return "\n".join(f"{label}: {value}" for label, value in pairs if value)


# --- greet_checkin ---------------------------------------------------------
def greet_checkin(kernel: Kernel, channel: str = "app") -> dict:
    at = kernel.clock.now()
    meds = kernel.store.rows("SELECT med, status FROM med_log ORDER BY id DESC LIMIT 3")
    insight = kernel.store.rows("SELECT text FROM insights ORDER BY id DESC LIMIT 1")
    facts = {
        "现在时间": at.strftime("%H:%M"),
        "昨日用药": [{"药": m, "状态": s} for m, s in meds] or "无记录",
        "今日用药": kernel.config.get("med", {}),
        "最近观察": insight[0][0] if insight else "无",
    }
    text, lane = _say(kernel, "晨间主动问候, 顺带昨晚情况和今天要记得的事", facts)
    if text is None:
        text = _fmt([("早安 Morning check-in", at.strftime("%H:%M")),
                     ("今日用药 Medication", kernel.config.get("med", {}).get("name", "")),
                     ("备注 Note", kernel.config.get("med", {}).get("note", ""))])
    receipt = _elder(kernel, {"type": "greeting", "text": text, "channel": channel, "speak": True})
    kernel.store.put("last_checkin", at.strftime("%H:%M"))
    kernel.loop.checkin_sent(channel)
    kernel.store.log("conversations", at=at.strftime("%H:%M"), role="anan", text=text)
    return {"text": text, "lane": lane, "channel": channel, "delivery": receipt,
            "effect": f"greeting delivered on {channel}, ack window armed"}


# --- companion_chat --------------------------------------------------------
def companion_chat(kernel: Kernel, text: str = "") -> dict:
    kernel.loop.heartbeat("chat")
    at = kernel.clock.now().strftime("%H:%M")
    kernel.store.log("conversations", at=at, role="elder", text=text)
    history = kernel.store.rows("SELECT role, text FROM conversations ORDER BY id DESC LIMIT 6")
    facts = {
        "最近对话": [{"谁": r, "说": t} for r, t in reversed(history)],
        "TA刚说": text,
    }
    reply, lane = _say(kernel, "陪伴对话, 回应TA刚说的话", facts)
    offline = reply is None
    if offline:
        reply = _fmt([("状态 Status", "安安暂时离线 AnAn briefly offline"),
                      ("已记录 Recorded", text[:60])])
    kernel.store.log("conversations", at=at, role="anan", text=reply)
    mood_words = kernel.config.get("mood_markers", ["疼", "累", "睡不着", "难受", "孤"])
    mood = "低落" if any(w in text for w in mood_words) else "平稳"
    kernel.store.log("mood_log", at=at, label=mood, note=text[:60])
    receipt = _elder(kernel, {"type": "chat", "text": reply, "speak": not offline})
    return {"reply": reply, "lane": lane, "mood": mood, "delivery": receipt,
            "effect": "conversation logged, mood tracked, heartbeat"}


# --- relay_family ----------------------------------------------------------
def relay_family(kernel: Kernel, text: str = "") -> dict:
    """The elder asked for family to be told something. ACTUALLY send it and
    confirm from the delivery receipt — never a spoken promise."""
    kernel.loop.heartbeat("relay_request")
    at = kernel.clock.now().strftime("%H:%M")
    kernel.store.log("conversations", at=at, role="elder", text=text)
    first = (kernel.config.get("contact_tree") or [{}])[0]
    p = kernel.config.get("profile", {})
    facts = {
        "收信人": {"称呼": first.get("name"), "关系": first.get("relation")},
        "被照顾者": p.get("name"),
        "TA的原话": text[:200],
        "时间": at,
    }
    msg, lane = _say(kernel,
                     f"转达: 你现在是在给{first.get('name', '家人')}({first.get('relation', '')})发消息, "
                     f"不是在跟被照顾者说话。以称呼{first.get('name', '')}开头, "
                     f"忠实转达被照顾者的话和时间", facts,
                     contract="两三行, 中英各有")
    if msg is None:
        msg = "📨 " + _fmt([("转达 Message from", p.get("name", "")),
                            ("原话 Their words", text[:120]), ("时间 At", at)])
    receipt = _family(kernel, msg, {"to": first.get("telegram", "")})
    sent = bool(receipt.get("ok")) and receipt.get("surface") != "mirror"
    mirror_only = receipt.get("surface") == "mirror"
    if sent or mirror_only:
        confirm_facts = {"已发送给": first.get("name"), "渠道": receipt.get("surface")}
        confirm, _l = _say(kernel, "告诉TA消息真的已经发出去了, 一句安心的话", confirm_facts)
        if confirm is None:
            confirm = f"✓ 已发给{first.get('name', '家人')} Sent to {first.get('relation', 'family')}"
    else:
        confirm = _fmt([("没发出去 Could not send", receipt.get("error", "?")),
                        ("会再试 Will retry", "是 yes")])
    kernel.store.log("conversations", at=at, role="anan", text=confirm)
    _elder(kernel, {"type": "chat", "text": confirm, "speak": True})
    return {"message": msg, "lane": lane, "delivery": receipt,
            "effect": (f"elder's words RELAYED to {first.get('name')} via {receipt.get('surface')}"
                       if (sent or mirror_only) else "relay FAILED — elder told honestly")}


# --- safe_range ------------------------------------------------------------
def safe_range(kernel: Kernel, lat: float = 0, lng: float = 0, dist_m: int = 0,
               returned: bool = False) -> dict:
    """Wander safety relay (dementia care): geofence breach → family gets the
    live position + map link; return → all-clear. Detection is kernel-owned
    and deterministic; this skill only communicates, with receipts."""
    at = kernel.clock.now().strftime("%H:%M")
    p = kernel.config.get("profile", {})
    home = kernel.config.get("home", {})
    first = (kernel.config.get("contact_tree") or [{}])[0]
    map_link = f"https://maps.google.com/?q={lat},{lng}"
    if returned:
        facts = {"收信人": first.get("name"), "被照顾者": p.get("name"),
                 "情况": f"已回到家 {home.get('radius_m')}米 安全范围内", "时间": at}
        text, lane = _say(kernel, "报平安: TA回到安全范围了, 告诉家人不用担心了", facts)
        if text is None:
            text = _fmt([("✅ 已回到安全范围 Back in safe range", p.get("name", "")),
                         ("时间 At", at)])
        receipt = _family(kernel, text, {"to": first.get("telegram", "")})
        return {"lane": lane, "delivery": receipt,
                "effect": "all-clear sent — back inside the safe radius"}
    facts = {"收信人": {"称呼": first.get("name"), "关系": first.get("relation")},
             "被照顾者": p.get("name"),
             "情况": {"离家距离": f"{dist_m}米", "安全半径": f"{home.get('radius_m')}米",
                      "时间": at, "健康备注": ", ".join(p.get("conditions", []))}}
    text, lane = _say(kernel,
                      f"走失预警: 你在给{first.get('name', '家人')}发消息 — TA离开了安全范围, "
                      f"请家人查看位置并联系TA", facts, contract="三行内, 中英各有, 语气急但不吓人")
    if text is None:
        text = "🧭 " + _fmt([("走失预警 Wander alert", p.get("name", "")),
                             ("距离 Distance", f"{dist_m}m (radius {home.get('radius_m')}m)"),
                             ("时间 At", at)])
    text += f"\n📍 {map_link}"
    buttons = [[{"text": "🧭 查看位置 View location", "url": map_link}],
               [{"text": "✅ 我去接TA On my way", "callback_data": "anan:called:wander"}]]
    receipt = _family(kernel, text, {"buttons": buttons, "to": first.get("telegram", "")})
    _elder(kernel, {"type": "chat", "speak": True,
                    "text": (f"{p.get('address_as', '')}, 走远了点呢, 要不要歇一歇? "
                             f"已经告诉{first.get('name', '家人')}了。\n"
                             f"You've wandered a little far — take a rest, "
                             f"{first.get('name', 'family')} knows where you are.")})
    kernel.store.log("escalation_log", at=at, step="wander_alert",
                     contact=first.get("name", ""), outcome="sent" if receipt.get("ok") else "failed")
    return {"dist_m": dist_m, "map": map_link, "lane": lane, "delivery": receipt,
            "effect": f"wander alert relayed to {first.get('name')} with live position"}


# --- health_scan -----------------------------------------------------------
_HEALTH_NAMES = {"heart_rate": ("心率", "Heart rate", "bpm"),
                 "face_symmetry": ("面部对称", "Face symmetry", "/100"),
                 "fitness": ("活动力", "Mobility", "reps")}


def health_scan(kernel: Kernel, kind: str = "", score: float = 0,
                alert: bool = False, metrics: dict | None = None) -> dict:
    """Camera health-check results: encourage the elder always; alert family
    ONLY on deterministic anomaly (low face symmetry = FAST droop screen;
    out-of-range heart rate). CV ran on-device; only the score exists here."""
    at = kernel.clock.now().strftime("%H:%M")
    p = kernel.config.get("profile", {})
    zh_name, en_name, unit = _HEALTH_NAMES.get(kind, (kind, kind, ""))
    facts = {"检查": zh_name, "结果": f"{score:g}{unit}", "时间": at,
             "TA": p.get("address_as", "")}
    text, lane = _say(kernel, "健康小检查做完了, 鼓励TA一句并报结果", facts)
    if text is None:
        text = _fmt([(f"{zh_name} {en_name}", f"{score:g}{unit}"), ("时间 At", at)])
    _elder(kernel, {"type": "chat", "text": text, "speak": True})
    delivery = {"ok": True, "surface": "elder_only"}
    if alert:
        first = (kernel.config.get("contact_tree") or [{}])[0]
        afacts = {"收信人": {"称呼": first.get("name"), "关系": first.get("relation")},
                  "被照顾者": p.get("name"),
                  "异常": {"检查": zh_name, "结果": f"{score:g}{unit}", "时间": at},
                  "建议": "面部不对称可能提示中风征兆(FAST), 请尽快联系确认" if kind == "face_symmetry"
                          else "心率超出正常范围, 请联系确认"}
        amsg, _l = _say(kernel,
                        f"健康异常通知: 你在给{first.get('name', '家人')}发消息, 如实告知检查异常并建议行动",
                        afacts, contract="三行内, 中英各有, 严肃但不制造恐慌")
        if amsg is None:
            amsg = "⚠️ " + _fmt([("健康异常 Health anomaly", f"{zh_name} {en_name}: {score:g}{unit}"),
                                 ("时间 At", at), ("请联系 Please call", p.get("name", ""))])
        delivery = _family(kernel, amsg, {"to": first.get("telegram", "")})
        kernel.store.log("escalation_log", at=at, step=f"health_alert:{kind}",
                         contact=first.get("name", ""),
                         outcome="sent" if delivery.get("ok") else "failed")
    return {"kind": kind, "score": score, "alert": alert, "lane": lane, "delivery": delivery,
            "effect": (f"{kind} anomaly relayed to family" if alert
                       else f"{kind} logged + elder encouraged (CV stayed on-device)")}


# --- med_reminder ----------------------------------------------------------
def med_reminder(kernel: Kernel) -> dict:
    at = kernel.clock.now()
    med = kernel.config.get("med", {})
    facts = {"现在时间": at.strftime("%H:%M"), "药": med}
    text, lane = _say(kernel, "用药提醒, 提到药名和服用方法", facts,
                      contract="一两行, 确认按钮由界面提供, 不用在话里要求回复")
    if text is None:
        text = _fmt([("用药提醒 Medication", med.get("name", "")),
                     ("时间 Time", at.strftime("%H:%M")),
                     ("备注 Note", med.get("note", ""))])
    receipt = _elder(kernel, {"type": "med", "text": text, "med": med.get("name", ""),
                              "speak": lane and not lane.startswith("degraded"),
                              "buttons": True})
    kernel.store.log("med_log", at=at.strftime("%H:%M"), med=med.get("name", ""), status="reminded")
    if med.get("arms_silence") and kernel.loop.state in ("IDLE", "ENGAGED"):
        # the all-day silence net: a med prompt is also a liveness expectation —
        # but it must never reset an already-armed silence episode's ladder
        kernel.loop.checkin_sent("app", kind="med_prompt")
    return {"text": text, "lane": lane, "delivery": receipt,
            "effect": "med card shown; confirmation doubles as liveness heartbeat"}


# --- escalate_tree ---------------------------------------------------------
def escalate_tree(kernel: Kernel, contact_idx: int = 0, esc_id: str = "") -> dict:
    at = kernel.clock.now().strftime("%H:%M")
    tree = kernel.config.get("contact_tree", [])
    if not tree:
        _elder(kernel, {"type": "escalate_fallback",
                        "text": _fmt([("紧急 Emergency", kernel.config.get("hotline", "1777"))])})
        return {"effect": "NO CONTACT TREE — hotline card shown", "ok": False}
    first = tree[contact_idx % len(tree)]
    p = kernel.config.get("profile", {})
    facts = {
        "收信人": {"称呼": first.get("name"), "关系": first.get("relation")},
        "被照顾者": {"名字": p.get("name"), "与收信人的关系": first.get("recipient_is", "家人")},
        "情况": {"最后问候时间": kernel.store.get("last_checkin", "?"),
                 "已尝试渠道": ["app", "voice_call"], "现在时间": at, "回应": "无"},
    }
    text, lane = _say(kernel, "紧急升级通知: 告知收信人情况并请求TA回电确认", facts,
                      contract="三四行内; 按钮由界面提供")
    if text is None:
        text = "⚠️ " + _fmt([
            ("警报 Alert", f"{p.get('name', '')} 无回应 no response"),
            ("自 Since", kernel.store.get("last_checkin", "?")),
            ("已试 Tried", "app, voice_call"),
            ("现在 Now", at)])
    buttons = [[{"text": "✅ 我已回电 Called back", "callback_data": f"anan:called:{esc_id}"},
                {"text": "🏠 联系邻居 Contact neighbour", "callback_data": f"anan:neighbor:{esc_id}"}]]
    receipt = _family(kernel, text, {"buttons": buttons, "to": first.get("telegram", "")})
    kernel.store.log("escalation_log", at=at, step=f"notify:{esc_id}",
                     contact=first.get("name", ""), outcome="sent" if receipt.get("ok") else "failed")
    if receipt.get("ok"):
        kernel.submit("escalation_delivered", "escalate_tree")
        effect = f"alert delivered to {first.get('name')} ({first.get('relation')}), awaiting callback"
    else:
        effect = f"delivery FAILED: {receipt.get('error', '?')} — hotline card fallback"
        _elder(kernel, {"type": "escalate_fallback",
                        "text": _fmt([("紧急 Emergency", kernel.config.get("hotline", "1777"))])})
    return {"contact": first, "lane": lane, "delivery": receipt, "effect": effect}


# --- family_bulletin -------------------------------------------------------
def family_bulletin(kernel: Kernel) -> dict:
    day = kernel.store.get("day_no", 1)
    meds = kernel.store.rows("SELECT med, status FROM med_log ORDER BY id DESC LIMIT 4")
    moods = kernel.store.rows("SELECT label FROM mood_log ORDER BY id DESC LIMIT 5")
    insights = kernel.store.rows(
        "SELECT text FROM insights WHERE day=? ORDER BY id DESC LIMIT 2", (day,))
    first = (kernel.config.get("contact_tree") or [{}])[0]
    health = kernel.store.rows(
        "SELECT kind, score FROM health_log ORDER BY id DESC LIMIT 4")
    facts = {
        "第几天": day,
        "收信人": {"称呼": first.get("name"), "关系": first.get("relation")},
        "用药记录": [{"药": m, "状态": s} for m, s in meds],
        "近期心情": [m for (m,) in moods],
        "今日观察": [t for (t,) in insights],
        "健康检查": [{"项目": k, "结果": s} for k, s in health] or "今日未做",
    }
    text, lane = _say(kernel, "每晚家庭播报: 向收信人报当天平安, 包含用药/心情/观察", facts,
                      contract="三行左右, 每个意思中英都有")
    if text is None:
        text = _fmt([(f"播报 Day {day}", ""),
                     ("用药 Meds", "; ".join(f"{m}:{s}" for m, s in meds) or "无记录"),
                     ("心情 Mood", moods[0][0] if moods else "无记录"),
                     ("观察 Noticed", "; ".join(t for (t,) in insights) or "无")])
    receipt = _family(kernel, text)
    return {"text": text, "lane": lane, "day": day, "delivery": receipt,
            "effect": "family bulletin delivered (daily heartbeat to the family)"}


# --- care_insight ----------------------------------------------------------
def care_insight(kernel: Kernel) -> dict:
    at = kernel.clock.now()
    day = kernel.store.get("day_no", 1)
    convs = kernel.store.rows("SELECT role, text FROM conversations ORDER BY id DESC LIMIT 12")
    facts = {
        "第几天": day,
        "今天的对话": [{"谁": r, "说": t} for r, t in reversed(convs)] or "无对话",
        "历史观察": [t for (t,) in kernel.store.rows(
            "SELECT text FROM insights ORDER BY id DESC LIMIT 3")],
    }
    text, lane = _say(kernel, "从今天的对话提炼一条对家人有用的照护观察 (健康线索/情绪趋势/兴趣)", facts,
                      contract="一句话, 中英双语")
    if text is None:
        return {"lane": lane, "effect": "insight skipped — model lanes down, nothing fabricated"}
    kernel.store.log("insights", at=at.strftime("%H:%M"), day=day, kind="daily", text=text)
    return {"insight": text, "lane": lane, "day": day,
            "effect": f"insight #{day} written — day {day} knows more than day 1"}


def register_all(kernel: Kernel) -> None:
    kernel.registry.add(Skill("greet_checkin", "主动晨间问候, 附昨日摘要", "无回应触发沉默检测", greet_checkin,
                              "schedule", effects=("notify.elder", "tts.speak")))
    kernel.registry.add(Skill("companion_chat", "陪伴对话, 内嵌情绪感知", "事件触发; 写入对话与心情日志", companion_chat,
                              "event", effects=("notify.elder", "tts.speak", "memory.write")))
    kernel.registry.add(Skill("relay_family", "把老人的话真实转达给家人", "老人请求时; 发送有回执, 不口头承诺", relay_family,
                              "event", effects=("notify.family", "notify.elder", "tts.speak")))
    kernel.registry.add(Skill("safe_range", "走失预警: 超出安全半径即通知家人", "地理围栏由内核判定(确定性); 附实时位置", safe_range,
                              "event", effects=("notify.family", "notify.elder", "tts.speak")))
    kernel.registry.add(Skill("health_scan", "镜头健康检查结果: 鼓励老人, 异常即告家人", "CV 全在设备端; 心率/面部对称/活动力; 阈值确定性", health_scan,
                              "event", effects=("notify.family", "notify.elder", "tts.speak", "memory.write")))
    kernel.registry.add(Skill("med_reminder", "用药提醒, 确认即心跳", "提示同时布下沉默网", med_reminder,
                              "schedule", effects=("notify.elder", "tts.speak")))
    kernel.registry.add(Skill("escalate_tree", "沿紧急联系人树通知家人", "SILENCE_2 触发; 回调闭环; 走树", escalate_tree,
                              "event", effects=("notify.family",)))
    kernel.registry.add(Skill("family_bulletin", "每晚向家人播报当日状态", "每日心跳", family_bulletin,
                              "schedule", effects=("notify.family",)))
    kernel.registry.add(Skill("care_insight", "从对话提炼照护观察", "时间维度学习证据", care_insight,
                              "schedule", effects=("memory.write",)))
