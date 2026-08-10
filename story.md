# 安安 AnAn · story.md — FINAL build-story (video + deck spine) · claude × kimi merge
# Runtime ~4:45 · narration EN read-aloud ready (安安台词保留中文) · facts follow ARCHITECTURE.md

## Act 0 · Cold open (0:00–0:15)
**VO**: "Most agents wait to be asked. Ours doesn't. We built AnAn — an autonomous companion
for seniors living alone — on one thesis: **silence is an input**. A chatbot's input domain
is text. AnAn's is time, silence, and state."
**Screen**: black → thesis slams on → cut to the LIVE console, uptime ticking. `[CLIP C0]`

## Act 1 · Origin: an autonomy program, not a chat window (0:15–0:45)
**VO**: "We didn't start from a chat window. We started from an autonomy research program —
eighteen artifacts on what makes an agent more than an LLM plus a scheduler. Its core law:
**WAKE is not THINK is not ACT.** A trigger only creates the opportunity to inspect;
cognition is a separate decision; action is another. Every action runs a seven-phase
pipeline — wake, think, revalidate, gate, act, receipt, commit — and every phase writes a
receipt."
**Screen**: ARCHITECTURE §1 diagram → seven-phase log scrolling. `[CLIP C1]`

## Act 2 · Skeleton: the Hero-Loop FSM (0:45–1:15)
**VO**: "The skeleton is a state machine built for one question: what happens when she
doesn't answer? Morning greeting — no reply — retry on another channel — still nothing —
escalate down a contact tree that *actually walks*: daughter, son, neighbour, each hop with
its own receipt. And the moment she touches anything, the silence net dissolves. **Every
touch is a heartbeat.**"
**Screen**: FSM strip walking IDLE→CHECKIN_SENT→SILENCE_1→SILENCE_2→ESCALATED live. `[CLIP C2]`

## Act 3 · Exploration: 93 words (1:15–1:40)
**VO**: "Before building, we mapped the whole problem space — ninety-three needs scattered
unbiased across three poles: the autonomous agent, the elderly, their needs. Position is
semantic affinity; colour is the blend. We converged with a weighted matrix — impact,
autonomy visibility, feasibility, drama — and picked the loop you just saw."
**Screen**: polygon Ken-Burns → circle animates around the 主动陪伴 cluster. `[CLIP C3]`

## Act 4 · Soul: the mascot statesheet ★ (1:40–2:10)
**VO**: "An autonomous system you can't see is a system you can't trust. So the kernel got a
face — AnAn the bird: ten pixel states, one per kernel state. Dormant sleeps; thinking
tilts; escalation *flies out of the grandmother's phone toward the daughter's*. Every
receipt, the bird acts out. The sprite pack was drawn by a second AI agent — which then
adversarially **blocked our renderer** with a reproduced defect report. Multi-agent build,
with review gates. Not decoration."
**Screen**: full statesheet (10 states) → bird-sprites mp4 → live reward-beat in the app. `[CLIP C4 + bird mp4]`

## Act 5 · Flesh: nine skills, one law (2:10–2:40)
**VO**: "Nine skills, all through the same pipeline, all gated by a permission envelope —
autonomous, family-approval, and never: no emergency calls, no medical advice, no money.
The registry carries name plus one-line capability — a measured law: ninety-seven percent
correct selection at eight percent of the token cost. Skills assemble facts; the model
writes every word. And composition is never load-bearing for safety: **take the LLM away,
and the safety net still fires.**"
**Screen**: skill rack chips glowing one by one; planner line above. `[CLIP C5]`

## Act 6 · Voice: cloning presence, not audio (2:40–3:05)
**VO**: "Her family records ten seconds — one language at a time. The clone never crosses
languages; it hot-reloads; the audition proves it instantly. 她听到的不是 AI, 是女儿。"
**Screen**: /family record (waveform) → 生效了 → sample plays ALOUD → elder card speaks. `[CLIP Y1 — needs your mic]`

## Act 7 · One day, live (3:05–4:00) — causality across real devices
- **7a Morning (10s)**: Act ① → the phone pops the bilingual greeting and SPEAKS. VO: "7:30.
  She's slow to rise. AnAn speaks first — and starts a sixty-minute listening window." `[CLIP C6]`
- **7b Silence → the daughter's real phone (14s)**: Acts ②③ → junction receipt closeup
  (`chosen=… (model)`) → **your real phone lights with the Telegram alert card**. VO: "No
  answer. The agent weighs its options and chooses. Still nothing — and across the city, a
  real phone, real Telegram, zero human input on the agent." `[CLIP C7 + Y2 phone film]`
- **7c Wander (14s)**: Act ⑧ → elder map turns red + 带我回家 button → real-phone wander card
  with 📍 live position. VO: "For dementia, silence isn't the only input. Cross the family-set
  radius: family gets her position; she gets one blue button that walks her home." `[CLIP C8 + Y3]`
- **7d The camera clinic (17s)**: splice YOUR vids — smile (~5s) → mobility (~5s) →
  heart_rate_tracker (~4s) → AnAn's reflection card + anomaly ping on Telegram. VO: "Heart
  rate, mobility, a facial-droop screen — frames never leave her device; only the score
  reaches the agent. A droop pattern reaches family in seconds. FAST, automated." `[Y4 vids + C9]`

## Act 8 · Evidence: the decision that didn't happen (4:00–4:20)
**VO**: "Our favourite moment is a decision that *doesn't* happen. The agent decides to
escalate — then revalidation finds a heartbeat that raced it, and kills it: **STALE —
candidate cancelled, no external action.** And each night it distills one observation into
memory — day seven knows her better than day one. Judges don't watch claims; they watch
receipts."
**Screen**: revalidate STALE closeup → planline `🧬 memory += …`. `[CLIP C10]`

## Act 9 · Lineage: how it was built (4:20–4:40)
**VO**: "How was it built? An autonomy research program donated the organs. A production
agent donated measured laws. Two hackathons donated organs whole — maps from one, three
clinical CV pages from another. WorkBuddy planned and generated the project; a second agent
drew the mascot and reviewed the code adversarially. One human, a fleet of agents, review
gates between them."
**Screen**: lineage diagram + repo commit wall scroll. `[CLIP C11]`

## Act 10 · Close (4:40–4:55)
**VO**: "Eighty-eight thousand four hundred seniors in Singapore live alone. AnAn is live
tonight, at this link. AnAn — an AgeWell companion. **Silence is an input.**"
**Screen**: real phone opens onrender URL → bird idle → 安安 AnAn · Team SyntaxError ·
anan-iax1.onrender.com. One soft ding. `[Y5 phone film + C12 endcard]`

## Cut priority (if time runs short, cut from the bottom)
Must: C0 C2 C4 C5 C7+Y2 C10 Y5 · Next: Y1(voice) C8 · Static-replaceable: C1 C3 C11

## Deck page order (cut directly from ARCHITECTURE §9)
P1 cover(A0) · P2 three numbers · P3 passive-tools-fail insight · P4 autonomy origin(A1) ·
P5 FSM(A2) · P6 polygon(A3) · P7 mascot+multi-agent(A4) · P8 skills+registry(A5) ·
P9 voice(A6) · P10 five surfaces(A7) · P11 receipts+反悔+envelope(A8) · P12 lineage(A9) ·
P13 impact+close(A10)

Live demo: https://anan-iax1.onrender.com · Story: https://yxiang-828.github.io/anan · Source: https://github.com/Yxiang-828/anan
