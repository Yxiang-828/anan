#!/usr/bin/env python3
"""Traced captions — open-source, aligned to the actual audio, never hand-typed.

faster-whisper transcribes each narration line with word timestamps. Because the
exact spoken text is known (media/vo2/<key>.txt), the transcript is used only for
TIMING; the words that get burned in are the words we actually fed the voice, so
a mis-hearing can never put a wrong word on screen.

Emits one .srt per line (times relative to that line) — the assembler offsets them
into the final timeline.
"""
import json, os, pathlib, sys, re

ROOT = pathlib.Path(__file__).resolve().parent.parent
VO = ROOT / "media" / (os.environ.get("VO_DIR") or "vo2")


def srt_time(t: float) -> str:
    h, rem = divmod(max(0.0, t), 3600)
    m, s = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{int((s - int(s)) * 1000):03d}"


def words_of(wav: pathlib.Path, model):
    segs, _ = model.transcribe(str(wav), word_timestamps=True, language="en",
                               vad_filter=False, beam_size=1)
    out = []
    for seg in segs:
        for w in (seg.words or []):
            out.append((w.word.strip(), float(w.start), float(w.end)))
    return out


def chunk(words, script: str, max_chars=42):
    """Group timed words into short caption cues. Words come from the TRANSCRIPT
    for timing; we re-flow the SCRIPT's own text over them so on-screen wording is
    exactly what was written and spoken."""
    # normalise both sides to compare shapes
    script_words = re.findall(r"\S+", script)
    n = min(len(words), len(script_words))
    if n == 0:
        return []
    pairs = [(script_words[i], words[i][1], words[i][2]) for i in range(n)]
    # any trailing script words (whisper dropped some) ride the last timing
    for j in range(n, len(script_words)):
        pairs.append((script_words[j], words[n - 1][1], words[n - 1][2]))

    cues, cur, start = [], [], None
    for w, s, e in pairs:
        if start is None:
            start = s
        cand = " ".join(cur + [w])
        if len(cand) > max_chars and cur:
            cues.append((start, prev_end, " ".join(cur)))
            cur, start = [w], s
        else:
            cur.append(w)
        prev_end = e
    if cur:
        cues.append((start, prev_end, " ".join(cur)))
    return cues


def main(keys):
    from faster_whisper import WhisperModel
    model = WhisperModel("base.en", device="cpu", compute_type="int8")
    index = {}
    for k in keys:
        wav, txt = VO / f"{k}.wav", VO / f"{k}.txt"
        if not wav.is_file():
            print(f"skip {k} (no audio)", file=sys.stderr)
            continue
        cues = chunk(words_of(wav, model), txt.read_text(encoding="utf-8"))
        lines = []
        for i, (s, e, text) in enumerate(cues, 1):
            lines += [str(i), f"{srt_time(s)} --> {srt_time(e)}", text, ""]
        (VO / f"{k}.srt").write_text("\n".join(lines), encoding="utf-8")
        index[k] = [[round(s, 3), round(e, 3), t] for s, e, t in cues]
        print(f"{k}: {len(cues)} cues")
    (VO / "cues.json").write_text(json.dumps(index, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    ks = sys.argv[1:] or [p.stem for p in sorted(VO.glob("v*.wav"),
                                                 key=lambda p: int(re.sub(r"\D", "", p.stem) or 0))]
    main(ks)
