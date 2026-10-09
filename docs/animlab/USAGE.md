# Animation lab, phase 1: REPLAY (usage)

Replays a recorded first-person viewmodel session through the real solver, offline, and prints the in-game
`vmcheck` metrics per pose state. Variants (setting overrides or patched solver source) run in parallel.
600 frames take ~0.1 s, so a 10-variant sweep of a 2500-frame recording takes a few seconds.

Pieces:
- `tools/animlab/recfmt.py`: reader for `fp_vm rec dump` recordings (format in its docstring).
- `tools/animlab/metrics.py`: per-frame and per-state metrics (`wb`, `elb_h`, `st`, `edge`, `jit`, `step`).
- `tools/animlab/animlab.py`: CLI (`metrics`, `compare`, `replay`, `sweep`, `gate`).
- An **adapter**: any command `CMD <rec.txt> <out.txt> [args]` that replays the recording through a solver and
  writes a recording in the same format. KenshiFP's adapter (`kfpvm_replay`) lives in the KenshiFP workspace
  (`components/KenshiFP/animlab/`), not in this public repo: it compiles the real `kfp_viewmodel.inc`.

## One-liners (WSL)

```
# build the KenshiFP adapter against a read-only copy of the current source (+ the rec-native patch if not merged yet)
bash components/KenshiFP/animlab/build.sh --sync [--patch pending-fixes/kfp-rec-native-meta.py] --out /root/animlab-build/kfpvm_cur
# metrics of one recording (game or replay)
python3 tools/animlab/animlab.py metrics rec.txt
# replay + compare with the game
python3 tools/animlab/animlab.py replay rec.txt --adapter /root/animlab-build/kfpvm_cur --args=--quiet
# sweep: settings variants and patched-source variants side by side, in parallel
python3 tools/animlab/animlab.py sweep rec.txt --adapter /root/animlab-build/kfpvm_cur --args=--quiet \
    --variant 'st1: --set stretch=1 --quiet' --variant 'noelb: --set elb=0 --quiet' \
    --variant 'fix@/root/animlab-build/kfpvm_fix: --quiet' --metrics wb_p95,st_max,elb_h_max,jit_p95
# faithfulness gate (exit 0 = PASS)
python3 tools/animlab/animlab.py gate rec1.txt rec2.txt --adapter /root/animlab-build/kfpvm_6c9516b --args=--quiet --quiet
```
Use `--args=...` (with `=`) when the value starts with `--`. A patched-source variant is a second binary:
`build.sh --sync --patch my-fix.py --out /root/animlab-build/kfpvm_fix` (`.py` = script called with the client dir,
`.patch` = `patch -p1`); `--rev <git rev>` builds the solver as committed in the workspace snapshot instead.

Adapter options (`kfpvm_replay`): `--set k=v` (any `fp_vm set` key, applied after the recording's own `# set -1`
lines), `--set-at frame:k=v`, `--calib L1R,L2R,L1L,L2L,K` (sweep passes the base run's calibration to every variant),
`--no-native` (ignore the recorded native pose), `--no-rec-sets`, `--apply-all` (apply on every frame instead of
only where the recording's `napply` counter moved), `--cold` (start from a draw instead of record 0's state),
`--bw-lag` (experiment: bone-world queries inside the apply see the previous frame's pose), `--quiet`.

## Metrics (per state)

States: `ready`, `swing`, `block`, `swing->block`, `aim`, `reload` (crossbow), `settle` (gate only: 0.3 s after a
swing/reload/blend and the frame before one), `draw`/`lower` (blends), `native` (zoomed out, zf < 0.99: the body plays
the native animation), `off`. Rendered pose of frame i = skeleton measured in record i+1, re-expressed in frame i's
camera.

| metric | meaning |
|---|---|
| `wb_p95`, `wb_max` | wrist bend, deg (weapon forearm vs hand X axis) |
| `elb_h_max`, `elb_h_mean` | weapon elbow height above the shoulder along world up, dm |
| `st_max`, `st_p95` | upper-arm stretch of the weapon arm (1 = native length) |
| `edge_mean`, `edge_max` | cos(blade edge, eye->wrist); +1 = edge away from the camera |
| `jit_p95` | weapon tip screen jitter, px at 1600x900 (distance from the time-weighted midpoint of its neighbours) |
| `step_p95` | tip screen step per frame, px |
| `move_dm`, `move_deg` | how far the state moves the weapon from the median ready pose: grip displacement (dm) and blade/stock axis angle (deg); held states (aim, block) by their median pose, paths (swing, reload) by their largest frame. `metrics` prints `moves PASS|FAIL`: each required state (`--require`, default aim,reload or block,swing by the states seen) must exist and move >= 1.0 dm or >= 15 deg. `aim` = ti 1 AND UI state aiming (a ti label alone let a never-shown aim pass, KenshiFP C1) |

**Adding a metric:** compute it per frame in `metrics.frame_metrics()` (or `rendered()` for pose quantities), add
the aggregate to `state_table()` and its name to `METRIC_COLS`; it then shows in `metrics` and can be picked in
`sweep --metrics`. To gate on it, add `m_<name>` (max |game - replay|) to `DEFAULT_TOL` in `animlab.py`, and a
synthetic case to `tests/animlab/test_animlab.py`.

## Faithfulness gate

`gate` replays each recording and compares it with the game, per frame (grip, elbow, wrist position error dm;
blade forward / edge angle deg; wrist bend deg; p95) and per state (metric game vs replay). Tolerances (`DEFAULT_TOL`,
override with `--tol file.json`):

| check | tolerance |
|---|---|
| grip / wrist p95 | 0.25 dm |
| elbow p95 | 0.35 dm |
| blade forward p95 / edge p95 | 3 deg / 4 deg |
| wrist bend p95 (per frame) | 4 deg |
| state metrics | wb_p95 4 deg, elb_h_max 0.4 dm, st_max 0.08, edge_mean 0.06, jit_p95 2 px |
| comparable frames | >= 100 |

Gated states: `ready`, `block`, `aim`. Swing and reload are reported as `(info)`: the free swing tracks the native
swing animation and the crossbow reload blends the native arms, and recordings made before the **rec-native** KenshiFP
patch hold only the post-IK skeleton, so the replay has to use the next frame's post-IK skeleton as the native pose.
With a recording that has the native group (`pending-fixes/kfp-rec-native-meta.py`, coordinator applies it) the
replay uses the recorded native pose, and reload/swing become comparable (the round trip reproduces reload exactly).

Results (2026-10-09, recordings `vmq-f8c` = workspace commit 6c9516b, solver 6c9516b):

| recording | frames | grip95 | elbow95 | edge95 | wb95 | result |
|---|---|---|---|---|---|---|
| sword-z0-a (ready + block) | 556 | 0.15-0.22 | 0.20-0.22 | 1.5 | 0.1-1.3 | PASS |
| crossbow-z0 (ready + aim) | 1380 | 0.13-0.14 | 0.14 | 0.0 | 0.4-0.8 | PASS |
| sword-z0 (ready + block; swing info) | 378 | 0.21-0.22 | 0.22-0.23 | 2.0 | 0.1-1.2 | FAIL: block jit 6.6 game vs 3.4 replay |
| crossbow-z0 reload (info) | 813 | 0.13 | 0.62 | 0.0 | 7.2 | not gated (no native pose in the recording) |

## What it can and cannot check

Can: everything the solver computes from its inputs: targets, IK, elbow choice, stretch, wrist bend, blade roll,
holds/blends, settings and source variants, on the exact frame timing, camera motion and native torso of a real session.

Cannot (yet):
- **Jitter is under-reported.** The replay's world<->skeleton map is exact (world = skeleton space); in the game
  the map is rebuilt each frame from bone-world queries. Measured: ready jit_p95 game 1.2-1.7 px vs replay 0.01-0.4 px
  on the same recordings. So a replay jitter value is the solver's own jitter (lower bound), not the game's.
- Native-animation-driven states (swing, reload) on recordings without the native group (see above).
- A replay that starts mid-session warm-starts from record 0; hidden solver history (elbow look-ahead, roll history)
  can pick another branch of a bistable choice (sword elbow), so long sword replays can diverge from the game.
- Zoomed-out frames (zf < 0.99) show the native animation only: not compared.

## Regression (run before every animlab commit; also covers phase 2)

`bash components/KenshiFP/animlab/regress.sh` (WSL): offline unit tests, the gate above, and the native round trip.
Unit tests only: `python3 tests/animlab/test_animlab.py`. Phase 1 is tagged `animlab-p1`.

# Phase 2: METRICS LAB (author motions, measure them through the real solver)

Write a motion as time-keyed weapon targets (JSON), solve it through the viewmodel solver on a real recorded body
(skeleton, shoulders, arm lengths and prop calibration from a game recording), and get per-segment metrics plus reach
limits and intersections. Phase-1 commands are unchanged; this is a separate CLI (`tools/animlab/metricslab.py`) and a
separate adapter entry point (KenshiFP: `kfpvm_drive`, `build.sh --drive`).

```
A=/mnt/c/KenshiModding/components/KenshiFP/animlab; L=/mnt/c/KenshiModding/Kenshi-Automation-Harness/tools/animlab
bash $A/build.sh --sync --drive --out /root/animlab-build/kfpvm_drive_cur            # drive adapter, current source
python3 $L/metricslab.py run $A/motions/dualwield-alternate.json --adapter /root/animlab-build/kfpvm_drive_cur \
        --body vmrec-q-sword-z0-a.txt --body-frame 100 --out ml-dw --args=--quiet    # table + RESULT line, exit 0 = PASS
python3 $L/metricslab.py fromrec vmrec-q-sword-z0-a.txt 83 232 -o start.json        # start authoring from a recording
python3 $L/metricslab.py sample motion.json -o dir                                  # interpolated frames only
python3 $L/metricslab.py faithful vmrec-q-crossbow-z0.txt 345 1097 --adapter /root/animlab-build/kfpvm_drive_6c9516b
```

**Motion file** (camera numbers of the body frame: x right, y up, z forward, decimetres):
`{"name", "fps": 60, "interp": "spline|linear|smooth", "preroll": 0.5, "hold": 0, "limits": {...}, "geom": {...},
"body": {"rec", "frame"}, "hands": {"R": {"weapon": "sword|crossbow", "blade": 8.0, "keys": [{"t", "p": [x,y,z],
"f": [..], "u": [..], "label", "ease"}], "off": "rest" | [{"t", "p"}]}, "L": {...}}}`.
`p` = grip (prop bone), `f` = toward the tip, `u` = edge (sword) / up (crossbow); `u` is re-orthogonalised to `f`.
Positions interpolate Catmull-Rom (`spline`), linear or smoothstep; directions slerp. A key's `label` names the segment
that starts there (report rows). `preroll` seconds hold key 0 first (solver smoothing settles; not reported).
Example: `components/KenshiFP/animlab/motions/dualwield-alternate.json` (guard, right cut, guard, left cut).

**Dual wielding:** each armed side is its own run (`--side L` solves the left hand as the weapon hand with the prop
local mirrored, `fp_vm set hand_m 0`); the other arm rests. `pose.txt` merges each side's own arm (input for phase 3).

**Report columns** (per side and segment, `*all*` = whole motion): `wb` wrist fold deg (forearm vs hand X),
`elb_h` elbow height over the shoulder, `st` stretch, `reach` shoulder-wrist / (L1+L2) (>1 = stretched arm),
`terr` solved grip vs authored grip dm (target out of reach / clamped), `ferr` blade direction error deg, `edge`
edge-to-camera cos, `jit` tip jitter the SOLVER adds (px, second difference of solved-minus-authored tip on screen, so
fast authored arcs don't count), `ww` blade/blade clearance dm (<0 = intersect; blades are capsules of radius
`geom.blade_r` 0.15), `warm` blade vs the other arm (capsule `arm_r` 0.35), `head` blade distance to the eye,
`clip` frames with an on-screen blade part nearer than `geom.near` (3 dm), `ikfail`.
Default limits (override per motion in `"limits"`): wb_max 30, terr_max 0.30, ferr_max 10, reach_max 1.5 (game ready
max ~1.49), ww_min 0, warm_min 0, head_min 1.0, clip_frames 0, jit_p95 2.0. Last line:
`RESULT <name> PASS|FAIL <side:key evidence> [fails=...]`; files in `--out`: frames_*.txt, solved_*.txt, pose.txt,
report.txt/json.

**Drive adapter contract:** `CMD <body_rec> <frames.txt> <out.txt> --body-frame N --side R|L [args]`, formats in the
`metricslab.py` docstring. KenshiFP's `kfpvm_drive` feeds each frame through the plugin's own commanded-pose path
(`fp_vm replay N t`: g_vm_rp), so vm_targets -> vm_apply (IK, elbow pick with look-ahead over the authored future,
wrist roll, edge clamp, stretch) is the game's code. The weapon pose is taken as given (no target smoothing).

**Drive gate** (`faithful`): the weapon pose the game rendered (record i+1) as the target on a still-body segment
(eye within 0.3 dm, full viewmodel, no swing) must give the game's measured arm, p95 <= 0.25 dm. Results:
crossbow-z0 345-1097 with its own source 6c9516b PASS (753 fr, elbow95 0.07, wrist95 0.003); sword-z0-a 83-232 PASS
with the current source (elbow95 0.05) but FAILS with 6c9516b (wrist95 1.1, elbow95 5.2: that build's frozen-replay
path did not reproduce the sword wrist roll; open in STATUS.md). Current-source crossbow fails against the old
recordings because X5 (xwalign) changed the crossbow elbow after they were made (expected).

Can't: native animation blending (swing/reload follow the native pose; the drive holds one body frame), target
smoothing/springs (authored poses are applied directly), body motion while walking.

# Phase 3: VISUAL LAB (render arms + weapon offline, frames / MP4 / side by side with a game frame)

`tools/animlab/visual/render.py` poses the game's own skeleton and arm/weapon meshes from per-frame joint data and
rasterises them (numpy z-buffer, flat shading) from the eye. Meshes and skeleton are Ogre binaries read from the game
install at run time (`tools/animlab/visual/ogre.py`: .mesh v1.8-v1.100, .skeleton v1.8x); nothing is copied or
committed. Needs python3 + numpy + Pillow; ffmpeg for MP4.

```
H=/mnt/c/KenshiModding/Kenshi-Automation-Harness/tools/animlab/visual
C=/mnt/c/KenshiModding/components/KenshiFP/animlab/visual.json
# MP4 of a game or replay recording (fp_vm rec dump), 800x450, fps from the recorded time stamps
python3 $H/render.py frames vmrec-q-sword-z0.txt --config $C -o sw-frames --mp4 sword-z0.mp4
# MP4 of an authored motion (phase-2 metricslab run output), both hands armed
python3 $H/render.py frames /tmp/al-dw/pose.txt --config $C --weapons R,L -o dw-frames --mp4 dualwield.mp4
# one frame (optionally over a background image)
python3 $H/render.py still pose.txt --config $C --frame 30 -o f30.png [--bg game.png] [--size 1600x900]
# validation: game screenshot + the `fp_vm state` dump of the same frame -> game | render | game with outlines
python3 $H/render.py compare e-h90.txt e-h90.png --config $C -o cmp.png [--scale 0.5]
```
Inputs (auto-detected): `fp_vm rec dump` recordings, phase-2 `pose.txt` / `solved_*.txt`, `fp_vm state` dumps.
Options: `--every N --from A --to B` (frame range), `--fps`, `--size WxH`, `--weapons R,L` (override weapon_sides),
`ANIMLAB_GAME_DIR` (override the config's game_dir). Each run prints `hand_x_err` = angle between the posed hand X axis
and the solver's measured one (convention check; 0-0.5 deg on all validated frames).

Config (KenshiFP: `components/KenshiFP/animlab/visual.json`): skeleton, body mesh (arm = triangles weighted >= 0.5 to
upper arm / forearm / hand), weapon meshes per hand, prop axes and prop-local rotation per weapon class
(`g_vm_ax` / `g_vm_pldq`), `prop_roll_deg` (the grip roll `g_vm_groll`; without it the hand is 45 deg off),
`prop_mirror` (off hand: quaternion x,y negated = the drive adapter's biped mirror), fov tangents, near plane, colours.

Validation (game frames from `C:\KenshiTestRuns\opt`, copied): e-flatA, e-h90, e-h-90 (three different katana poses,
1600x900): hand X error 0.3 / 0.5 / 0.4 deg; the rendered blade outline lies on the game's blade (incl. the curved tip
in e-h-90) and the arm outline around the gauntlet. Speed ~0.1 s per 800x450 frame (702-frame recording: 34 s).

Limits: arms are rigid per bone with fingers in the bind pose (no finger curl / grip), no textures, no clothing or
armour meshes (the game shows gloves/gauntlets), no camera-space effects (Kenshi's FOV zoom uses the config fov).
Frames where the solver has the arms out of view (holster, `w` -> 0) render black.

## Regression
`regress.sh` steps 7-8 run `tests/animlab/test_visual.py` (synthetic Ogre binaries: reader, rasteriser, posing, prop
mirror, CLI) and, when the game install exists, a real-asset still of the dual-wield example (both hand X errors < 1 deg).
