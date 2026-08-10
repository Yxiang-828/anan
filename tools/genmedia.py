#!/usr/bin/env python3
"""Cinematic media generation for the story site.
Craft peeled from Open-Higgsfield-AI (Autom8AI): cinema prompt compiler
(promptUtils.js buildNanoBananaPrompt) + submit/poll queue contract (muapi.js).
Gateway: FAL queue API (same models, key we hold). Every run logs to
docs/story-assets/ledger.jsonl — probe results are assets.
"""
import json, os, sys, time, urllib.request, pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "story-assets"
KEY = None
for line in (ROOT/"keys.env").read_text().splitlines():
    if line.startswith("FAL_API_KEY="):
        KEY = line.split("=",1)[1].strip().strip('"'); break
assert KEY, "FAL_API_KEY missing"

# ---- peeled cinema formula (Open-Higgsfield promptUtils.js) ----
def cine(base, camera="full-frame digital cinema camera",
         lens="warm-toned cinema prime lens", mm=35, ap="f/4",
         persp="natural cinematic perspective",
         depth="balanced depth of field"):
    return ", ".join([base,
        f"shot on a {camera}",
        f"using a {lens} at {mm}mm ({persp})",
        f"aperture {ap}", depth,
        "cinematic lighting", "natural color science",
        "high dynamic range", "professional photography, ultra-detailed"])

def _req(url, data=None, method=None):
    r = urllib.request.Request(url, data=json.dumps(data).encode() if data else None,
        headers={"Authorization": f"Key {KEY}", "Content-Type": "application/json"},
        method=method or ("POST" if data else "GET"))
    with urllib.request.urlopen(r, timeout=120) as f:
        return json.loads(f.read())

def submit_poll(model, payload, timeout=900):
    sub = _req(f"https://queue.fal.run/{model}", payload)
    rid = sub["request_id"]
    status_url = sub.get("status_url") or f"https://queue.fal.run/{model}/requests/{rid}/status"
    resp_url = sub.get("response_url") or f"https://queue.fal.run/{model}/requests/{rid}"
    t0 = time.time()
    while time.time() - t0 < timeout:
        time.sleep(3)
        st = _req(status_url)
        if st.get("status") == "COMPLETED":
            return _req(resp_url)
        if st.get("status") in ("FAILED","ERROR"):
            raise RuntimeError(f"{model} failed: {st}")
    raise TimeoutError(model)

def fetch(url, dest):
    urllib.request.urlretrieve(url, dest)
    return dest

def ledger(entry):
    entry["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    with open(OUT/"ledger.jsonl","a") as f: f.write(json.dumps(entry, ensure_ascii=False)+"\n")

NVKEY = None
for line in (ROOT/"keys.env").read_text().splitlines():
    if line.startswith("NVIDIA_API_KEY="):
        NVKEY = line.split("=",1)[1].strip(); break

def gen_image(name, prompt, w=1344, h=768, steps=28):
    """NVIDIA genai flux.1-dev — FAL account locked (exhausted balance), same model."""
    import base64
    out = OUT/f"{name}.jpg"
    if out.exists():
        print(f"SKIP {name} (exists)"); return
    try:
        r = urllib.request.Request("https://ai.api.nvidia.com/v1/genai/black-forest-labs/flux.1-dev",
            data=json.dumps({"prompt": prompt, "mode":"base", "width":w, "height":h,
                             "steps":steps, "samples":1, "cfg_scale":3.5}).encode(),
            headers={"Authorization":f"Bearer {NVKEY}","Content-Type":"application/json","Accept":"application/json"})
        with urllib.request.urlopen(r, timeout=300) as f:
            d = json.loads(f.read())
        out.write_bytes(base64.b64decode(d["artifacts"][0]["base64"]))
        ledger({"kind":"t2i","model":"nvidia/flux.1-dev","name":name,"prompt":prompt,"ok":True,"file":out.name,"wh":[w,h]})
        print(f"OK {name}")
    except Exception as e:
        ledger({"kind":"t2i","model":"nvidia/flux.1-dev","name":name,"prompt":prompt,"ok":False,"error":str(e)[:300]})
        print(f"FAIL {name}: {e}", file=sys.stderr); raise

if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    SHOTS = {
      "hero_dawn": cine("Interior of a Singapore HDB flat at dawn, an elderly woman's empty rattan armchair beside the window, soft golden light through lace curtains, a cup of tea steaming on a small table, quiet stillness, nobody in the room",
            camera="grand format 70mm film camera", mm=35, ap="f/4"),
      "night_block": cine("A Singapore HDB apartment block at night seen from street level looking up, every window dark except one warm lit window, light rain, moody",
            mm=24, persp="wide-angle dynamic perspective", ap="f/11", depth="deep focus clarity, sharp foreground to background"),
      "phone_table": cine("An old mobile phone lying face down on a wooden kitchen table next to an untouched bowl of congee and chopsticks, morning light raking across, nobody present",
            lens="extreme macro lens", mm=50, persp="standard portrait perspective", ap="f/1.4", depth="shallow depth of field, creamy bokeh"),
      "grandma_phone": cine("An elderly Chinese woman with silver hair in a bright Singapore flat, smiling warmly at her phone which glows softly, over-shoulder view, houseplants behind her",
            mm=85, persp="classic portrait perspective", ap="f/1.4", depth="shallow depth of field, creamy bokeh"),
      "build_night": cine("A dark room at night with a developer workstation, three monitors glowing with green and amber terminal logs and code, mechanical keyboard, empty coffee cups, blue city light through blinds",
            mm=35, ap="f/4"),
      "wander_dusk": cine("Aerial drone view of a Singapore HDB housing estate at dusk, warm lit void decks and connecting walkways, a small green park in the center, blue hour sky",
            mm=14, persp="wide-angle perspective", ap="f/11", depth="deep focus clarity, sharp foreground to background"),
      "kopitiam": cine("Elderly people having morning kopi at a Singapore void deck kopitiam, marble tables, warm tungsten light mixing with daylight, lived-in and warm",
            camera="classic 16mm film camera", mm=35, ap="f/4"),
      "receipts_macro": cine("Extreme close-up of a thermal printer receipt curling out of a small machine, dense rows of tiny printed timestamps and codes on the paper, dark background",
            lens="extreme macro lens", mm=50, persp="", ap="f/1.4", depth="shallow depth of field, creamy bokeh"),
      "finale_sunrise": cine("Sunrise over Singapore HDB rooftops, warm hopeful golden light, a small flock of birds flying across the sky",
            mm=14, persp="wide-angle perspective", ap="f/11", depth="deep focus clarity"),
    }
    names = sys.argv[1:] or list(SHOTS)
    for n in names:
        gen_image(n, SHOTS[n])
