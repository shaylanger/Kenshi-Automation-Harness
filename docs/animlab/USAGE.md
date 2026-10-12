# Animation lab (usage)

Phases: 1 REPLAY (below), 2 METRICS LAB, 3 VISUAL LAB, 4 NATIVE (sections further down); take and video-frame checks under
"Take checks". Durable state, misses and next steps: STATUS.md.

## Phase 1: REPLAY

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

Live animation tables (KenshiFP `fp_tables`, file `fp_tables.txt`, format in KenshiFP `docs/LIVE_TABLES.md`): the lab
reads the same files. `kfpvm_replay`/`kfpvm_drive --tables <file>` apply a variant (after the recording's own `# set`
lines, which already carry the variant a game recording was filmed with); `kfpvm_tables check <file>` gives the game's
hash offline; `tools/animlab/fptables.py make|show|check|expand` writes variant files and expands sweep lists.

```
# build the KenshiFP adapter against a read-only copy of the current source (+ the rec-native patch if not merged yet)
bash components/KenshiFP/animlab/build.sh --sync [--patch pending-fixes/kfp-rec-native-meta.py] --out /root/animlab-build/kfpvm_cur
# adapter of EXACTLY a game take's build (replaying a take with any other adapter mispredicts): prints the path, builds +
# caches kfpvm_src-<sha8> from the pipeline source snapshot on first use, writes <adapter>.d/MATCHES
bash components/KenshiFP/animlab/adapter-for.sh <take.vmrec.txt | sha8> [--drive]
# metrics of one recording (game or replay)
python3 tools/animlab/animlab.py metrics rec.txt
# replay + compare with the game
python3 tools/animlab/animlab.py replay rec.txt --adapter /root/animlab-build/kfpvm_cur --args=--quiet
# sweep: settings variants and patched-source variants side by side, in parallel
python3 tools/animlab/animlab.py sweep rec.txt --adapter /root/animlab-build/kfpvm_cur --args=--quiet \
    --variant 'st1: --set stretch=1 --quiet' --variant 'noelb: --set elb=0 --quiet' \
    --variant 'fix@/root/animlab-build/kfpvm_fix: --quiet' --metrics wb_p95,st_max,elb_h_max,jit_p95
# game-only checks (no replay): C3 bolt rigid on the weapon (<rec>.bolt sidecar); C2 stock top <= 25% from the screen
# bottom in ready + ready orientation within 3 deg of a known-good recording
python3 tools/animlab/animlab.py bolt rec.txt
python3 tools/animlab/animlab.py stock rec.txt --ref good.txt [--max 25 --ori 3 --h 1.45]
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
Arm bone roll (not recorded): the fake upper arm / forearm get local Y = -(native bend normal) like the game rig
(in game `fp_vm hinge` captures 0,-1,0 for all four bones) and the E5 hinge starts captured as in the game;
`--up-roll` = the old synthetic roll (Y nearest camera up, replay captures its own hinge: ~60 deg forearm-roll error),
`--hinge-capture` = capture the hinge from the replayed frames. `animlab.py hinge <replay> --vs <game rec>` adds the
per-frame bone-roll faithfulness gate (forearm median <= 5 deg, `--faith`).

E6 swing variety: `animlab.py --only-stroke N <cmd> <rec>` judges only swings of scripted stroke N (rec group H 4th token;
other strokes are labelled `swing_x` and skip every swing gate); `hinge` compares swings of the same stroke only.
`animlab.py [--only-stroke N] blade <rec>` judges what a 30 fps video shows, per frame instead of per window: `snap` = sword
rotation over one video frame (33 ms) right after the wind-up top (<= 22 deg, `--snap`), `seen` = per-frame visible blade
(screen length of 7 dm of blade x |flat normal . view ray|; an edge-on katana is a hairline) over u .45-.95 (>= 0.05, `--seen`).
`animlab.py [--only-stroke N] stroke <rec> [--overhead 2]` judges how each stroke reads on screen: `len` = min on-screen
length of 7 dm of blade over u .40-.78 (>= 240 px at 1600x900, `--len`; a blade pointing into the screen is a short stub at
an odd angle to the forearm, which `inline`'s 0.5 dm grip segments and 3D angle do not see); for the scripted strokes listed
in `--overhead`: blade tilt from screen vertical <= 35 deg over u .28-.78 (`--tilt`) and the blade-middle path over the
stroke within 20 deg of straight down (`--path`). The tip leaving the top edge at an overhead's wind-up top is not gated
(a raised sword is expected to leave the frame).
`animlab.py [--only-stroke N] path <rec> [--stroke N] [--gate-info]` (R30, Shay 2026-10-11 PT17) judges each swing's screen
path: the blade tip (grip + 8 dm, FP eye, zoom 0, 1600x900, unclipped) from the stroke start (u .28) to the follow-through end
(u .78) must be ONE straight line: `dev` = max distance from the total-least-squares line / extent along it (<= .08, `--dev`),
`late` = max distance of the last 35 % of the path (arc length) from the line of the first 65 % / extent (<= .05, `--late`;
the PT17 "/|" end hook), `ang` = line angle from the horizontal (35-50 for the diagonals 0 and 3, `--ang-min/--ang-max`; other
strokes reported), `edge` = end tip distance to the nearest screen edge as a fraction (<= .12, `--edge`; PT17 s0 stopped
mid-screen), `len` = extent / screen width (info). Stroke 1 is accepted as it is (Shay 16:27): measured, never fails
(`INFO-FAIL`; `--gate-info` gates it, used by mutation rec-path-late-drift). Prints `pathsw s<stroke> swing<k> PASS|FAIL|INFO-FAIL
<numbers>` per swing (optimizer input) and `path PASS|FAIL swings=n [first_bad=...]`. Also: `pool --checks ...,path`, e6-takes.py
`E6TAKE <rec> s<n> path` (gate step 3c, new keys: non-blocking until the baseline holds a PASS), taste rule R30 (t90-t92).
Shay 17:05/17:25 rules in the same per-swing line (animlab-maintainer): `sweep=` blade angular sweep >= 70 deg (R31),
`wexit=` wind-up exit continuity (R32: a stroke starting off screen must be carried off in the wind-up, last on-screen
point within 25 % of the exit edge, back in through the same edge; `wexit=on` = starts on screen, `mid:` = tip off from
the ready pose so the blade middle is judged), plus one `pathrep s<stroke> PASS|FAIL rep=` line per stroke (R33, <= .03
of the width). Thrust strokes (`metrics.PATH_THRUST`) skip span/ang/edge/fast/sweep and gate the end tip near the centre
(R34). Zoom-0 framing (R35): `spec.py framed <rec>` (also `framed=` in `animlab.py weapons --run` and the gate check_suite):
a wrist on screen on >= 80 % of ready/block and 50 % of swing frames at zoom 0.

## Take checks (labelled video takes)
`tools/animlab/takecheck.py --labels <lab> --ev <ev> [--ev ...] --rules <rules> [--video <mp4> | --video-len <s>]` judges a
labelled video take against game state sampled while it was recorded (formats in the script header): every `claim` must
hold over the label's WHOLE segment with no unsampled gap > `maxgap` (a label true for 1 s of a 5 s segment fails), `pre`
= setup state at the label start (e.g. loaded before an aim), `forbid` = nothing may happen in the take (combat messages,
bystanders, KO), `cover` = keys sampled across the whole take, and the video must end at the `end` label (`endslack`).
Prints one line per check and `RESULT <name> PASS|FAIL <failed checks>`. A take without sampled evidence fails (unproven).
`--kfplog <KenshiFP.log> [--log-t0 HH:MM:SS.ms]` adds `animlive`: every free block / free swing in the take (log window
t0 .. t0 + end label + 1 s) must have run its native animation (`PT34 free block end ... live=1`, `free swing end ... live=1`);
progress that never went live (p 1.010, pmin 9.000) fails. Block tech ids in the log are heap pointers (per session: info only).
KenshiFP adapter: sampler `components/KenshiFP/animlab/take-sample.sh` (source it in the take script:
`take_sample_start <ev> "$T0" <fp char> ["<allowed>|..."]` ... `take_sample_stop`) + rules `take-rules.txt`.
`animlab.py guard <rec>`: block guard readability judged per press (runs of block frames): the median blade elevation
above the horizontal over each press's settled 70% must be >= -60 deg (`--elev`; a hanging guard, blade straight down with
the hilt at the face, is ~-80..-90); any hanging press fails; hilt-head distance info. `guard <survey>.tsv` judges a
per-press survey table (`blade_elev_deg` column, `tech=` in `evidence`) per row with a per-technique median.
**Lab agreement** (`animlab.py agree <manifest> [--status STATUS.md]`): the lab must predict the game. Manifest lines
`<game rec> <adapter of the rec's build> [adapter args]` (rec relative to the manifest); every rec is replayed and every
check that applies (metrics.check_suite: moves, branch, stock, guard, and per scripted stroke arc/churn/inline/blade/stroke/
hinge, plus the per-frame `gate`; zoomed-out recs without viewmodel frames get no gate row) runs on the game rec and on the
replay; a pass/fail difference is a disagreement = a lab bug with an open Misses row. `--status` rewrites the "Lab
agreement" section (summary + disagreements) and writes the full table to `<manifest>-table.md`. Corpus manifest:
`C:\KenshiTestRuns\corpus\agree\agree.list`.
**Native variant pools** (`animlab.py pool`): the game picks a native variant per occurrence (attack variant per swing,
free-block technique per press), so a check on one recording cannot predict a take. `pool @list --adapter A --stroke N
[--overhead 2] [--checks arc,blade,stroke]` replays every recording of the list with the stroke forced (`--stroke-args`,
KenshiFP default `--no-rec-sets --set stroke={stroke}`), judges every full swing on its own and prints the predicted take
pass rate (all `--take` 2-swing combinations; arc pooled over the take like the game gate, blade/stroke = every swing):
PASS when each check's rate >= `--rate` 0.95. `pool @list --motion block` judges every press of the recordings as recorded
(the zoomed-out block is the native pose; `--replay` re-solves it). List paths are relative to the list file; pools live in
the protected corpus `C:\KenshiTestRuns\corpus\pools\{sword-swing,block-guard}` (README there). `-v` prints every swing.
`animlab.py zoomband <rec> [--head-show 16]`: no own body in frame while the zoom camera is between the eye and the
head-show distance (head hidden there): neck/spine/shoulders projected from the camera `zoom` dm behind the eye (orbit 0),
elbows/wrists too once the viewmodel fades (zf < 0.99). Catches the Z1 crossfade's headless torso / floating hand.
`band_leak` (same command, `[--band-clip dm]`): on band_hidden frames the hide flag is not trusted (9C9ECB01 hat-brim /
neck slivers): head, hat (head + 1.2 dm up), neck, spine, shoulders, chest in view must lie inside the camera near clip
(depth + 1 dm margin <= nc). nc = the rec's group-4 10th token (KenshiFP kfp-vmrec-nc builds), else the build rule
`--band-clip` (KenshiFP band_clip_dm: 5 from e4bb536, 0 before = near 0.3), else SKIP. Corpus pair: rec/zs-sword-fade-on-07886691.txt
`--band-clip 0` FAIL, zs-sword-fade-on-8b3f.vmrec.txt `--band-clip 5` PASS.
Frames of the video itself: `tools/animlab/frames.py openground <mp4> [--from s --to s]` = judgeable open ground on the
RECORDED frames (sky share of the scene band between the title label and the UI panel >= 0.08 on >= 90% of frames at
2 fps; prints the closed spans); a setup check before recording is not enough (sword-z25-block: slope for 17 s). Night/fog fails.
`frames.py cursor <mp4>`: no Windows mouse cursor in any frame (arrow shape, any cursor size, full-res frames at 5 fps;
prints the spans). `takecheck.py --video` runs it on every take (`--no-cursor` skips).
Label lag (T6): `frames.py syncmarks <mp4>` = onsets of the harness `sync_flash` frames (full-view magenta). KenshiFP
`take-sample.sh` shows flash 0 at T0 and one per label (`take_mark "$*"` in the take script's lab(), none for `end`),
each with a `<t> mark sync=<n>` evidence line; `takecheck.py --video` pairs sends and flashes and FAILs `sync` when a
label's flash is missing or reaches the screen > 0.15 s (`set synclag`) earlier/later than the T0 flash, or a flash has
no send; `--synced-out <file>` writes the labels at their measured video times for the burn-in. Without take_mark (old
takes, harness without sync_flash) it is SKIP unless the rules say `set sync 1`. openground/cursor/overlay skip flash frames.
- **Punch reads** (NA1 fists, Misses 2026-10-11 "fist punch read"): `python3 components/KenshiFP/animlab/fist-punch-check.py <vmrec> [-v] [--camera]`
  judges every punch of a fist take (native es >= .5) on the per-frame vmrec: C1 depth, C2 aim, C3 travel, C4 snap, C5 recovery,
  C6 wind-up, C7 hand, C8 off hand, hold; C9 camera impulse INFO unless `--camera`. `RESULT FIST-PUNCH PASS|FAIL`; synthetic PASS
  reference `fist-punch-synth.py <src vmrec> <out>`.

## Video: decode once, NVDEC, GPU checks (cpu-video, Shay 2026-10-10)
- **Frame cache** `tools/animlab/framecache.py`: never decode a take video yourself; read frames through it.
  `framecache.frames(video, fps, w, h, t0, t1)` = uint8 memmap (N,h,w,3), decoded once per (fps, size) into
  `<video dir>/.framecache/<stem>-<sha1>/` (corpus videos: `/tmp/animlab-framecache`), shared under a file lock by every
  concurrent consumer (<= `ANIMLAB_FRAMECACHE_MAX_MB` 256, bigger requests return None: stream). `cached_check(name, fn)`
  wraps a check `fn(video, ...)` so an identical call (same video content, arguments, checking source) returns the
  stored result: frames.py syncmarks/cursor/overlay/openground use it, so takecheck, take scripts, the gate and
  review-pack runs on one take judge it once. `framecache.hwdec()` = ffmpeg `-hwaccel cuda` args (NVDEC; software
  fallback); autoreview.py and stamp.py use it for their own passthrough decodes. CLI `framecache.py info|clear <video>`;
  `ANIMLAB_FRAMECACHE=0` / `ANIMLAB_HWDEC=0` turn them off. Corpus turret-fp + sword-z25-block: identical RESULT lines,
  117 -> 41 and 59 -> 26 cpu-s cold, 0.4 warm.
- **GPU pixel maths** `tools/animlab/gpu.py` (CuPy, lowest-priority CUDA stream; numpy fallback, `ANIMLAB_GPU=0`):
  frames.py cursor/overlay candidate search runs on it; `python3 gpu.py` prints the active path.
- **Windows-native GPU under WSL** (gpu-native 2026-10-11: WSL CUDA/NVDEC goes through dxgkrnl GPU-PV, the 5090's
  13:16 BSOD + afternoon TDRs): `framecache.decode(video, pre, post)` runs every NVDEC decode (frames.py, autoreview.py,
  stamp.py) in Windows `ffmpeg.exe -hwaccel cuda` (`ANIMLAB_WIN_FFMPEG`); `framecache.native_check` runs frames.py
  cursor/overlay in Windows python + CuPy (`ANIMLAB_WIN_PYTHON`, via `native_run.py` on a content-hashed copy of
  tools/animlab in `%TEMP%\kah-native`, so gate snapshots run their own sources); videos Windows cannot see (gate
  namespaces' /tmp, bind-mounted snapshots) are copied there for the call. WSL NVDEC/CuPy = fallback only, at most 2
  WSL GPU processes (`framecache.gpu_slot`, flock `/run/kah-gpu/slot<i>`, `ANIMLAB_WSL_GPU_SLOTS`; the others queue).
  `ANIMLAB_NATIVE=0` = old WSL path, `ANIMLAB_DECODE=native|hw|sw` forces one decode path. Measured (56 s 1600x900
  corpus take): decode fps=5 full-res 5.3 -> 2.8 s, 160x90 3.6 -> 1.9 s, 256x144 passthrough 4.3 -> 1.5 s; cursor /
  overlay checks same wall (9-10 s / 4.7 s), WSL cpu 14 -> 0.05 s; identical RESULT lines. Test
  `tests/animlab/test_gpunative.py` (WSL). Windows python needs `pip install --user numpy pillow cupy-cuda12x
  nvidia-cuda-nvrtc-cu12 nvidia-curand-cu12 nvidia-cuda-runtime-cu12` (done on the 5090).
- **Recording** `tools/automation/venc.sh` `venc_args <crf> [x264-preset]` (sourced by rig-env.sh / take-preflight.sh):
  h264_nvenc on both rigs (probe cached per rig/day in `$TMPDIR/kah-venc.<rig>`), libx264 fallback, `VENC=x264|nvenc`
  forces. New take recorders use `$(venc_args 18)` instead of literal libx264 args.

## Auto-review (per-frame image checks; reviewers judge only flagged frames)

`tools/animlab/autoreview.py` (usage in its header) looks at EVERY encoded frame of a take video (VFR passthrough,
256x144, NVDEC via framecache) and writes `flags.tsv` + `crops/` (prev | FLAG | next at full resolution) + one
`RESULT <take>-autoreview PASS|FAIL flags=..` line. Checks: `oneview` (one view per FP/3P switch: no both / neither /
misplaced frame; with a frame stamp only the stamp's switch frame is judged and a settle that keeps the same objects passes), `fragments` (no stray body parts while the body is hidden in the zoom fade band), `occluder` (arm /
body across the lens, edge-connected foreground share per weapon), `weapon` (viewmodel weapon complete vs references in
`tools/animlab/autoreview-refs/<weapon>/<state>/`), plus frames.py's `overlay`, `cursor`, `openground`.
View/state per frame: the frame stamp (decoded from the video when it carries one; or `<stem>.stamp.txt`), else the
take's vmrec, else image-only rules (oneview needs a quiet side, fragments a short-event view showing less than both
neighbours for >= 0.25 s). Stills (screenshots) take `--plate <same spot, no viewmodel> --state <state>`.

    python3 autoreview.py run <video|png> <out> [--weapon fists|sword|crossbow] [--plate P --state S]
    python3 autoreview.py ref add <accepted video|png> <weapon> [--states ..] [--plate P]     # weapon references
    python3 autoreview.py selftest            # corpus rows `autoreview:<check>` FAIL+PASS: RESULT AUTOREVIEW-SELFTEST

`tools/automation/review-pack.py` runs it first (`--autoreview auto`, nice 15) and then builds sheets of the flagged
frames only (`flag-NN-<t>-<check>.jpg` + crop; `--full` = the old complete pack; falls back to complete when autoreview
cannot run, e.g. the 4080's Windows python). Known limits: image-only oneview misses a both-frame in the middle of a
swing (2E66 33.67 s; a stamp/vmrec view source covers it); occluder flags a fully extended punch near 15-17% too
(review pointer, not a verdict); weapon references so far: crossbow reload/aim/fired (XBMESH-A stills).

## CPU: result cache, search, one CPU budget (Shay 2026-10-10)
- **Result cache** `tools/animlab/labcache.py` (store `/root/animlab-cache`, 6 GB LRU; header has the CLI): adapter
  builds (`build.sh`: key = content of every compile input, so the same source under another name/tree hits), adapter
  replays (`labcache.py replay <adapter> <rec> <out> args`, used by regress.sh as `rp`), drive runs, recording checks and
  mutation verdicts (mutate.py: key = mutation code + base material + the check code it runs) are memoised by content
  hash. A fists patch never re-replays sword/crossbow. `ANIMLAB_CACHE=0` recomputes, `=verify` recomputes and compares;
  `labcache.py stats|prune|clear`. Gate on an unchanged tree: 390 -> ~196 CPU-s, 279 -> 160 s wall, verdicts identical
  (124 verdicts, pool, mutations; /root/cpu-lab m-before1 vs m-cold1/m-warm1).
- **Search** `tools/animlab/optim.py`: CMA-ES (default) / Nelder-Mead / coarse-to-fine with early stop (`target`,
  convergence `tol`, `maxevals`) and batched parallel evaluation; CLI `optim.py run`. Climbs use it instead of grids or
  random mutation loops (e.g. `components/KenshiFP/animlab/e1-climb.py`, `METHOD=cma|nm|cf|random TARGET=<score>`).
- **One CPU budget** (`tools/automation/labnice.sh` + `lab-recpause.sh`): every offline lab job runs through labnice
  (nice 15, ionice idle, all-or-nothing slots); `LABNICE_SLOTS` (default nproc/2 = 16 workers) normally,
  `LABNICE_REC_SLOTS` (default 12) while a 5090 take records: new jobs then take only slots 1..12 and lab-recpause
  SIGSTOPs only job trees holding a slot above 12 (`/tmp/labnice/held.<pid>`), SIGCONT when the recording ends.
  Cache-miss adapter runs outside labnice take one slot of the same pool. `LABNICE_REC_SLOTS=0` = pause everything
  while recording. A job asking for more than 12 while recording starts at once with 12; jobs without a held file are
  never paused; stale recording flags (marker or ffmpeg gdigrab older than 30 min) are ignored. `lab-recpause.sh
  --status|--which`, `labnice.sh --status`, selftest `tools/automation/labnice-selftest.sh` (private LAB_D).
- weapon_matrix temp dirs (`/tmp/animlab-wm-replay*`) are removed at exit.
- **One OpenBLAS thread per python** (gpu-lab 2026-10-11): `tools/automation/wsl-blas1.sh install|remove|status`
  (KenshiModding repo, installed in WSL) makes every WSL python3 run numpy with `OPENBLAS_NUM_THREADS=1` (system
  sitecustomize.py; `KAH_BLAS_THREADS=n|keep` overrides). Each numpy import used to start nproc (32) busy-spinning
  threads, or LABNICE_J under labnice: `import numpy` 1.35 s CPU (unset) / 0.37 s (=6) vs 0.07 s; one pasweep.py variant
  2.26 -> 0.94 s CPU, identical output. labnice.sh's OPENBLAS cap is overridden by it (OMP/MKL caps still apply).
- **forkbatch** `components/KenshiFP/animlab/forkbatch.py <jobs> -j N` (KenshiModding repo): drop-in for
  `xargs -P N -I{} -d '\n' bash -c '{}' < jobs` on variant sweeps whose lines are `python3 <script>.py args`
  (polearm pasweep.py, any per-variant evaluator). One warm parent (numpy + recfmt/metrics/weapon_matrix imported) forks
  a child per job (no interpreter start, no state leak, script read at run time); in the child recfmt.parse and
  metrics.rendered are memoised (judge() + the caller recomputed both 2-3x per replay). Use it inside labnice:
  `labnice.sh -s 6 python3 forkbatch.py jobs.txt -j 6 > out.txt 2>&1`. `--check K` = agreement selftest (K jobs forked vs
  plain bash, byte compare). Measured 2026-10-11 (24 fresh Naginata 2-stroke variants, -j 6, shared load): xargs
  (BLAS 6) 51 CPU-s -> forkbatch 33 CPU-s (-35%), 9.5 -> 7.2 s wall; cached-replay variants ~2x less CPU; checks
  6/6 fresh + 12/12 cached identical. What stays: the adapter replay (~0.45 s CPU per replay, ~70% of a variant now;
  75% of it the elbow search) is the KenshiFP C viewmodel, a branchy per-frame state machine over globals: it stays on
  the CPU (a GPU port = a second copy of the game code; WSL CUDA is off-limits, /etc/kah-no-gpu). Next cut there:
  fewer variants (optim.py CMA/early stop instead of random 1300-variant grids) and replay result reuse (labcache).
- **Optimizer populations in parallel + on the 4080** (load-balance 2026-10-11). `optim.proc_batch(fn, workers,
  on_result, inner_env='OBJ_J')`: fork process pool for a Python-heavy objective (a thread pool ran ~1 core under the
  GIL: 12-point CMA generation 104.6 s -> 13.6 s); `inner_env` gives a batch smaller than the pool the spare slots
  (CMA x0 alone: OBJ_J=workers). `tools/animlab/lab_remote.py`: `Remote(module, func, adapter=, data=, env=, workers=)`
  serves the objective on the 4080 (Windows Python at IDLE priority, so its Kenshi lanes keep the CPU; never the 4080's
  WSL), mingw-builds `<adapter>.exe` from `<adapter>.d`, copies module/adapter/data dirs by content hash; `split_batch(
  local_batch, rem, to_args, local_workers, on_result)` sends a share of every population there and adapts the share so
  both sides finish together; any remote error -> those points run locally (nothing lost), `LAB_REMOTE=0` = local only,
  `LAB_REMOTE_V=1` prints `k=<remote>/<n> local Xs remote Ys` per batch. Windows libm differs in the last digit (max
  0.002 on a pose dump): use it for optimizers/sweeps, not for gate verdicts; re-check a final optimum locally.
  Example: `/root/strokefix/opt-par.py` (remote on by default, OPT_REMOTE_J=6). Measured (sjl_v4 s2, 48 evals, 8 local
  workers, 5090 lab budget shared, 4080 filming 2 lanes): 68 s local -> 60 s with the 4080; a 4080 replay is 0.86 s vs
  0.47 s in 5090 WSL, so it pays most when the 5090's labnice slots are full. Selftest: `python3 lab_remote.py selftest`.

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

## Phase 2: METRICS LAB (author motions, measure them through the real solver)

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
**Left-hand mirror (exact):** mirrored (f,u) targets flip the prop axis perpendicular to both, the bone mirror flips z,
so the adapter uses prop local q -> (w,-x,-y,z) AND grip roll groll -> 180 - groll (sword; -groll when that axis is z);
`--set groll` takes the RIGHT-hand value. The solver's melee elbow pick also has three right-hand-only rules
(`g_vm_elbd`, the coarse-search bound `e.x < -0.25`, the `g_vm_rbe` f x u term): variant patch
`components/KenshiFP/animlab/patches/left-hand-mirror.py` makes them side-aware (for KenshiFP only if dual wielding goes
ahead). With both, `motions/dualwield-sync-mirror.json` on a symmetric body (sword-z0 frame 541) gives L == R in every
segment (regress.sh step 9). L/R differences that remain on a ready-stance body come from the stance itself: Kenshi's
sword stance twists the torso (frame 100: R shoulder 1.1 dm further back than L), so a camera-mirrored motion is not
body-mirrored.
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
Hand scale: default = the body record's recorded non-uniform hand scale (`hs`, rec native v2) when it has one, else
uniform C_K; `--hs x,y,z` forces a vector (e.g. Axima 0.914,1.058,0.914; zeroes a --l1 build's hoff), `--no-hs` = always
uniform C_K (a fixed Axima vector on the pre-v2 corpus bodies failed the drive gate: crossbow-z0 elbow95 0.07 -> 1.03).

**Drive gate** (`faithful`): the weapon pose the game rendered (record i+1) as the target on a still-body segment
(eye within 0.3 dm, full viewmodel, no swing) must give the game's measured arm, p95 <= 0.25 dm. `--commanded` drives the
commanded pose (out) instead: use it across swings (rendered targets flip the elbow branch at every swing tail, regress 16). Results:
crossbow-z0 345-1097 with its own source 6c9516b PASS (753 fr, elbow95 0.07, wrist95 0.003); sword-z0-a 83-232 PASS
with the current source (elbow95 0.05) but FAILS with 6c9516b (wrist95 1.1, elbow95 5.2: that build's frozen-replay
path did not reproduce the sword wrist roll; open in STATUS.md). Current-source crossbow fails against the old
recordings because X5 (xwalign) changed the crossbow elbow after they were made (expected).

Can't: native animation blending (swing/reload follow the native pose; the drive holds one body frame), target
smoothing/springs (authored poses are applied directly), body motion while walking.

## Phase 3: VISUAL LAB (render arms + weapon offline, frames / MP4 / side by side with a game frame)

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
`prop_mirror` (off hand: quaternion x,y negated, grip roll 180 - groll = the drive adapter's left grip), fov tangents, near plane, colours.

Validation (game frames from `C:\KenshiTestRuns\opt`, copied): e-flatA, e-h90, e-h-90 (three different katana poses,
1600x900): hand X error 0.3 / 0.5 / 0.4 deg; the rendered blade outline lies on the game's blade (incl. the curved tip
in e-h-90) and the arm outline around the gauntlet. Speed ~0.1 s per 800x450 frame (702-frame recording: 34 s).

Limits: arms are rigid per bone with fingers in the bind pose (no finger curl / grip), no textures, no clothing or
armour meshes (the game shows gloves/gauntlets), no camera-space effects (Kenshi's FOV zoom uses the config fov).
Frames where the solver has the arms out of view (holster, `w` -> 0) render black.

## Regression
`regress.sh` steps 7-8 run `tests/animlab/test_visual.py` (synthetic Ogre binaries: reader, rasteriser, posing, prop
mirror, CLI) and, when the game install exists, a real-asset still of the dual-wield example (both hand X errors < 1 deg).

## Phase 4: NATIVE (the game's own skeletal animations, offline)

`tools/animlab/native.py` reads the animations inside the game's Ogre `.skeleton` (`visual/ogre.py`: SK_ANIMATION tracks,
keyframes applied to the bind pose, linear position / shortest-path nlerp rotation, loop or clamp, as Ogre), plays and
samples them on the skeleton, renders them third person, extracts hand / weapon trajectories in first-person camera
numbers and adapts them into phase-2 motions or KenshiFP key tables that run through the real viewmodel solver (drive
adapter) and the recording checks. It is NOT the game's animation blending (layers, speed factors, blend-in) and has no
root-motion physics. Game files are read at run time (config `game_dir`, `ANIMLAB_GAME_DIR`); nothing is copied.

```
L=/mnt/c/KenshiModding/Kenshi-Automation-Harness/tools/animlab; A=/mnt/c/KenshiModding/components/KenshiFP/animlab
python3 $L/native.py list --config $A/native.json [--filter punch]                  # 174 clips on the male skeleton
python3 $L/native.py catalog --config $A/native.json -o catalog.md                    # techniques per weapon class (game data)
python3 $L/native.py sample --config $A/native.json "ma chudan" --fps 10 --bones "Bip01 R Hand"   # model-space bone poses, dm
python3 $L/native.py render --config $A/native.json "ma chudan" -o fr --views side,front[,z25] --sheet s.png [--mp4 m.mp4]
python3 $L/native.py traj  --config $A/native.json "chop down" --weapon katana --body vmrec-q-sword-z0-a.txt -o traj.txt
python3 $L/native.py adapt --config $A/native.json "chop down" --weapon katana --body vmrec-q-sword-z0-a.txt -o motion.json
python3 $L/native.py run   --config $A/native.json "chop down" --weapon katana --adapter /root/animlab-build/kfpvm_drive_cur \
        --body vmrec-q-sword-z0-a.txt --body-frame 100 --out run --visual $A/visual.json      # + native-vs-fp.mp4 / sheet
python3 $L/native.py fists --config $A/native.json "ma chudan,ma 2strike" --adapter /root/animlab-build/kfpvm_drive_cur \
        --body vmrec-q-sword-z0-a.txt --body-frame 100 --out fists --visual $A/visual.json     # key tables + NA1 checks# fist tables that ship: solve on the game model (L1, the game over-reaches near full extension) and the unarmed body:
bash $A/build.sh --drive --l1 --src /root/KenshiFP/client --out /root/animlab-build/kfpvm_drive_fistl1
python3 $L/native.py fists --config $A/native.json "badpunch,ma chudan,ma 2strike,shoteiL" --adapter /root/animlab-build/kfpvm_drive_fistl1         --body vmrec-fist-z0-a.txt --body-frame 100 --out fists --visual $A/visual.json  # reach comp + HUD lift (spec U23)
```

**Trajectories** (`traj`/`adapt`/`run`): per sample the grip p, blade/hand f, edge/up u, both shoulders/elbows/wrists and
hand X axes, in FP camera numbers. `--stab torso` (default) re-expresses every frame in the chest bone at the start (lean,
twist, steps drop out: a weapon swing as seen from the head); `--stab pelvis` removes only the pelvis' ground travel
(steps, lunges) and keeps torso turns (martial-arts punches turn the torso ~90 deg; torso-stabilised they point sideways);
`--stab world` = a world-fixed camera. Framing `--anchor fit|ready|shoulder|none` (+ `--lift`, `--gain`) places the native
shoulder on the body recording's shoulder and turns the motion about it (see the docstring). `--target weapon` follows the
native prop bone; `--target hand` (fists, default without a weapon) applies the solver's prop convention to the native
hand (left hand = the drive's mirrored left grip, config `prop_mirror`) and, in `run`, first solves once to measure the
solver's wrist in its prop frame (`measure_grip`; KenshiFP class 0: -1.64, -0.46, -/+0.34 dm) so the SOLVED wrist lands on
the native wrist (with the skeleton's bind prop offset it was 1.7 dm off). Swing phases (wind-up top, stroke end) are found
from the tip path (`--phases` overrides) and mapped onto KenshiFP's swing u (0.28 / 0.58 / 0.78).

**run**: adapt -> metricslab drive -> report -> synthetic KenshiFP recording (`adapted.rec.txt`) -> `animlab.py` checks
(arc, churn, inline, hinge, blade, stroke; blade checks are INFO for fists) -> side-by-side video (native 3P | adapted FP).
A raw native clip is not an FP swing: expect FAILs (regress keeps it as an info row); it is the measuring tool.

**Keyed path** (`keyed_at`, `fit_keys`): Python port of KenshiFP `vm_swing_at` (start pose -> keys -> end pose,
non-uniform Catmull-Rom on p/f/u per component, zero tangent at the rest poses, `vm_pose_norm`). `fit_keys` picks key times
shared by all hands (coordinate descent over the dense samples) that best reproduce a dense path; values = the dense pose.

**fists** (NA1, unarmed): per technique, both hands: `--stab pelvis` trajectory with the calibrated grip -> profile model
(`fist_path`): a striking hand (wrist >= `strike_min` dm forward) keeps the native TIMING only: its extension e(t) along the
native strike direction drives the FP guard `fists.guard` -> strike point `fists.strike` (e < 0, pulled back = wind-up:
guard -> `chamber`, down/back, never toward the eye), native off-line motion kept at `res_scale` (clamp `res_max`); a
non-striking hand moves at `off_scale` (clamp `off_max`) about its guard; clamps y <= `y_max` (eye level), z >= `z_min`;
eases back onto the guard over the last `end_blend` -> hand frame (`fist_hand`): wrist STRAIGHT (hand X on the solved
forearm; the solver's natural 2-bone IK elbow, `elb=0`, does not depend on the hand frame, so one align solve is exact),
rolled so the palm (-hand Z: the mesh fingers curl that way) faces `palm_guard` blended to `palm_strike` by e (both palm
down, as the native stances / the native straight punch ma 2punchie), then flexed `flex_guard`/`flex_strike` deg (18/22)
toward the palm so the knuckles lead (the FP shoulders sit below the eye: a dead-straight hand stands up and the fixed
half-open fingers curl toward the camera = a palm-up reach, review 2026-10-10); `strikers` overrides the striking hands ->
`nkeys` shared keys fitted until the keyed path is within 0.8 x `path_err_max` -> the keyed path solved for both arms (fp_vm
sets `fists.sets`) -> checks: `guard_view` (both fists on screen at u <= .02 / >= .98), `strike_<side>` (the striking fist
reaches the view centre |x/z| <= .30, |y/z| <= .35), `eye` (forearm/fist >= 2.5 dm from the eye, never above eye level
+0.5 dm), `nearcut` (no on-screen forearm/fist point nearer than 3 dm), `wrist` (wb_max <= 30, PT30), `solver`
(metricslab limits), `reach` (solved wrist vs keyed target at the same clip time, p95 <= 0.35 dm), `keys` (keyed vs adapted
path p95 <= 0.5 dm), `churn_<side>` (animlab.py churn on a synthetic recording of each striking hand, swing window = start
-> strike peak, L mirrored onto the R slot; arc/inline/blade/stroke/hinge read a sword edge/blade or need >= 3 swings: INFO
lines in checks.txt). Why the profile model: the native unarmed clips are whole-body moves (90 deg torso turns, lunges) and
ma chudan / ma 2strike / shoteiL are palm-heel strikes with the wrist bent back ~100 deg on the native skeleton itself (hand X
vs forearm, ma chudan R 102, shoteiL L 110; badpunch R <= 23), so mapping the native path/hand gave 80-110 deg folds and
paths far off any FP punch. Shay 2026-10-10: palm techniques become straight-wrist punches; the game hand mesh has no finger
bones (fixed half-open hand), accepted, no closed-fist requirement. `spec.py unarmed` judges the hand frame: U19 knuckles lead at contact (hand
X <= 30 deg above the eye->wrist sight line, palm hidden from the camera, not up, not a palm heel), U20 guard palm
hidden, U21 arms never cross on screen (polylines intersect or a fist within 250 px of the other arm); U18 = closure INFO
(out of reach: no finger bones, the body mesh poses are face morphs). `--visual <visual.json>` loads the prop convention.
Outputs per technique: checks.txt (`RESULT fist-<anim> PASS|FAIL ...`), keys.json, report.txt, check_<side>.rec.txt,
sheet-z0.png (lab FP render, both arms, crosshair = screen centre) and sheet-z25.png (what the game shows zoomed out: the
viewmodel fades out beyond zf1 = 8 dm, so the native third-person clip, camera 25 dm from the eye orbited 60 deg to the side),
both full-resolution 800x450 tiles; all techniques: `fist_keys.inc` (C tables `g_vm_fist_guard[2]`, `g_vm_fist_u_<anim>[]`,
`g_vm_fist_<anim>[2][n]`, VP format, L rows in the drive's --side L convention). Config: `native.json` `fists` (defaults
`FIST_DEFAULTS` in native.py). The FP body is the sword-ready recording until an unarmed body recording exists.

**Catalogue** (`catalog`): the FCS game data (gamedata.base + mods, v16 and v17 headers) -> COMBAT_TECHNIQUE records per weapon
category (anim name, length, speed mult, attack/block/dodge, arms, skill range), combat stances, unreferenced clips.

**Config** (KenshiFP `components/KenshiFP/animlab/native.json`): game_dir, skeleton, body_meshes, game_data, head_bone,
eye_from_head, bones per side, prop_axes / prop_local_q / prop_roll_deg / prop_mirror (= visual.json), weapons {mesh, bone,
class, blade, hands}, default_weapon per category, fov_3p, fists.

Limits: no game blending/layering (upper/lower body layers, blend-in, anim speed x skill factor), no IK foot placement, the
FP body is a recorded frame (sword-ready torso for fists until an unarmed body recording exists), the drive applies poses
directly (no target springs).

## Regression
`regress.sh` step P4: `tests/animlab/test_native.py` (synthetic skeleton + animation chunks: reader, interpolation, pose
sampling, pelvis stabilisation, left mirror, grip offset, keyed path, key fit, FCS v17) and, with the game install, list /
catalog / run / fists complete. Phase 4 is tagged `animlab-p4`.

## Spec and taste (spec-first rules, scoring the lab against Shay's decisions)
`tools/animlab/spec.py`: `map <rules.tsv> [--md]` (rule -> check map), `run <rules.tsv> --checks <checks.json> --class C <rec>...`
(every rule of a class on a recording), `unarmed <candidate dir>... [--rules]` (NA1 unarmed spec on fist candidates' pose.txt:
guard view, return to guard, moves, strike to centre, eye clear, wind-up below eye, near-plane cut, wrist <= 30, churn, arm-driven,
fist roll, ikfail, palm-heel = straight-wrist punch), and new recording checks `restedge` (S1: sword edge cos p05 >= 0 in
ready/block), `stilljit` (X1: aim jit_p95 <= 1.5 px), `wrist` (holds <= 30, swings <= 50).
`tools/animlab/taste.py score <taste.tsv> --rules --checks --root <corpus>`: runs each labelled item's rule checks and prints the
confusion per rule (TP rejected+FAIL, TN accepted+PASS, FN lab missed, FP false alarm), `DISAGREE` lines and
`RESULT taste PASS|FAIL items= agree=(weighted)`. File formats in the script headers. KenshiFP data + one-command rerun:
`components/KenshiFP/animlab/taste/run.sh` (workspace). Unit tests `tests/animlab/test_spec.py`.

## Feedback loop: corpus, per-build gate, mutations, backfill, ledger, take preflight (animlab-loop)
Scripts live in KenshiModding `components/KenshiFP/animlab/` (run in WSL); each has a usage header.
- **Corpus** `corpus.sh add|row|verify|sync|stats|files`: the protected evidence corpus `C:\KenshiTestRuns\corpus`
  (never cleaned; MANIFEST.tsv = name kind check expect build source status notes, SHA256SUMS). Every check keeps a FAIL
  and a PASS recording ("pair"); `pending` rows name material still to record. Before deleting a run dir, `corpus.sh add`
  any recording a check or Misses row uses. `regress.sh` syncs its work dir from the corpus.
- **Gate** `gate.sh [--update-baseline] [--no-mutate]` (~3 min, offline): corpus verify + regress on an empty work dir
  + E6 swing pool + mutation tests + flips vs `corpus/gate-baseline.tsv`; one `RESULT ANIMLAB-REGRESS PASS|FAIL ...` line,
  cached per source/lab/manifest hash in `/root/animlab-gate/`. Runs on every KenshiFP viewmodel build before VMQUICK
  (fp-viewmodel.sh `vmq_gate`). After a lab-check commit: run it, read the flips, then `--update-baseline`.
  E6 coverage steps (2026-10-11): the pool runs `--checks arc,blade,stroke,churn,inline` per stroke and records two verdicts,
  `POOL stroke s` (arc/blade/stroke/churn) and `POOL-INLINE stroke s` (the take judge's inline; RESULT field `pinl=`);
  3b `stroke-cycle.py --adapter <kfpvm> --src <client>` replays a corpus sword rec UNFORCED per weapon class
  (`corpus/pools/stroke-cycle/classes.tsv`: class wcat wpom wtip expect) and FAILs a class whose picked strokes miss
  the source's default mask (or the listed set): a FAIL fails the gate (`cycle=`); 3c `e6-takes.py --adapter <kfpvm>
  [--args "--tables f"]` replays every corpus E6 game take (`corpus/pools/e6-takes/takes.list`) with the candidate source
  and judges each take x stroke inline + arc like fp-e6-strokes.sh (`E6TAKE <rec> s<n> <check>` verdicts, baseline-judged,
  `e6takes=<n>/<fail>`). Both run standalone on any adapter build (build.sh --src <tarball client>) to vet a candidate.
- **Mutations** `mutate.py --work <gate work dir>`: synthetic corruptions of known-good corpus material (recording edits,
  video overlays); each check must FAIL its own kind. Known gaps (no check yet) in `corpus/mutations-known.tsv`; a gap is a
  Misses row for the maintainer, not a gate FAIL.
- **Backfill** `backfill.sh <rec|video> <name> '<cmd with {}>'`: a new/changed check run once over all corpus material;
  SKIP when the check does not apply (BF_NA: n/a, no swing, no block, band_frames=0 ...); `new=` lists FAILs on material
  with no expected-FAIL manifest row for that check = lab finds on old material (check by eye, then Misses row or manifest row).
- **Ledger** `ledger.py`: rewrites the "Catch-rate ledger" table in STATUS.md (who found each flaw first per build and class).
- **Setup misses** `SETUP_MISSES.md`: take/setup failures; each maps to a check in the shared take preflight
  `components/KenshiFP/tests/ingame/take-preflight.sh` (pf_begin RESULT guard, pf_outdir, pf_rig incl. the 4080
  rig_preflight, pf_display, pf_day, pf_clean, pf_area, pf_weapon, pf_open with cursor + min luma; `pf_all` = all in order).
- **Review verdicts**: `tools/automation/review-verdict.ps1 ... FAIL|REJECT-SHEET` appends a PENDING Misses row automatically.

## Reference motion (mocap)

`tools/animlab/mocapref.py` reads openly licensed human motion capture (CMU ASF/AMC, BVH) and measures it the way the
lab measures a viewmodel: the clip is torso-stabilised (as the fixed FP camera sees the arms), its weapon-side shoulder
placed on the FP body's shoulder and scaled to the FP arm length (`--body <rec>`), then strikes / kicks / aim holds /
two-hand swings are found and measured: phase timing and shares, peak wrist speed (arm lengths/s), wrist path, elbow
angles + opening, reach, wrist bend (start / max / added), wrist share at a fixed 0.15-arm lever (U10 formula),
forearm roll per 33 ms (swing-twist of the hand in the forearm frame), torso share + chest yaw, two-hand spacing,
kick head/wrist travel, aim-hold reach/elbows/jitter/raise time. `strike_rows(V, ...)` takes any view dict, so the same
code measures a solved KenshiFP path. No motion data in this repo (it is fetched by the KenshiFP workspace).
```
python3 -I $L/mocapref.py info <clip.amc|clip.bvh> [--asf subj.asf]
python3 -I $L/mocapref.py measure <clip> --kind strike|kick|hold|twohand --side R|L --body vmrec-q-sword-z0-a.txt [--json o.json]
```
KenshiFP comparison (workspace `components/KenshiFP/animlab/reference/`: `sources.tsv` clips + licenses, `fetch.sh <dir>`
downloads each source into its own new dir, `compare.py --data <dir> --tables <fp_tables dump> --out <dir>` solves the
live tables through the drive adapter and writes REFERENCE.md + `REF <family> <metric> ... OK|DEVIATES` lines; run via
labnice.sh). Limits: mocap hands have no weapon (blade direction is not measured; CMU hand/thumb axes are noisy, roll
spikes > 120 deg/33 ms dropped as flips), the reference performers mime (casual swordplay, acted slashes), the drive applies
poses without the game's target smoothing. Tests: `tests/animlab/test_mocapref.py`.
