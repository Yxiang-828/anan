# AnAn demo video — storyboard v2 · confident-male VO, burned captions, ~4:00

Voice: qwen3-TTS `english/16_confident_male` (owner order: no soothing woman).
Captions: whisper → SRT → burned in (open-source traced, not hand-typed).
Music: Jamendo instrumental bed, ducked under VO.
Owner clips: **sped up, never cut mid-action** (setpts; audio atempo where kept).

## The brief this script must answer
building process · the AI fleet · the sprites · the pitch · WHY these skills ·
every feature · what the console is FOR · why the app lives INSIDE the console ·
actual (local) vs hosted, and the inevitable Render cut (no qwen3-TTS on the demo server).

| # | vis | source | VO |
|---|-----|--------|----|
| v1 | night HDB block, one lit window | `night_block.jpg` (FLUX) | the problem |
| v2 | face-down phone, untouched breakfast | `phone_table.jpg` | the thesis: silence is an input |
| v3 | 93 words land, sort to three poles, converge on one | **motion** `media/motion/v3` | design started with vocabulary |
| v4 | nine skills, each with the failure it answers; then the refusals | **motion** `media/motion/v4` | why these nine skills, and what we refused |
| v5 | the camera walks all seven phases, each writing its receipt | **motion** `media/motion/v5` | every action writes seven receipts |
| v6 | FSM chips walking | `R1_treewalk` | the hero loop |
| v7 | STALE line closeup | `R2_stale` | the agent that changed its mind |
| v8 | dark workstation, commit wall | `build_night.jpg` + `C11` | one human, a fleet of agents |
| v9 | statesheet + sprite reel | `birds.png`, `bird-sprites` | codex drew it, then blocked my renderer |
| v10 | elder phone, greeting card | `C4_bird_talk` | the elder app: five tabs, bird is the button |
| v11 | smile + mobility + heart rate | **owner clips (sped)** | CV on device, only the score leaves |
| v12 | wander map + telegram alert | `C8`, owner wander clip | the geofence |
| v13 | family voice record page | `family.png` | ten seconds becomes her daughter's voice |
| v14 | full console breathing | `console.png` | what the console is FOR |
| v15 | console with elder app embedded | `M1_console_master` | why the app lives inside it |
| v16 | actual vs hosted, lane by lane, ending on what was NOT cut | **motion** `media/motion/v16` | actual vs hosted — the Render cut |
| v17 | sunrise, bird, links | `finale_sunrise.jpg` | close |

## VO script (as generated)
See `media/vo2/*.txt` — each line is the exact text fed to qwen3-TTS and to whisper
for caption alignment, so captions and speech cannot drift.


## Motion segments (added 2026-08-11)

Four segments measured as stills (<0.8% of the frame changing per frame) while
their narration enumerated things. They are now HTML compositions rendered
frame-by-frame through headless Chrome with the `motion-compose` skill, which
refuses any render that still measures as a still.

    # re-render one after editing media/motion/<seg>/index.html
    KEEL_INPUT_PROJECT=$PWD/media/motion/v5 \
    KEEL_INPUT_COMPOSITION=$PWD/media/motion/v5/index.html \
    KEEL_INPUT_OUT=$PWD/media/motion/v5.mp4 \
      python3 ~/aiko/arsenal/skills/motion-compose/run.py

The `.mp4` renders are gitignored — the `index.html` is the source, and GSAP is
vendored so a fresh clone re-renders offline.

**Layout law for this video:** the burned captions occupy **bottom 215-257px**
(measured, not assumed — a second line grows upward from there). Keep any HUD
element below ~200px or above ~300px.

**Left as real footage on purpose:** v1 (night block), v6, v10, v15. They
measure as near-stills because a console genuinely does not move much; replacing
them with motion graphics would delete the evidence the product exists.
