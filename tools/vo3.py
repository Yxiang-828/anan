#!/usr/bin/env python3
"""Narration sized to HIS footage: each line is written to fit the clip it sits
under, played whole and sped — the clip sets the length, not the voice."""
import os, subprocess, sys, pathlib, json
ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "media" / "vo3"; GEN = ROOT / "skills" / "voice-gen" / "run.py"
VOICE = "english/16_confident_male"
LINES = {
 # ~7s — his stomach clip @2x. The Telegram chime in his own audio is the proof.
 "h1": "She says her stomach hurts. Nobody typed anything, and no button was pressed — listen for her daughter's phone.",
 # ~13s — his wander clip @2x
 "h2": "Her family drew a circle around home. She crosses it, and the kernel wakes on its own: the guardian gets a live map link, and grandma gets one large button that walks her back. Coming home sends the all clear by itself.",
 # ~8s — his smile clip @2x
 "h3": "A smile symmetry screen — the same test paramedics use for facial droop. The camera never leaves her phone; only the score does.",
 # ~25s — his mobility clip @2.5x, three exercises, played whole
 "h4": "Sit and stand, shoulder abduction, standing march. Pose tracking counts every repetition on the device itself, and the whole battery is here uncut, just sped up. When it finishes, the score goes to the agent — and the agent decides whether this is worth telling her family about, or worth only a word of encouragement to her.",
 # ~14.5s — his heart clip @2x
 "h5": "Heart rate, read from the camera. Blood changes how a fingertip absorbs light, and the phone can see it. This is the transplanted hackathon code running unmodified inside her own app.",
 # ~23.5s — his reference-voice clip, ramped so his voice stays natural
 "h6": "This is the whole voice setup, uncut. He picks a language, reads one line aloud, and those few seconds become the reference. Nothing is uploaded — the clone is built on this machine and never crosses between languages. Listen to him, and then listen to what she hears.",
 # ~11s — after AnAn speaks in his voice
 "h7": "That is not an assistant voice. That is her family, saying the thing she needed to hear this morning. The feature is not text to speech. The feature is that she is not being spoken to by a machine.",
}
def gen(k, t):
    wav = OUT / f"{k}.wav"; (OUT / f"{k}.txt").write_text(t, encoding="utf-8")
    if wav.is_file(): print(f"SKIP {k}"); return True
    env = {**os.environ, "KEEL_INPUT_TEXT": t, "KEEL_INPUT_VOICE": VOICE,
           "KEEL_INPUT_LANG": "english", "KEEL_INPUT_VERIFY": "off",
           "KEEL_INPUT_OUT": str(wav), "KEEL_JOB_DIR": str(OUT)}
    r = subprocess.run(["python3", str(GEN)], env=env, cwd=GEN.parent,
                       capture_output=True, text=True, timeout=900)
    if not wav.is_file(): print(f"FAIL {k}: {(r.stdout or r.stderr)[-200:]}", file=sys.stderr); return False
    try: sec = json.loads(r.stdout.strip().splitlines()[-1])["seconds"]
    except Exception: sec = "?"
    print(f"OK   {k}  {sec}s"); return True
if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    sys.exit(0 if all(gen(k, LINES[k]) for k in (sys.argv[1:] or list(LINES))) else 1)
