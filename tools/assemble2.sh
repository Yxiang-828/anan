#!/bin/bash
# AnAn demo video v2 — confident-male VO, burned traced captions, CC-BY music bed.
#
# Owner orders honoured here:
#   * his phone clips are SPED UP (setpts), never chopped mid-action. Where a clip
#     is longer than its slot, the speed factor is computed from the real duration
#     so the WHOLE action still plays.
#   * mobility.mp4 contains THREE separate exercises (sit-and-stand, shoulder
#     abduction, standing march) plus the completion card. The montage takes the
#     sit-and-stand block the narration actually names — a cut made with
#     understanding, not a blind trim.
#   * captions come from whisper timings over the exact spoken script.
set -eu
cd /home/dinosaur/Project/anan
V=media/vo2; S=media/seg2; A=docs/story-assets; C=media/captures; D=media_dump; DL=$HOME/Downloads
mkdir -p $S deliverables
FONT=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf

dur(){ ffprobe -v error -show_entries format=duration -of csv=p=0 "$1"; }
vdur(){ dur "$V/$1.wav"; }

# Caption style: bottom, big, high-contrast box — readable on a phone.
sub(){ echo "subtitles=$V/$1.srt:force_style='FontName=DejaVu Sans,Fontsize=17,Bold=1,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BackColour=&HB0000000,BorderStyle=4,Outline=0,Shadow=0,MarginV=54,Alignment=2'"; }

# still <key> <image> [zoom-direction]  — Ken Burns over a generated/captured still.
#
# NEVER force a source to 16:9. zoompan's s=1920x1080 rescales whatever it is
# handed, so a portrait screenshot (family.png, 560x900) was being stretched to
# 178% of its width — the distortion the owner has flagged twice. Sources within
# ~4% of 16:9 are pushed as before; anything else is fitted whole inside the
# frame over a blurred, darkened copy of itself, the same treatment portrait
# phone clips already get.
still(){ local k=$1 img=$2 zd=${3:-in}
  local d; d=$(vdur $k); local f; f=$(python3 -c "print(int($d*30)+18)")
  local z; if [ "$zd" = in ]; then z="min(1.0001+0.00035*on,1.13)"; else z="max(1.13-0.00035*on,1.0001)"; fi
  local ar; ar=$(python3 -c "
import subprocess
w,h=subprocess.run(['ffprobe','-v','error','-select_streams','v:0','-show_entries','stream=width,height','-of','csv=p=0','$img'],capture_output=True,text=True).stdout.strip().split(',')[:2]
print(round(int(w)/int(h),4))")
  local fits; fits=$(python3 -c "print(1 if abs($ar-1.7778)<=0.075 else 0)")
  if [ "$fits" = 1 ]; then
    ffmpeg -y -loglevel error -loop 1 -i "$img" -i "$V/$k.wav" \
      -filter_complex "[0:v]scale=2600:-2,zoompan=z='$z':d=$f:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1920x1080:fps=30,\
setsar=1,$(sub $k)[v]" \
      -map "[v]" -map 1:a -t "$d" -c:v libx264 -preset medium -crf 20 -c:a aac -ar 48000 -ac 2 -pix_fmt yuv420p "$S/$k.mp4"
    echo "{\"key\":\"$k\",\"src\":\"$img\",\"ar\":$ar,\"mode\":\"kenburns\"}" >> $S/geometry.jsonl
    echo "{\"key\":\"$k\",\"kind\":\"still\",\"src\":\"$img\"}" >> $S/provenance.jsonl
    echo "  still  $k  ${d}s  ar=$ar  <- $(basename $img)"
  else
    # the fitted foreground gets its OWN Ken Burns push, in a box whose aspect
    # equals the source's — so it moves without being distorted. Fitting alone
    # left the picture static and the whole segment read as a slide again.
    local fw fh; fh=1010
    fw=$(python3 -c "print(int(round($ar*1010/2))*2)")
    ffmpeg -y -loglevel error -loop 1 -i "$img" -i "$V/$k.wav" \
      -filter_complex "[0:v]split=2[a][b];\
[a]scale=2600:-2,zoompan=z='$z':d=$f:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1920x1080:fps=30,\
gblur=sigma=44,eq=brightness=-0.22,setsar=1[bgb];\
[b]scale=w=-2:h=2400,zoompan=z='$z':d=$f:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=${fw}x${fh}:fps=30,setsar=1[fg];\
[bgb][fg]overlay=(W-w)/2:(H-h)/2,$(sub $k)[v]" \
      -map "[v]" -map 1:a -t "$d" -c:v libx264 -preset medium -crf 20 -c:a aac -ar 48000 -ac 2 -pix_fmt yuv420p "$S/$k.mp4"
    echo "{\"key\":\"$k\",\"src\":\"$img\",\"ar\":$ar,\"mode\":\"fitted\"}" >> $S/geometry.jsonl
    echo "{\"key\":\"$k\",\"kind\":\"still\",\"src\":\"$img\"}" >> $S/provenance.jsonl
    echo "  still  $k  ${d}s  ar=$ar  FITTED whole (not stretched)  <- $(basename $img)"
  fi; }

# land <key> <clip> <in> — landscape capture, sped to fill the slot exactly
land(){ local k=$1 src=$2 ss=${3:-0} len=${4:-0}
  local d sd sp; d=$(vdur $k)
  if [ "$len" = 0 ]; then sd=$(python3 -c "print(max(0.1,$(dur "$src")-$ss))"); else sd=$len; fi
  sp=$(python3 -c "print(round(max(1.0,$sd/$d),4))")
  ffmpeg -y -loglevel error -ss "$ss" $([ "$len" = 0 ] || echo -t "$len") -i "$src" -i "$V/$k.wav" \
    -filter_complex "[0:v]setpts=PTS/$sp,scale=1920:-2,crop=1920:1080,fps=30,setsar=1,\
tpad=stop_mode=clone:stop_duration=$d,$(sub $k)[v]" \
    -map "[v]" -map 1:a -t "$d" -c:v libx264 -preset medium -crf 20 -c:a aac -ar 48000 -ac 2 -pix_fmt yuv420p "$S/$k.mp4"
  echo "{\"key\":\"$k\",\"kind\":\"land\",\"src\":\"$src\"}" >> $S/provenance.jsonl
  echo "  land   $k  ${d}s  speed x$sp  <- $(basename "$src")"; }

# phone <key> <clip> <in> <len> — portrait phone clip, blurred pillarbox, sped to slot
phone(){ local k=$1 src=$2 ss=${3:-0} len=${4:-0}
  local d sd sp; d=$(vdur $k)
  sd=$([ "$len" = 0 ] && python3 -c "print(max(0.1,$(dur "$src")-$ss))" || echo "$len")
  sp=$(python3 -c "print(round(max(1.0,$sd/$d),4))")
  ffmpeg -y -loglevel error -ss "$ss" $([ "$len" = 0 ] || echo -t "$len") -i "$src" -i "$V/$k.wav" \
    -filter_complex "[0:v]setpts=PTS/$sp,fps=30,split[bg][fg];\
[bg]scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,gblur=sigma=42,eq=brightness=-0.16[b];\
[fg]scale=-2:1010[f];[b][f]overlay=(W-w)/2:(H-h)/2,setsar=1,\
tpad=stop_mode=clone:stop_duration=$d,$(sub $k)[v]" \
    -map "[v]" -map 1:a -t "$d" -c:v libx264 -preset medium -crf 20 -c:a aac -ar 48000 -ac 2 -pix_fmt yuv420p "$S/$k.mp4"
  echo "{\"key\":\"$k\",\"kind\":\"phone\",\"src\":\"$src\"}" >> $S/provenance.jsonl
  echo "{\"key\":\"$k\",\"src\":\"$src\",\"ss\":$ss,\"len\":$sd,\"slot\":$d,\"rate\":$sp,\"audio\":\"preserve\"}" >> $S/editplan.jsonl
  echo "  phone  $k  ${d}s  speed x$sp  <- $(basename "$src")"; }

# motion <key> <render> — a rendered HTML composition (motion-compose): real
# generated motion for the segments that had no footage and could have none.
# The renders are cut a hair LONGER than their narration, so -t trims rather
# than the picture running out; tpad is the belt to that braces.
motion(){ local k=$1 src=$2
  local d; d=$(vdur $k)
  ffmpeg -y -loglevel error -i "$src" -i "$V/$k.wav" \
    -filter_complex "[0:v]fps=30,scale=1920:1080,setsar=1,\
tpad=stop_mode=clone:stop_duration=$d,$(sub $k)[v]" \
    -map "[v]" -map 1:a -t "$d" -c:v libx264 -preset medium -crf 20 -c:a aac -ar 48000 -ac 2 -pix_fmt yuv420p "$S/$k.mp4"
  echo "{\"key\":\"$k\",\"kind\":\"motion\",\"src\":\"$src\"}" >> $S/provenance.jsonl
  echo "  motion $k  ${d}s  <- $(basename $src)"; }

: > $S/geometry.jsonl
: > $S/provenance.jsonl
: > $S/editplan.jsonl
echo "── building segments"
still v1  $A/night_block.jpg      in
still v2  $A/phone_table.jpg      out
motion v3  media/motion/v3.mp4
land  v4  $C/M1_console_master.mp4 8  58
land  v5  $C/R2_stale.mp4          20 38
land  v6  $C/R1_treewalk.mp4       22 38
land  v7  $C/R2_stale.mp4          44 32
still v8  $A/build_night.jpg      in
still v9  docs/img/birds.png      in
land  v10 $C/C4_bird_talk.mp4      0
# v11 — three checks share one narration line. Each clip is SPED to its third of
# the slot so the whole action survives; nothing is chopped mid-rep.
piece(){ local out=$1 src=$2 ss=$3 len=$4 slot=$5
  local sp; sp=$(python3 -c "print(round(max(1.0,$len/$slot),4))")
  ffmpeg -y -loglevel error -ss "$ss" -t "$len" -i "$src" \
    -filter_complex "[0:v]setpts=PTS/$sp,fps=30,split[bg][fg];\
[bg]scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,gblur=sigma=42,eq=brightness=-0.16[b];\
[fg]scale=-2:1010[f];[b][f]overlay=(W-w)/2:(H-h)/2,setsar=1[v]" \
    -map "[v]" -an -t "$slot" -c:v libx264 -preset medium -crf 20 -pix_fmt yuv420p "$S/$out.mp4"
  echo "{\"key\":\"$out\",\"src\":\"$src\",\"ss\":$ss,\"len\":$len,\"slot\":$slot,\"rate\":$sp,\"audio\":\"drop\"}" >> $S/editplan.jsonl
  echo "    piece $out  x$sp"; }
D11=$(vdur v11); T=$(python3 -c "print(round($D11/3,3))")
piece p11a "$DL/smile.mp4"             2  14 "$T"   # smile symmetry, 98%→58%
piece p11b "$DL/mobility.mp4"          1  17 "$T"   # the sit-and-stand block the VO names
piece p11c "$D/heart_rate_tracker.mp4" 3  24 "$T"   # camera PPG
printf "file 'p11a.mp4'\nfile 'p11b.mp4'\nfile 'p11c.mp4'\n" > $S/v11.txt
ffmpeg -y -loglevel error -f concat -safe 0 -i $S/v11.txt -c copy $S/v11_mute.mp4
ffmpeg -y -loglevel error -i $S/v11_mute.mp4 -i "$V/v11.wav" \
  -filter_complex "[0:v]tpad=stop_mode=clone:stop_duration=$D11,$(sub v11)[v]" \
  -map "[v]" -map 1:a -t "$D11" -c:v libx264 -preset medium -crf 20 -c:a aac -ar 48000 -ac 2 -pix_fmt yuv420p $S/v11.mp4
echo "  montage v11  ${D11}s (3 checks)"
land  v12 $C/C8_wander_map.mp4     16 24
still v13 docs/img/family.png     in
still v14 docs/img/console.png    in
land  v15 $C/M1_console_master.mp4 92 36
motion v16 media/motion/v16.mp4
still v17 $A/finale_sunrise.jpg   in
echo "── segments built"

# ── geometry gate ────────────────────────────────────────────────────────────
# A stretched frame ships silently: it fills the frame, there are no bars, and
# nothing measurable in the OUTPUT distinguishes distorted from correct — I tried
# cropdetect first and it cannot see a blurred pillarbox, so it passed the stretch
# and failed the fix. The truth only exists HERE, where the source aspect and the
# filter path are both known. So assert the path, and fail the build.
python3 - <<'PYEOF' || exit 1
import json, pathlib, sys
rows=[json.loads(l) for l in pathlib.Path("media/seg2/geometry.jsonl").read_text().splitlines() if l.strip()]
bad=[r for r in rows if abs(r["ar"]-1.7778) > 0.075 and r["mode"] != "fitted"]
for r in rows:
    print(f"  {r['key']:<4} ar={r['ar']:<7} {r['mode']}")
if bad:
    print("GEOMETRY GATE FAILED — these sources are not 16:9 and were force-resized:")
    for r in bad:
        print(f"   {r['key']}: {r['src']} ar={r['ar']} -> 1.78 "
              f"({abs(r['ar']-1.7778)/r['ar']*100:.0f}% distortion)")
    sys.exit(1)
print(f"  geometry gate: {len(rows)} stills, none force-resized")
PYEOF

# ── footage gate ─────────────────────────────────────────────────────────────
# I replaced two of the owner's real product captures (v4 M1_console_master,
# v5 R2_stale) with generated animations because they MEASURED as low-motion.
# That was the wrong reason: low motion in real evidence is not the same defect
# as a Ken Burns push over a photograph, and removing footage removes the proof
# the product exists. Nothing in the build noticed. Now it does.
python3 - <<'PYEOF' || exit 1
import json, pathlib, os, sys
cur = {}
for l in pathlib.Path("media/seg2/provenance.jsonl").read_text().splitlines():
    if l.strip():
        r = json.loads(l); cur[r["key"]] = r
ref = pathlib.Path("media/provenance-approved.json")
if not ref.is_file():
    ref.write_text(json.dumps(cur, ensure_ascii=False, indent=1))
    print(f"  footage gate: baseline recorded, {len(cur)} segments")
    sys.exit(0)
old = json.loads(ref.read_text())
FOOTAGE = {"land", "phone", "montage"}
lost = [k for k, v in old.items()
        if v.get("kind") in FOOTAGE and cur.get(k, {}).get("kind") not in FOOTAGE]
if lost and not os.environ.get("ALLOW_FOOTAGE_SWAP"):
    print("FOOTAGE GATE FAILED — owner footage replaced by generated/still content:")
    for k in lost:
        print(f"   {k}: was {old[k]['kind']} {old[k]['src']}"
              f"  ->  now {cur.get(k,{}).get('kind','MISSING')} {cur.get(k,{}).get('src','')}")
    print("   If this is intended: ALLOW_FOOTAGE_SWAP=1 bash tools/assemble2.sh")
    print("   then refresh the baseline: media/provenance-approved.json")
    sys.exit(1)
if os.environ.get("ALLOW_FOOTAGE_SWAP"):
    ref.write_text(json.dumps(cur, ensure_ascii=False, indent=1))
    print("  footage gate: swap explicitly allowed, baseline updated")
else:
    print(f"  footage gate: {sum(1 for v in cur.values() if v['kind'] in FOOTAGE)} "
          f"footage segments intact")
PYEOF

if [ -z "${ALLOW_CLIP_CUT:-}" ]; then bash tools/clip_guard.sh || exit 1; else echo "  clip guard: cutting explicitly allowed"; fi

echo "── end card (CC-BY attribution is a licence condition, not decoration)"
ffmpeg -y -loglevel error -loop 1 -t 7 -i media/endcard.png \
  -f lavfi -t 7 -i anullsrc=r=48000:cl=stereo \
  -filter_complex "[0:v]scale=1920:1080,fps=30,setsar=1,fade=t=in:st=0:d=0.6[v]" \
  -map "[v]" -map 1:a -c:v libx264 -preset medium -crf 20 -c:a aac -ar 48000 -ac 2 -pix_fmt yuv420p $S/v18.mp4

echo "── concatenating"
: > $S/final.txt
for k in v1 v2 v3 v4 v5 v6 v7 v8 v9 v10 v11 v12 v13 v14 v15 v16 v17 v18; do
  [ -f "$S/$k.mp4" ] || { echo "MISSING $S/$k.mp4" >&2; exit 1; }
  echo "file '$k.mp4'" >> $S/final.txt
done
ffmpeg -y -loglevel error -f concat -safe 0 -i $S/final.txt \
  -c:v libx264 -preset medium -crf 20 -c:a aac -b:a 192k -pix_fmt yuv420p $S/body.mp4
BODY=$(dur $S/body.mp4); echo "  body: ${BODY}s"

echo "── music bed (CC-BY, ducked under narration)"
# sidechaincompress: the bed ducks itself whenever narration is present, so the
# voice never fights the music and no manual keyframing is needed.
ffmpeg -y -loglevel error -i $S/body.mp4 -stream_loop -1 -i media/music/bed.mp3 \
  -filter_complex "\
[1:a]volume=0.30,afade=t=in:st=0:d=2,afade=t=out:st=$(python3 -c "print(max(0,$BODY-4))"):d=4[bed];\
[0:a]asplit=2[vo][key];\
[bed][key]sidechaincompress=threshold=0.05:ratio=9:attack=8:release=420[duck];\
[vo][duck]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[a]" \
  -map 0:v -map "[a]" -t "$BODY" -c:v copy -c:a aac -b:a 192k -movflags +faststart \
  deliverables/AnAn-DemoVideo-SyntaxError.mp4

OUT=deliverables/AnAn-DemoVideo-SyntaxError.mp4
echo "FINAL: $(dur $OUT)s  $(du -h $OUT | cut -f1)"
cp $OUT docs/AnAn-DemoVideo-SyntaxError.mp4
