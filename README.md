# 安安 AnAn — the agent that hears silence

An autonomous care companion for seniors living alone. Chatbots take text;
AnAn's inputs are **time, silence, and state**. Built for the Tencent Cloud
"Age Well" Social Good Challenge Singapore (AI Agent/Skills track).

**Claim:** it watches over a senior all day and escalates to family — with
nobody touching it. Every decision passes WAKE → THINK → REVALIDATE → GATE →
ACT → RECEIPT → COMMIT, visible live on the demo console.

## Try it (90 seconds)
1. Open `/` (demo console) and `/elder` (the senior's phone app) side by side.
2. Console → **跳到 07:30**: AnAn greets, bilingual, spoken. Nobody typed anything.
3. **+61 min** then **+31 min**: watch SILENCE_1 → retry → SILENCE_2 → ESCALATED —
   the family's Telegram gets a real alert card with buttons.
4. Tap **✅ 我已回电**: the loop closes, ESCALATED → RESOLVED.
5. Red line: the console injects **time and scenarios only** — never behavior.

## Run
```
pip install -r requirements.txt && python server.py   # http://localhost:8801
```
Docker/Render: `Dockerfile` + `render.yaml` (free tier). Env: `NVIDIA_API_KEY`
(cloud model lane), `ANAN_BOT_TOKEN` + `OWNER_TELEGRAM_ID` (family Telegram).

## Known limits
Cloud runs the NVIDIA model lane (local dev uses a Gemini CLI) and browser-silent
voice (local uses qwen3-TTS voice cloning). Demo persona is seed config —
swap `config.json` and AnAn cares for someone else.
