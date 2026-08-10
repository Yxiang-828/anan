# A day as 婆婆 — a judge's checklist

Fifteen minutes, in order, on the live demo. Each step says **what to do**, **what
you should see**, and **why it matters**. Tick as you go.

**Live demo:** https://anan-iax1.onrender.com
**Story:** https://yxiang-828.github.io/anan · **Source:** https://github.com/Yxiang-828/anan

> **Read this first — what the hosted demo cannot do.**
> The free Render instance has **no GPU**. So on *this* server:
> - ❌ **No qwen3-TTS voice cloning.** The "record your voice" setup is disabled and
>   says so on the page — it is not broken, it is declared. Cloning runs on a local
>   machine with a GPU. The demo video shows it working.
> - ❌ **No local Whisper.** Speech recognition falls back to a hosted service.
> - ✅ Everything else — the agent, the seven-phase receipts, escalation, Telegram,
>   the geofence, the camera health checks — runs identically.
>
> The boot log prints a **capability receipt** listing exactly what this instance
> can and cannot do. Differences are declared, never discovered.

---

## 0 · Before you start  (1 min)

- [ ] Open the demo link. The landing page loads: 安安 AnAn, the six link cards, a
      language switch.
- [ ] Pick **English** or **中文** — the whole page, landing *and* console, switches.
- [ ] Scroll down once. The live console appears and fills the screen.
- [ ] Press **⟲ Reset** in the header. This wipes state so you start at a known point.

*Why: the agent is already running before you touch it. Reset only rewinds it.*

---

## 1 · Meet her phone  (2 min)

- [ ] In the middle column is **the actual elder app**, running live in the page —
      not a screenshot. Interact with it directly.
- [ ] Tap through her five tabs: **今天 Today · 说话 Talk · 健康 Health · 记录 Log · 家人 Family**.
- [ ] Note there is **no text box anywhere**. She never types.

*Why: elders do not open apps. Everything she needs is two taps deep.*

---

## 2 · Talk to 安安  (2 min)

- [ ] Go to **说话 Talk**. The bird *is* the button — hold it and speak.
- [ ] Say something ordinary: *"I had porridge this morning."*
      → You should see her words transcribed, then a reply.
- [ ] Now say something for her family: *"Tell my daughter my stomach hurts."*
      → Watch the **planner line** in the right column. It should pick
      `relay_family`, not `companion_chat`.

*Why: nobody told it which tool to use. The model chose the skill from what she
said — that is the autonomous tool invocation, and it is logged either way.*

> 🎧 On this hosted server the reply may be silent or use the browser voice.
> Her real voice — her daughter's, cloned — needs the local GPU. See the video.

---

## 3 · Do a health check-up  (3 min)  · **use a phone for this**

- [ ] From **健康 Health**, start **😊 Smile** (facial-droop screen, the FAST test).
- [ ] Let it run the full timer. **You should then see a result screen**: the score,
      what it means in plain language with the normal range, and a
      **安安说 / ANAN SAYS** block that fills in with her own words a few seconds later.
- [ ] It counts down and returns you to the Health tab by itself.
- [ ] Repeat with **🪑 Mobility** (sit-and-stand, counts your reps) and
      **❤️ Heart** (heart rate from the camera).

*Why: the camera never leaves the device — only the score does. The score enters
the same seven-phase pipeline as everything else.*

- [ ] **Now try a bad result.** In the console's demo rail, fire a health anomaly.
      → A guardian alert should appear in the **Telegram mirror** (right column).
      A normal score gives her encouragement only and does **not** disturb family.

*Why: whether family is told is decided by deterministic thresholds in plain code,
never by the model's mood.*

> 📷 If a device has no camera the page says so and offers a phone link. That
> banner can be dismissed.

---

## 4 · Watch it act on its own  (5 min) · **the important part**

In the left rail, run the acts **in order, one at a time**. ⏳ **Wait for each act to
finish before clicking the next** — the agent is really thinking (a live model
call), so a step can take 10–25 seconds. Clicking ahead makes you watch the
previous step land.

- [ ] **Act 1 · 07:30 — it speaks first.** A bilingual greeting appears on her phone
      and is spoken. A 60-minute reply window arms silently.
- [ ] **Act 2 · +61 min — silence becomes data.** No reply. State moves to `SILENCE_1`.
- [ ] **Act 3 · +31 min — the escalation promise.** Channels exhausted → `SILENCE_2`.
- [ ] **Act 4 · the tree actually walks.** No callback → the next contact is tried.
      Each hop is its own receipt.
- [ ] **Act 5 · a single touch — the 反悔 beat.** ⭐ Watch the decision log for
      `revalidate … STALE — candidate cancelled`. A decision was made and then
      *unmade* because she touched her screen while it was in flight.
- [ ] **Act 6 · 20:00 — the evening bulletin** to family.
- [ ] **Act 7 · 21:00 — it learns her.** `🧬 memory +=` on the planner line.
- [ ] **Act 8 · she wanders.** The geofence fires; family gets a live map link.
- [ ] **Act 9 · she comes home.** The all-clear sends itself.

*Why act 5 matters most: an agent that can cancel its own decision before acting is
the difference between autonomy and a scheduler.*

---

## 5 · Check our homework  (2 min)

- [ ] Open the **decision log** (right column). Every action has seven rows:
      `WAKE → THINK → REVALIDATE → GATE → ACT → RECEIPT → COMMIT`.
- [ ] Find one `gate` row. The permission envelope is visible: some effects are
      autonomous, some need family approval, and `call.995`, `medical.advice`,
      `finance.any` are **refused outright**.
- [ ] Find one `think` row at a junction. It shows the **options offered**, the
      **deterministic floor**, and **what the model chose** — so you can see where
      the model had freedom and where it did not.
- [ ] Watch the **bird** in the header while acts run. It sleeps when dormant, tilts
      while thinking, and flies when escalating — the kernel state, made visible.

*Why: every claim on the site is a row in that log. Nothing here asks to be
believed.*

---

## Known limits, stated up front

| | |
|---|---|
| No GPU on the demo server | voice cloning + local Whisper are disabled and declared |
| Free tier sleeps | the first load after idle can take ~50s to wake |
| Acts are live model calls | each takes 10–25s; run them one at a time |
| Telegram | messages go to the real bot; the mirror pane shows the same card |
| Fictional data | the elder profile and any seeded history are labelled as demo data |

## If something looks wrong

The console's log is the source of truth — an empty pane means the agent genuinely
did nothing, and a receipt means it genuinely did. Press **⟲ Reset** to return to a
known state and re-run the act.
