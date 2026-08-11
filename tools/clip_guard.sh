#!/bin/bash
# Emit the edit plan the build ACTUALLY performs on owner footage, then run
# codex's edit_guard against each clip contract.
#
# Why this exists: the build windows every long capture with -ss/-t and then
# speeds it, because segment lengths are locked to the narration audio. On
# mobility.mp4 that discarded 73% of the clip — two of three exercises and the
# completion card — while the owner's standing order was "speed up, don't cut".
# Nothing in the build noticed. This makes the trade visible and blocking.
set -uo pipefail
cd /home/dinosaur/Project/anan
A=/home/dinosaur/aiko/arsenal/skills/_media-arsenal
[ -f media/seg2/editplan.jsonl ] || { echo "  clip guard: no edit plan recorded"; exit 0; }

python3 - "$A" <<'PYEOF'
import json, pathlib, subprocess, sys, collections
A = sys.argv[1]
CONTRACTS = {"mobility.mp4": "media/contracts/mobility.json",
             "smile.mp4": "media/contracts/smile.json",
             "heart_rate_tracker.mp4": "media/contracts/heart_rate.json"}
rows = [json.loads(l) for l in
        pathlib.Path("media/seg2/editplan.jsonl").read_text().splitlines() if l.strip()]
by_src = collections.defaultdict(list)
for r in rows:
    by_src[pathlib.Path(r["src"]).name].append(r)

failed = []
for name, contract in CONTRACTS.items():
    segs = by_src.get(name)
    if not (segs and pathlib.Path(contract).is_file()):
        continue
    cj = json.loads(pathlib.Path(contract).read_text())
    plan = {"schema_version": 1, "project": "anan-demo-video", "approval_refs": [],
            "segments": [{
                "id": s["key"], "source_asset_id": cj["source"]["asset_id"],
                "source_start_s": s["ss"], "source_end_s": s["ss"] + s["len"],
                "timeline_start_s": 0.0, "timeline_end_s": s["slot"],
                "track": "video-main", "z_index": 0, "role": "primary",
                "opacity": 1.0, "blend_mode": "normal", "rate": s["rate"],
                "pitch_preserved": False, "crop": "fill", "anchors_preserved": False,
                "source_audio": s.get("audio", "drop"), "replacement": False,
                "overlays": [], "overlay_targets": [], "storyboard_beat": s["key"],
            } for s in segs]}
    out = pathlib.Path(f"media/seg2/guard-{name}.plan.json")
    out.write_text(json.dumps(plan, indent=1))
    r = subprocess.run(["python3", f"{A}/tools/edit_guard.py", contract, str(out),
                        "--output", f"media/seg2/guard-{name}.json"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        try:
            v = json.loads(pathlib.Path(f"media/seg2/guard-{name}.json").read_text())
            codes = collections.Counter(x["code"] for x in v.get("violations", []))
        except Exception:
            codes = {}
        kept = sum(s["len"] for s in segs)
        total = cj["source"]["duration_s"]
        failed.append((name, kept, total, codes))

if failed:
    print("CLIP GUARD FAILED — owner footage is being cut, not just sped:")
    for name, kept, total, codes in failed:
        print(f"   {name}: {kept:.0f}s of {total:.0f}s used "
              f"({(1-kept/total)*100:.0f}% discarded)")
        for c, n in sorted(codes.items(), key=lambda x: -x[1]):
            print(f"      {c} x{n}")
    print("   The narration length is what forces this. Fix by re-timing the VO to the")
    print("   footage, or accept it explicitly: ALLOW_CLIP_CUT=1 bash tools/assemble2.sh")
    sys.exit(1)
print(f"  clip guard: {len(CONTRACTS)} contracted clips, none cut")
PYEOF
