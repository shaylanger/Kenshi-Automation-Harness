# Animation lab: status (durable state)

Owner: animation-lab builder agent (ordered by Shay, 2026-10-09). This file + git are the
ONLY state (no temp handoffs). Update, commit and push at every milestone.
Builders #1-#3 stopped (context limit); builder #4 finished P2 + started P3; builder #5 finished P3, then the phase-2 open points.

## Goal
An offline animation lab for Kenshi first-person viewmodels, built in 3 phases (all required):
1. **REPLAY** (urgent): feed recorded per-frame data from the game (KenshiFP `rec` recordings from
   fp-viewmodel.sh / VMQUICK) into the REAL KenshiFP viewmodel solver (kfp_viewmodel.inc), compiled
   offline (gcc in WSL), and print the in-game vmcheck metrics per state (wrist bend, elbow,
   stretch, edge-to-camera cos, jitter p95 px); variants (tunable overrides + patched source) run
   in parallel. Faithfulness gate: >= 2 recordings reproduce in-game values within a stated
   tolerance (sword-z0 swing + crossbow-z0 incl. reload, or explain why reload is excluded).
2. **METRICS LAB**: author new motions (time-keyed hand/weapon targets, JSON) on Kenshi's real
   skeleton through the solver; same metrics + reach limits + weapon/weapon and weapon/camera
   intersection. Example use: dual wielding (`C:\KenshiModding\DUAL_WIELDING_MOD_IMPLEMENTATION_BRIEF.md`).
3. **VISUAL LAB**: render arms + weapon meshes (Ogre mesh/skeleton read from the game install at
   runtime, never committed) to frames/MP4 offline; validated side-by-side vs a real game frame.
Phase 1 stays frozen and working while 2/3 are built: separate modules/entry points, phase-1
regression tests run before every commit.

## Rules
- Public harness repo (`tools/animlab/`, `docs/animlab/`, `tests/animlab/`): generic code only. No
  KenshiFP source, no recordings, no binaries, no game assets.
- Workspace repo `C:\KenshiModding\components\KenshiFP\animlab\`: the KenshiFP solver adapter
  compiled against a read-only COPY of `/root/KenshiFP/client` (`/root/animlab-kfp-src`, rsync).
- Never edit /root/KenshiFP; never use the 5090 game (fixer owns it); 4080 only after asking "main".
  Don't modify C:\KenshiTestRuns (copy recordings out).
- Identity shaylanger <shaylanger2@gmail.com>, one feature per commit, push after each,
  "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>".

## Phase plan / current phase
- [x] P1 replay: DONE, frozen. Tag `animlab-p1` (harness 93b766e, workspace 36c162c). Later harness commit f0f0c4b
  (another agent: aim label/moves gate) changed the crossbow gate frame count 1380 -> 1355, still PASS.
- [x] P2 metrics lab: DONE (builder #4): `tools/animlab/metricslab.py`, adapter `kfpvm_drive.c` (`build.sh --drive`),
  example `components/KenshiFP/animlab/motions/dualwield-alternate.json`, tests `tests/animlab/test_metricslab.py`,
  USAGE.md "Phase 2", regress.sh steps 4-6. Tag `animlab-p2`.
- [x] P3 visual lab: DONE (builders #4 + #5): harness `tools/animlab/visual/ogre.py` (Ogre .mesh v1.100 / .skeleton
  v1.80 reader; skeleton bone chunk size excludes the name string), `visual/render.py` (`still|frames|compare`, MP4 via
  ffmpeg, `--weapons R,L`), tests `tests/animlab/test_visual.py` (8, synthetic binaries), USAGE.md "Phase 3", regress.sh
  steps 7-8; workspace `components/KenshiFP/animlab/visual.json` (prop_roll_deg 60 = g_vm_groll, prop_mirror L = adapter left grip,
  quat x,y negated + roll 180 - groll). Tag `animlab-p3`.

## Components
- Adapter `kfpvm_replay <rec> <out> [--calib L1R,L2R,L1L,L2L,K] [--set k=v] [--set-at f:k=v] [--cold] [--quiet]`
  compiles the REAL kfp_viewmodel.inc with prelude stubs + quat helpers extracted from
  kenshifp_client.c, a fake Ogre skeleton (Bip01 spine/neck/head/clav/UA/FA/hand/prop,
  parent-derived transforms), world = skeleton space, virtual QPC clock = recorded dt, fake character
  (wih/class via vtable 0x3D0); drives vm_frame + hooked_vm_setanim per record; output written by the
  plugin's own vm_rec_dump (same format). 600 frames in 0.13 s.
  Build: `bash /mnt/c/KenshiModding/components/KenshiFP/animlab/build.sh --rev 6c9516b --out /root/animlab-build/kfpvm_6c9516b`
  (`--rev` = KenshiModding git rev of components/KenshiFP/client; `--sync`/`--src` = live copy;
  `--patch x.py|x.patch` = variants).
- Harness CLI `python3 tools/animlab/animlab.py metrics|compare|replay|sweep|gate` (sweep runs variants
  in parallel and passes base calib to variants). DEFAULT_TOL in animlab.py.
- Rec format + vmcheck metrics reference: `components/KenshiFP/tests/ingame/fp-viewmodel.sh` lines
  53-230 (embedded vmcheck.py).

- P2: `metricslab.py run|sample|fromrec|faithful|report` + drive adapter `kfpvm_drive <body_rec> <frames> <out> --body-frame N
  [--side R|L] [--calib ..] [--set k=v] [--no-lookahead] [--quiet]` (`build.sh --drive`); usage in USAGE.md "Phase 2".

## WSL scratch (not git, may be lost; rebuildable)
`/root/animlab-kfp-src` (rsync copy), `/root/animlab-src-archive/e80aa2a5` (source at DLL e80aa2a5),
`/root/animlab-build/` (binaries), `/root/animlab-work/` (copied recordings + sims).

## Results
P1 gate (recordings `C:\KenshiTestRunsmq-f8c`, made right after workspace commit 6c9516b = DLL 419D164F, replayed
with source 6c9516b): sword-z0-a PASS 556 fr; crossbow-z0 PASS (ready+aim); sword-z0 swings/reload info only (native
pose not recorded before the rec-native patch); X1 crossbow jitter NOT reproduced offline (replay jit ~0.4 vs game ~1.7).
SOLVED (builder #5): the drive had no elbow warm start; 6c9516b has no S2 re-seed, so its elbow branch depends on history and a cold drive
picked the right-hand branch (elbow 6.05,-1.90 vs game 1.63,-4.53). kfpvm_drive now seeds g_vm_elbe from the body record
(--cold-elbow = old behaviour): sword drive @6c9516b PASS (elbow95 0.046 = current). Original note: P2 drive gate: crossbow-z0 345-1097 @6c9516b PASS (elbow95 0.07); sword-z0-a 83-232 @current PASS (elbow95 0.05), FAILS
@6c9516b (wrist95 1.1, elbow95 5.2) = open question, not investigated (that build's frozen-replay path vs sword wrist
roll; current source fine). Dual-wield example PASS (R wb_max 13, L wb_max 24: L/R asymmetry in the windup/cut on a
mirrored motion, worth a look by the FP fixer if dual wield goes ahead; ww_min 0.22 dm).
P3 visual validation (game frames C:\KenshiTestRuns\opt e-flatA / e-h90 / e-h-90, copies in /root/animlab-work/p3): hand X
err 0.3 / 0.5 / 0.4 deg, rendered blade outline on the game blade (curved tip matched in e-h-90), arm outline around the
gauntlet. MP4s: /root/animlab-work/p3/sword-z0-replay.mp4 (702 fr, 34 s render), dualwield-alternate.mp4 (145 fr; L hand
X err 0.0 deg with prop_mirror, 98 deg without). Frames 499+ of sword-z0 render black = holster (arms out of view).
Asymmetry SOLVED (builder #5): (1) adapter bug: the left grip mirror missed a 180 deg roll about the blade and the grip
roll sign (fixed: groll_L = 180 - groll, kfpvm_drive.c); (2) solver: 3 right-hand-only rules in the melee elbow pick
(variant patch patches/left-hand-mirror.py, not in the game); (3) the ready stance twists the torso (frame 100: R
shoulder 1.1 dm back), so camera-mirrored != body-mirrored. With (1)+(2) the sync mirror motion on a symmetric body
gives L == R exactly (regress step 9); dualwield-alternate now L wb_max 14.9 vs R 13.0 (was 24.1).
Also: the source copy /root/animlab-kfp-src was re-synced at 19:03 (new vm_bolt_measure): prelude.h got stubs for
g_ent_getvisible and the node setters; the current-source sword drive gate still PASSES.

## Misses (game found, lab missed)
Standing order (Shay via coordinator, 2026-10-09): every miss gets a lab check that FAILS on the recording that showed
it (and passes on the fixed build where one exists), or a written reason it is out of reach. The FP fixer appends rows.
Format: date | point | what the game showed | recording path | build | status
- 2026-10-09 | C1 aim | aim pose did not play in background: the combat layer read only real keys, the viewmodel read harness input | none (input layer) | - | open: outside the solver; lab can assert every expected state appears and moves
- 2026-10-09 | X1 crossbow jitter | game jitter p95 5-6 px vs replay ~0: bone-world map quantised at the floating origin (fixed in game by the node map, e948f86) | C:\KenshiTestRuns\vmq-f8c\vmrec-q-crossbow-z0.txt | 419D164F (6c9516b) | CLOSED (lab): `animlab.py compare` jitter line (game jit_p95 > 1 px at most 2.5x the replay, swings skipped), regress step 12: crossbow-z0 vs its 6c9516b replay FAIL (ready 1.74/0.42 x4.2, reload 2.73/0.41 x6.6); f14/xb0 (node map) vs the current solver PASS (ready x2.3, close to the limit; f13/sw0 without build stamp x2.5). The quantised-map mode (kfpvm_replay --abs-world: absolute float32 world, game magnitudes ~54100) does NOT reproduce it: float32 ulp ~0.004 units, far below a pixel; --bw-lag overshoots ready (7.3) -> the game mechanism is not modelled, only detected
- 2026-10-09 | jitter under-reported | lab jitter generally below the game's | vmq-f8c recordings | 419D164F | CLOSED with X1: the compare jitter line flags any state where the game is noisier than the replay (detects, does not model)
- 2026-10-09 | sword elbow branch drift | elbow switches branch on long replays/drives (e.g. drive @6c9516b sword-z0-a 83-232: elbow on the right branch, game low; no S2 re-seed + no elbow warm start in the drive) | C:\KenshiTestRuns\vmq-f8c\vmrec-q-sword-z0-a.txt | 419D164F (6c9516b) | partly: branch history dependence reproduced by check regress step 10 (cold drive @6c9516b elbow95 5.16 vs seeded 0.05); drift over long replays itself still open
- 2026-10-09 | E1 edge leads | game swing led with the back of the blade (edge_arc -0.9 in the main stroke) | C:\KenshiTestRuns\f14\e0.txt | build Oct 9 18:21:44 | CLOSED (lab): `animlab.py metrics` arc gate (stroke frames after the wind-up u>=0.28: edge_arc>=0.7 on >=85%, swing wb_max<=30), regress step 11: game e0 arc_ok 0.50 FAIL, current solver replay 0.56 FAIL. Patch pending-fixes/kfp-e1-swlead.py: arc_ok 1.00 but wb_max 107 (the lead comes from fading the PT17 wfix roll = wrist fold); sweep with components/KenshiFP/animlab/patches/e1-lead-variants.py (e1wfix 0..1, e1clamp, edgeclamp, swlse/swlin/swlout): no variant has arc_ok>=0.85 with wb<=30 (e1wfix 0: wb 27 but arc 0.56). The lead roll must come from the forearm, not the wrist. Root cause (lab): straight-wrist edge sits ~-70 deg from the forearm projection about the blade, the strike velocity at +110..170 deg (keys sweep the blade along its length). CANDIDATE (sent to fixer + main): pending-fixes/kfp-e1-keys.py = kfp-e1-swlead.py + kfp-e1-rollcap.py (lead roll <= e1cap 50 deg off the straight wrist) + re-authored strike keys sw2..sw4 (found by components/KenshiFP/animlab/e1-climb.py, e1-mkpatch.py): arc_ok 1.00/1.00/0.97 on e0/f13-sw0/vmq sword-z0, wb_max 47.9/48.5/47.6 (current 50.7/53.2/63.7), elb_h_max <= 0.89; regress step 11 requires it. Video /root/animlab-work/e1/e1-compare.mp4. Rejected: kfp-e1-elbfollow.py (elbow follows the rolled hand: worse, the off-screen elbow pass rules block it)
- 2026-10-09 | C2 stock height / C3 bolt jitter on walk | bolt is a separate node, not in the lab's skeleton | tbd | - | C3 PARTLY (lab): `animlab.py bolt <rec>` reads the game sidecar <rec>.bolt (since ~18:55 builds): bolt origin in the weapon frame within 0.1 dm of its median, step <= 0.05 dm; regress step 13: f16/c3a FAIL (ready dev95 0.82 step95 0.63). Every f16 recording up to c2b44 (build 19:24) FAILs (dev95 0.43-0.92): no passing build yet; told the fixer. Game-only (the lab skeleton has no bolt node). C2 stock height: fixer has f16/c2.py (stock top <= 25% screen); not yet a lab check

## Key findings / gotchas
- Camera numbers are a MIRRORED frame (rt = fw x up): recorded hand axes mh/hy/hz are left-handed
  there. Use dot products for hand-local coords; c2w() maps back to a right-handed world.
- Calib K (hand derived scale * skel scale for the prop offset) ~1.05; L1 2.79, L2 3.18 dm.
- frame_core resets all state when skel != g_vm_skel: warm_start() sets g_vm_skel first. Warm start
  inits cur/w/phase/oc/elbe from record 0.
- Measured fields in record i+1 = what apply i rendered. `napply` (group 3 field 3) increments 0 or 1
  per frame (sword-z0: 182 of 702 frames without an apply; crossbow 235/2504). Replay must apply only
  when it increments (else the skeleton keeps the last pose).
- Recordings lack build id + live `fp_vm set` overrides: planned KenshiFP patch (pending-fixes script,
  coordinator applies): vm_set logs each set with frame index; vm_rec_dump writes `# build ...` and
  `# set <frame> <key> <value>` lines (recfmt keeps `#` lines in Rec.meta; adapter applies via --set-at).
- Useful for P3: /root/KenshiFP/client/kfp_meshray.h parses Ogre .mesh triangles (read-only reference).

## Next steps
1. Standing lab maintainer (coordinator order 2026-10-09): work through "Misses" (a failing check per miss or a reason),
   report one line per closed miss to main. Both P2 open points are solved (see Results).
   Order (maintainer #6 resume list, from builder #5 handoff):
   a. (DONE, see Misses E1) E1: metrics.py has per-frame `arc` (edge_arc = cos(mu, mid-blade velocity perp. to blade), melee, speed > 8 dm/s)
      and per-state arc_ok (share >= 0.7), arc_p05, arc_n. `animlab.py metrics f14-e0.txt` (copy
      /root/animlab-work/f14-e0.txt of C:\KenshiTestRuns\f14\e0.txt): swing arc_ok 0.42 arc_p05 -1.00 = reproduces E1.
      Add a gate that FAILS on it, then variant build with pending-fixes/kfp-e1-swlead.py:
      `build.sh --src /root/animlab-kfp-src/client --patch /mnt/c/KenshiModding/pending-fixes/kfp-e1-swlead.py --out /root/animlab-build/kfpvm_e1`,
      replay e0 with both adapters; base replay should reproduce the game's arc; patched should pass.
   b. C1 (moves FAIL aim:MISSING on f13/x3.txt, f14/xb0.txt, xb0b.txt: game st never 'aim'; asked fixer if C1 or unloaded
      setup; need a PASS recording on a fixed build to close): check exists (metrics moves_ok, `moves PASS` line); needs a recording where aim stayed in ready, else
      "reproduced by check moves (no recording)".
   c. (DONE, see Misses X1) X1 jitter: optional quantised bone-world map mode in kfpvm_replay (floating-origin grid) vs game 5-6 px on Step 12 PASS half pinned to rev d40b6ad (the live source replay jitter drifts).
      vmq-f8c crossbow-z0; same for general jitter under-report.
   d. (C3 check DONE, see Misses) C2: port f16/c2.py (stock height from mp/mf/mu) into metrics as a gate. C3: add a PASS case once a fixed build records. Old note: C2/C3 bolt:
   e. Sword elbow drift on long replays.
   Not yet sent to main: "P2 open points solved: L/R mirror exact (adapter groll 180-g + patches/left-hand-mirror.py),
   sword drive @6c9516b PASS via elbow seed".
   Gotchas: /root/animlab-kfp-src may be re-synced by others (new globals -> stubs in prelude.h); stdin readers in WSL
   heredocs (ffmpeg needs -nostdin); untracked *.obj/vc100.pdb are not ours.

## How to resume
Read this file, `git log -- tools/animlab docs/animlab tests/animlab` in the harness repo and
`git log -- components/KenshiFP/animlab` in C:\KenshiModding. Run regress.sh (must be ALL PASS). Continue at "Next steps".
Gotchas: Git Bash: MSYS_NO_PATHCONV=1 + `wsl.exe ... -- bash -s <<'EOF'` heredocs (wsl.exe expands `$VAR` in -c args);
never run Windows `python` (hangs). Other agents (sword fixer) commit to tools/animlab too: commit only your files.
