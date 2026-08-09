# 安安 AnAn — the agent that hears silence

**Team SyntaxError** · Yao Xiang · "Age Well" Social Good Challenge Singapore · AI Agent/Skills Track

> A chatbot's input domain is {text}. AnAn's is **{time, silence, state}**.
> An autonomous care companion for seniors living alone — it speaks first, watches the
> silence, walks the family contact tree, tracks wandering, screens health with the camera,
> and writes a receipt for every decision it makes.

## ▶ Live demo — one link

**https://anan-iax1.onrender.com**

Open it and follow the numbered acts on the left — each sets the scene, then you press play
and watch it happen for real: on 婆婆's phone (center, live), on the daughter's Telegram
(right), and in the agent's own decision log. Red line: the demo injects **time and ordinary
inputs only — never behavior**.

- `/elder` — the senior's app (installable PWA; on a phone: Add to Home Screen)
- `/family` — family setup: contacts, voice recording, audition, live map
- `/health-lab` — the camera health checks (heart rate · mobility · smile/FAST screen)

## What it is (60 seconds)

Every action runs one pipeline, each phase a stored receipt:

```
WAKE → THINK → REVALIDATE → GATE → ACT → RECEIPT → COMMIT
```

- **THINK**: at junctions the model chooses inside a bounded envelope (retry / escalate /
  wait once; chat vs relay) — the deterministic floor stands if it fails. Choice is logged
  `chosen vs floor`.
- **REVALIDATE**: a decision born from an old snapshot re-checks the world — a heartbeat
  that raced it cancels the escalation before any external action.
- **GATE**: a three-tier permission envelope (autonomous / family-approval / **never**:
  no emergency calls, no medical advice, no money).
- **Safety floors are code, not model**: silence windows, geofence math, health thresholds,
  idempotent escalation — take the LLM away and the safety net still fires.

**Nine skills** through that pipeline: `greet_checkin` · `companion_chat` · `relay_family` ·
`med_reminder` · `escalate_tree` (a contact tree that actually walks) · `family_bulletin` ·
`care_insight` (day 7 knows her better than day 1) · `safe_range` (dementia wander safety
with live map + take-me-home) · `health_scan` (on-device CV → reflect to elder, fan out to
guardian on anomaly).

Full inventory & design: **[ARCHITECTURE.md](ARCHITECTURE.md)**

## Capability matrix (stated, not discovered)

| | Local (GPU workstation) | Hosted (this Render link) |
|---|---|---|
| Brain | Gemini 3.6 Flash (CLI) → Nemotron fallback | Nemotron Ultra → Super |
| Voice out | qwen3-TTS + per-language family **voice cloning** | ElevenLabs (3-key sticky rotation) |
| Ears | Whisper (medium, zh) | ElevenLabs scribe |
| Camera CV | in the browser, both — frames never leave the device | same |
| Telegram | one poller per token — the hosted instance owns the bot | owns the bot |

Every instance prints a **capability receipt** at boot (`/healthz`) — differences are
declared, not discovered.

## Run locally

```
pip install -r requirements.txt && python server.py    # http://localhost:8801
```

Deploy: `Dockerfile` + `render.yaml` (free tier). Env: `NVIDIA_API_KEY`,
`ANAN_BOT_TOKEN`, `OWNER_TELEGRAM_ID`, `*_ELEVEN_LABS_API_KEY`.
Config ships complete in `config.default.json` — the demo persona (陈婆婆) is seed data;
swap it and AnAn cares for someone else.

## Lineage

Built on an in-house autonomy research program (receipts over narration, stale-decision
revalidation, practical liveness), a production agent's measured context laws, transplanted
map UI (MapLibre + OneMap, zero keys) and clinical CV pages (rPPG / pose / face-symmetry,
reused verbatim), a sprite mascot drawn by a second AI agent — which also adversarially
blocked and corrected this agent's renderer in review.

Submission naming: `AnAn-<Deliverable>-SyntaxError`.
