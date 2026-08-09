# 安安 AnAn — Full Architecture & Feature Inventory
**Team SyntaxError** · Yao Xiang (solo) · "Age Well" Social Good Challenge Singapore · AI Agent/Skills Track
Live: https://anan-iax1.onrender.com · Repo: github.com/Yxiang-828/anan
Thesis: **"Silence is an input."** A chatbot's input domain is {text}. AnAn's is **{time, silence, state}**.

Everything below exists and ran tonight; every mechanism listed writes receipts that can be replayed from the event store.

---

## 1. System shape

```
                    FAMILY (Telegram / family page)          ELDER (PWA on her phone)
                          ▲            ▲                        ▲           ▲
                   alerts │ bulletins  │ chat replies    cards, │ voice     │ map, health
                          │            │                        │           │
   ┌──────────────────────┴────────────┴────────────────────────┴───────────┴──────────────┐
   │                                  CHANNEL LAYER                                        │
   │   elder (SSE) · family (Telegram transport, mirror fallback) · voice (TTS/ASR lanes)  │
   └──────────────────────────────────────────┬────────────────────────────────────────────┘
                                              │ receipts only
   ┌──────────────────────────────────────────┴────────────────────────────────────────────┐
   │                                    THE KERNEL                                          │
   │  injectable clock → scheduler → DURABLE EVENT INBOX → decision pipeline → skills       │
   │        WAKE → THINK → REVALIDATE → GATE → ACT → RECEIPT → COMMIT                       │
   │  Hero-Loop FSM · bounded model choice · permission envelope · liveness watchdog        │
   └──────────────────────────────────────────┬────────────────────────────────────────────┘
                                              │
   ┌──────────────────────────────────────────┴────────────────────────────────────────────┐
   │   STATE (SQLite): events(receipts) · med/mood/conversations/insights ·                 │
   │   escalations · health · kv(prospective/wander/location)                               │
   └───────────────────────────────────────────────────────────────────────────────────────┘
```

One process (FastAPI + SSE + background threads). The world is concurrent (crons, Telegram callbacks,
elder touches, GPS, CV scores); **cognition and state commit are serialized** through one inbox and
one loop — concurrent world, serialized mind.

---

## 2. The autonomous kernel — organ by organ

Grounded in an in-house autonomy research program (WAKE≠THINK≠ACT; receipts over narration;
practical liveness; stale-decision revalidation) and a production agent's measured context laws.

### 2.1 Injectable clock
`WallClock` in production, `DemoClock` in demos: wall-cadence plus a thread-safe offset with
`skip_to(hh,mm)` / `advance(min)`. Every kernel decision reads this clock and only this clock.
**The demo red line is a mechanism, not a promise**: the console can inject *time and ordinary
inputs* — there is no endpoint that can inject behavior.

### 2.2 Durable event inbox
Everything arrives as an event: `cron_due`, `junction`, `heartbeat`, `user_text`,
`family_callback`, `escalation_delivered`, `location`, `health_score`, `settle`.
Producers are many threads; one loop consumes. Nothing is dropped because the mind is busy.
Each event carries its creation wall-time — the raw material for revalidation.

### 2.3 Scheduler (five rules, each bought by a recorded failure)
- config-owned cron table (`schedule` in config.json — family data, not code);
- **boot guard**: after a restart, crons >10 min overdue roll forward with a single summary
  receipt — never replayed at the user;
- mid-timeskip catch-up: crons crossed by a jump fire honestly, in order;
- daily-fire bookkeeping per cron;
- ticks also evaluate FSM deadlines and the liveness watchdog.

### 2.4 Hero-Loop FSM (silence is an input)
States: `IDLE → CHECKIN_SENT → {ENGAGED | SILENCE_1 → CHECKIN_SENT(retry) | SILENCE_2 →
ESCALATED → RESOLVED} → IDLE`. All windows config-owned (ack 60′, retry 30′, escalation 10′,
re-arm 30′). Design laws implemented:
- **Every touch is a heartbeat** — med confirmation, speech, any tap dissolves the silence net;
  a med prompt also *arms* it (the all-day net), but never resets an active episode's ladder.
- The elder's own touch resolves even ESCALATED (her liveness outranks everything).
- **The contact tree actually walks**: no family callback within the window → next contact
  (daughter → son → neighbour), each hop a fresh idempotent `esc_id`; an exhausted tree re-arms
  from the top with a longer window — an escalation never sits without a firing route.

### 2.5 Decision pipeline — every action, seven receipts
`WAKE → THINK → REVALIDATE → GATE → ACT → RECEIPT → COMMIT`, each phase one row in the event
store, live-streamed to the console. "The judges don't watch claims; they watch receipts."

- **THINK — bounded model choice.** At a junction the model picks from an options envelope
  (`retry:voice_call | escalate_now | extend_once`); anything outside the envelope, a timeout,
  or a dead provider → the deterministic floor stands. `chosen` vs `floor` vs `how` is logged.
  On elder speech the planner routes between skills (`companion_chat` vs `relay_family`) the
  same way — autonomous tool selection with a deterministic fallback.
- **REVALIDATE — stale candidates die.** A silence-born decision is checked against evidence
  newer than its creation: a heartbeat that raced it cancels the candidate before any external
  action (`verdict: STALE — candidate cancelled, no external action`). Observed live.
- **GATE — the permission envelope.** Three tiers from config: `autonomous`
  (tts.speak, notify.elder, notify.family, memory.write) · `approval` (a family Telegram
  button IS the approval) · `never` (call.995, medical.advice, finance.any). Enforced at
  execution time on each skill's declared effects; a never-effect refuses loudly.
- **RECEIPT — effect scope.** Receipts record what actually changed ("alert delivered to 小芸
  via telegram, awaiting callback"), never just a return status.

### 2.6 Practical-liveness watchdog
Counts **firing routes, not states**: an armed deadline in the tick path, a queued inbox
event, a cron with a next fire. A non-terminal FSM state with no route, sustained across two
checks, emits `LIVENESS_GAP` — visible, not buried. (Lesson: a route is something that
actually fires; a detector must not share its mechanism's blind spot.)

### 2.7 Deterministic safety floors
Model composition is never load-bearing for safety: geofence breach detection (haversine vs
config radius), health-anomaly thresholds (face-symmetry < 60; BPM outside 45–120), silence
escalation timing, and idempotent callback handling are all plain code. **Take the LLM away
and the safety net still fires — with template-degraded language that renders facts as facts,
never fake warmth.**

### 2.8 Environment honesty
Boot emits a **capability receipt** (qwen? whisper? eleven keys? telegram? geofence? clone?)
into the trace and `/healthz` — a hosted instance and a local one *declare* their differences.
One-key `/reset` returns any instance to a known state. `ANAN_RUNTIME` isolates dev state so
test probes never pollute a live demo's trace.

---

## 3. Skills — 9 registered, all through the same pipeline

Registry law (measured on a production agent: names + one-line capability = 97% correct
selection at 8% of the token cost of full schemas): the catalogue carries `name + capability`;
full contracts live with the skill. Startup self-test: everything advertised must dispatch.
Unknown-skill errors teach (nearest real names), never bare-refuse.

| # | Skill | Trigger | Effects (gated) | What actually happens |
|---|---|---|---|---|
| 1 | `greet_checkin` | cron 07:30 + silence retries | notify.elder, tts.speak | Bilingual morning greeting composed from yesterday's med/mood records + latest insight; delivery arms the ack window |
| 2 | `companion_chat` | elder speech (routed) | notify.elder, tts.speak, memory.write | Model reply from conversation facts; mood tracked; every exchange is a liveness heartbeat |
| 3 | `relay_family` | elder speech (routed) | notify.family, notify.elder, tts.speak | The elder's words FAITHFULLY delivered to family; the elder's confirmation is generated from the delivery receipt — spoken promises are banned by the persona contract |
| 4 | `med_reminder` | cron 08:00/20:00 | notify.elder, tts.speak | Med card whose [我吃了] is simultaneously a liveness signal; confirmation triggers the reward beat (particles, happy mascot, spoken praise); arms the all-day silence net |
| 5 | `escalate_tree` | SILENCE_2 / walk timeouts | notify.family | Telegram alert card with idempotent inline buttons ([我已回电] closes the loop); per-hop receipts as the tree walks |
| 6 | `family_bulletin` | cron 20:05 | notify.family | Nightly bilingual report composed from the day's actual records: meds, mood, insight, health checks |
| 7 | `care_insight` | cron 21:00 | memory.write | Distills ONE care observation from today's conversations into memory — day N visibly knows more than day 1; feeds tomorrow's greeting and the next bulletin |
| 8 | `safe_range` | kernel geofence events | notify.family, notify.elder, tts.speak | Wander alert with live position + map link + [On my way] button; elder gets a gentle spoken nudge; return inside the radius → automatic all-clear |
| 9 | `health_scan` | CV score events | notify.family, notify.elder, tts.speak, memory.write | Reflects every camera-check result to the elder encouragingly; on deterministic anomaly (face droop = FAST screen, out-of-range BPM) fans out to the guardian immediately |

**Composition doctrine**: skills assemble *intents and facts*; the model writes every word
(system prompt = owner-record facts + output contract — no tone scripting, no canned lines);
degraded mode renders labeled data. Demo fixtures and shipped defaults are config data, never
agent hardcode.

---

## 4. Model & voice stack

### 4.1 Brain — three rungs, stateless, receipted
`Gemini 3.6 Flash (local CLI) → Nemotron-3 Ultra 550B (NVIDIA API) → Nemotron-3 Super 120B`.
Every call is one-shot: continuity lives in the state store, never in a provider session.
A reasoning model that spends its whole budget thinking returns an empty answer — that is
classified a *failure*, not a reply. The winning lane is recorded in every receipt.

### 4.2 Voice out — two-tier doctrine
- **Phone app (local): qwen3-TTS** on GPU. **Voice cloning**: a family member picks a language
  FIRST, reads a fixed ~10s script; the (recording, known-script) pair becomes that language's
  reference — never used cross-language; hot-reloads; instant sample playback proves the clone.
  Pack voices as shipped defaults. Content-hash cache; praise lines pre-warmed at boot.
- **Hosted demo: ElevenLabs** (Sarah primary EN+中 via multilingual v2; Matilda/Bill/Bella
  alternates) with a **3-key pool, sticky rotation on failure** — no priority, stay on whoever
  works, every rotation receipted.
- Fallback ladder ends honestly: browser English voice; **silence beats garbled Chinese**.
- A voice **audition**: any exact line played in any available voice, including your own clone.

### 4.3 Ears
- Local: **Whisper** (medium, zh prior) — the same invocation contract as the production agent.
- Hosted: **ElevenLabs scribe** with the same key rotation — verified character-perfect on
  Chinese test audio. Errors are honest ("no ASR on this host" never fakes a transcript).

---

## 5. Surfaces

### 5.1 Elder PWA (`/elder`) — reduction design
Five tabs, two primary touch actions (hold-the-bird to talk, SOS). Installable (manifest),
bilingual everywhere (语音 reads zh/en/both per config), pixel-art mascot with 10 sprite states
mapped to real kernel states. No input box, no chat history, no badges. The **transparency
log** re-renders kernel receipts as plain speech ("8:00 提醒您吃药, 您说吃过了 ✓") — trust by
visibility. Med reward beat: particle burst + happy mascot + spoken praise (reduced-motion safe).
**Wander map**: home + dashed safe radius + live self-dot; outside the ring → red warning and a
one-tap "带我回家" walking-directions button.

### 5.2 Health Lab (`/health-lab`) — transplanted, not rebuilt
Three complete CV pages transplanted **near-verbatim** (one import line changed) from a prior
clinical-screening build: rPPG fingertip **heart rate** (torch + red-channel bandpass + peak
counting), **mobility** (MediaPipe pose, per-exercise rep FSMs, skeleton overlay), **smile
symmetry** (face mesh, mouth-drop asymmetry — a FAST facial-droop screen). All CV runs
**on-device; frames never leave the browser** — only `{kind, score, metrics}` posts to the
agent, which reflects, logs, and fans out. Shell adds: stage telemetry chips
(react/page/mediapipe/camera/detect flip ✓/✗ live), loud error banner, device-aware
suggestion toasts ("heart rate needs a phone's flash"), camera-fallback + busy-retry shims,
and an explicit insecure-origin banner (browser law: no camera on plain HTTP) with a tappable
HTTPS link. Voice prompts speak through AnAn's own TTS lanes.

### 5.3 Family page (`/family`)
Contact setup (name/relation/Telegram ID/phone → hot-reloads the bot allowlist);
voice recording with live waveform, silent-mic warning, staged progress, explicit
done/error states; voice audition; **live map** of the elder with home + radius.
Unknown Telegram senders get onboarding automatically: the bot replies with *their own ID*
and where to enter it.

### 5.4 Demo console (`/`) — theatre with receipts
Story-first: an intro card sets 陈婆婆's day; **9 acts** (morning → silence → escalation →
tree walk → the 反悔 touch → bulletin → insight → wander → come-home), each opening with a
scene line, the design rationale, what-to-watch, and its skill chips. Product front and
center: the elder phone runs LIVE in a bezel (with delegated camera/mic permissions).
Right side: the daughter's Telegram, styled as Telegram (bubbles, inline keyboards, bot
header), and the internals panel — **planner line, live skill rack (chips glow per
invocation with counters), FSM strip, seven-phase decision log**. Full EN/中 toggle.
Independent column scrolling. One-key reset. Seeds labeled as fixtures.

### 5.5 Telegram (an adapter, not the product)
Alerts with idempotent inline buttons, nightly bulletins, wander cards with map links,
health-anomaly notices — and real conversation: family texting the bot gets model-composed
answers grounded in the elder's actual day.

---

## 6. State & learning
SQLite, WAL, single writer. `events` is the receipt ledger (at/wall/kind/source/detail/effect);
typed logs for med, mood, conversations, insights, escalations, health; kv for prospective
state (last_checkin, wander_flag, last_location, day counter). `care_insight` is the time
dimension made visible: Day-1 vs Day-7 bulletins differ because memory grew.

## 7. Deployment
Render free tier (Dockerfile, `render.yaml`, Singapore region, `/healthz`), GitHub-Actions
keepalive every 10 min that **fails loudly**. `config.default.json` is the committed single
source of configuration — the local-vs-cloud drift class is dead. One Telegram poller per
token (cloud owns the bot; local runs `ANAN_DISABLE_TG=1`). Secrets only in env.

## 8. Lineage (the AI-tools story is also the build story)
- **Autonomy research program** (18 artifacts): the kernel organs and their epistemics.
- **A production agent's measured laws**: the skill-menu context law, scheduler failure rules,
  transport contract, prompt-cache ordering.
- **Clean transports** transplanted from a sibling agent (Telegram/Discord).
- **KampungKaki** (hackathon): MapLibre + OneMap map mechanism, zero keys.
- **Synapxe challenge**: the three CV screening pages, verbatim.
- **A second AI agent (codex)** drew the 10-state mascot sprite pack — and adversarially
  **blocked** this agent's sprite renderer with a reproduced defect report; the fix followed
  its review. Multi-agent build with review gates, not decoration.

## 9. Rubric mapping (for the deck, not prose for judges)
- **Use of AI Tools (40)** — §2.5 bounded choice + skill routing + revalidation + gate;
  §3 nine receipted skills; §4 three-rung model strategy; the console makes all of it visible live.
- **Impact & Relevance (30)** — proactive silence net for the 88,400 seniors living alone;
  wander safety for dementia; FAST droop screen; guardian burden relief (evidence base doc).
- **Project Quality (30)** — live hosted system + installable PWA + real Telegram loop +
  voice cloning + on-device CV; receipts for every claim.

## Team
**SyntaxError** — Yao Xiang (solo). Submission naming: `AnAn-<Deliverable>-SyntaxError`.
