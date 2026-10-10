# Animation lab: status (durable state)

Owner: animation-lab builder agent (ordered by Shay, 2026-10-09). This file + git are the
ONLY state (no temp handoffs). Update, commit and push at every milestone.
Builders #1-#3 stopped (context limit); builder #4 finished P2 + started P3; builder #5 finished P3, then the phase-2 open points; maintainers #6-#7 work the Misses list.

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
P1 gate (recordings `C:\KenshiTestRuns\vmq-f8c`, made right after workspace commit 6c9516b = DLL 419D164F, replayed
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
- 2026-10-09 | C1 aim | aim pose did not play in background: the combat layer read only real keys, the viewmodel read harness input | C:\KenshiTestRuns\f14\xb0.txt (pre-fix) | pass: vmq-125c crossbow-z0 (build Oct 9 19:32:36) | CLOSED (lab): `animlab.py metrics` moves line, regress step 14: f14/xb0 FAIL aim:MISSING (also f13/x3, xb0b), vmq-125c crossbow-z0 PASS aim 6.2dm/23deg (vmq-cbaf 19:15, vmq-f804 19:24 also PASS). The input-layer cause itself is outside the solver; the lab detects the missing state
- 2026-10-09 | X1 crossbow jitter | game jitter p95 5-6 px vs replay ~0: bone-world map quantised at the floating origin (fixed in game by the node map, e948f86) | C:\KenshiTestRuns\vmq-f8c\vmrec-q-crossbow-z0.txt | 419D164F (6c9516b) | CLOSED (lab): `animlab.py compare` jitter line (game jit_p95 > 1 px at most 2.5x the replay, swings skipped), regress step 12: crossbow-z0 vs its 6c9516b replay FAIL (ready 1.74/0.42 x4.2, reload 2.73/0.41 x6.6); f14/xb0 (node map) vs the current solver PASS (ready x2.3, close to the limit; f13/sw0 without build stamp x2.5). The quantised-map mode (kfpvm_replay --abs-world: absolute float32 world, game magnitudes ~54100) does NOT reproduce it: float32 ulp ~0.004 units, far below a pixel; --bw-lag overshoots ready (7.3) -> the game mechanism is not modelled, only detected
- 2026-10-09 | jitter under-reported | lab jitter generally below the game's | vmq-f8c recordings | 419D164F | CLOSED with X1: the compare jitter line flags any state where the game is noisier than the replay (detects, does not model)
- 2026-10-09 | sword elbow branch drift | elbow switches branch on long replays/drives (e.g. drive @6c9516b sword-z0-a 83-232: elbow on the right branch, game low; no S2 re-seed + no elbow warm start in the drive) | C:\KenshiTestRuns\vmq-f8c\vmrec-q-sword-z0-a.txt | 419D164F (6c9516b) | CLOSED (lab): branch history dependence reproduced by check regress step 10 (cold drive @6c9516b elbow95 5.16 vs seeded 0.05). Drift (maintainer 7): long REPLAYS do not drift (sword-z0 full replay @6c9516b ready elb95 0.23); long DRIVES did, because `metricslab.py faithful` targeted the RENDERED pose: the rendered swing tail differs from the commanded one, the drive elbow stays at x~2 while the game elbow moves out to x~4.4 (frames 90-98), then sits on the other branch for the rest of the recording (elb 5.2 dm). New `faithful --commanded` drives the commanded pose (what the game solver got) and tracks the game through every swing. Regress step 16: sword-z0 0-520 @6c9516b rendered FAIL elbow95 5.15, commanded PASS 0.16. (Passing the recorded ui state/ti/swing flag into the drive did not help: tried, reverted.)
- 2026-10-09 | E1 edge leads | game swing led with the back of the blade (edge_arc -0.9 in the main stroke) | C:\KenshiTestRuns\f14\e0.txt | build Oct 9 18:21:44 | CLOSED (lab): `animlab.py metrics` arc gate (stroke frames after the wind-up u>=0.28: edge_arc>=0.7 on >=85%, swing wb_max<=30), regress step 11: game e0 arc_ok 0.50 FAIL, current solver replay 0.56 FAIL. Patch pending-fixes/kfp-e1-swlead.py: arc_ok 1.00 but wb_max 107 (the lead comes from fading the PT17 wfix roll = wrist fold); sweep with components/KenshiFP/animlab/patches/e1-lead-variants.py (e1wfix 0..1, e1clamp, edgeclamp, swlse/swlin/swlout): no variant has arc_ok>=0.85 with wb<=30 (e1wfix 0: wb 27 but arc 0.56). The lead roll must come from the forearm, not the wrist. Root cause (lab): straight-wrist edge sits ~-70 deg from the forearm projection about the blade, the strike velocity at +110..170 deg (keys sweep the blade along its length). CANDIDATE (sent to fixer + main): pending-fixes/kfp-e1-keys.py = kfp-e1-swlead.py + kfp-e1-rollcap.py (lead roll <= e1cap 50 deg off the straight wrist) + re-authored strike keys sw2..sw4 (found by components/KenshiFP/animlab/e1-climb.py, e1-mkpatch.py): arc_ok 1.00/1.00/0.97 on e0/f13-sw0/vmq sword-z0, wb_max 47.9/48.5/47.6 (current 50.7/53.2/63.7), elb_h_max <= 0.89; regress step 11 requires it. Video /root/animlab-work/e1/e1-compare.mp4. Rejected: kfp-e1-elbfollow.py (elbow follows the rolled hand: worse, the off-screen elbow pass rules block it)
- 2026-10-09 | C2 stock height | stock top high on screen; first fix (18:21 c2c) rotated the crossbow 24.5 deg (Shay) | C:\KenshiTestRuns\f16\c2a.txt, c2c.txt | build Oct 9 18:21:44 | CLOSED (lab): `animlab.py stock` (stock top line mp - k*mf + 1.45*mu, p95 <= 25% from the bottom in ready; --ref: ready fwd/up within 3 deg of f14/xb0 = d40b6ad-era pose), regress step 15: c2a FAIL 67%, c2c FAIL ori 24.5 deg, vmq-125c crossbow-z0 (19:32) PASS 15%/0.0 deg. Same numbers as the fixer's f16/c2.py + c2ori.py
- 2026-10-09 | C3 bolt jitter on walk | bolt + strings hang under a gun node the game sets to the native (pre-IK) Prop2 pose; fixed by kfp-c3-boltpin.py (node set to the post-IK Prop2 pose at the end of vm_apply) | C:\KenshiTestRuns\f16\r0.txt (pin off) | KenshiFP F8041381 | CLOSED (lab): `animlab.py bolt` now reads .bolt column group 5 (sl = bolt in the post-IK Prop2 frame; group 1 bl uses mp, measured at another time = false drift, only a fallback for old sidecars, `--source`), regress step 13: r0 FAIL dev95 0.52, r1 (pin on) PASS 0.000. Earlier "all f16 FAIL" results were bl false drift

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
1. Standing lab maintainer (#7 since 2026-10-09; #6 handoff copied here): work through "Misses" (a failing check per miss
   or a reason), one line to main per closed miss. Done: E1, X1, jitter under-report, C3 check (no pass case yet).
   Left, in order:
   a. (DONE) C1: `moves FAIL aim:MISSING` on f13/x3, f14/xb0, xb0b predate the C1 fix (fp_combat input path): pass case = a
      post-fix crossbow recording (newest vmq-* / f16); add a regress pair (fail old, pass new) and close.
   b. (DONE) C3: bolt reads group 5, r0 FAIL / r1 PASS (regress 13).
   c. (DONE) C2: gate in metrics: stock top <= 25% from the screen bottom (port C:\KenshiTestRuns\f16\c2.py, mp/mf/mu) AND
      crossbow orientation within ~3 deg of the d40b6ad-era pose (Shay: C2 rotated the crossbow); fail on an f16 c2 rec.
   d. (DONE) Sword elbow drift: faithful --commanded (regress step 16).
   TOP (main 2026-10-09, Shay rejected e1-compare.mp4): kfp-e1-keys candidate wind-up (source frames ~12-22) swings
      the forearm far out right (elbow off-screen) and back while the sword barely moves. (1) new check "arm churn":
      (a) elbow + forearm-mid screen path / grip+tip screen path over ~0.15 s windows, threshold calibrated on game vmq
      sword-z0 ready/swing/block; (b) elbow screen-x out-and-back > X within 0.4 s while grip moves < Y; (c) print the
      worst window. Regress step: FAIL on current candidate, PASS on the fix. Run it on game recordings too (vmq sword,
      f14/e0). (2) render.py review sheet: every Nth frame, elbow + grip trails, churn frames boxed red. (3) fix the
      candidate (elbow side continuous through the wind-up), keep arc/wb. Re-render e1-compare.mp4 + sheet, message main
      numbers + paths; send the patch to the fixer only after arc + wb + churn pass.
   CHURN STATE (maintainer #8 since 2026-10-09, #7 handoff copied here): `animlab.py churn` (metrics.py churn_series/
      churn_check/_twist/_forearm_vis) COMMITTED with unit test test_churn_check + regress step 17 (game vmq-f8c sword-z0
      PASS, candidate kfp-e1-keys on f14-e0 FAIL rev+roll). Coordinator decision (2026-10-09): keep the wind-up roll gate
      (~15 deg) for the fix; the current game swing failing it is expected (part of what is being fixed). Fix needs ALL:
      arc (>= 0.7 on >= 85% of fast stroke frames, may gate stroke + follow-through only), wb <= ~50, churn rev <= 450,
      windup_roll <= 15. Patch = pending-fixes/kfp-e1-*.py (never /root/KenshiFP). Send to the fixer (now agent
      a6b11f2fff651d5bf) only after main confirms Shay is OK with the video. Edit tip: python edit scripts via WSL
      python3 (Bash heredocs mangle backslashes; Git Bash sed corrupts Windows paths).
      Shay add-on (via main): NO hand roll in the wind-up (roll change <= ~10 deg), small gradual roll at stroke start;
      gate (d) total wind-up roll about the forearm > ~15 deg FAILs; arc may be gated on stroke + follow-through only.
      Measured with `animlab.py churn` (rev = visible forearm end out-and-back px within 0.4 s with grip extent <= 250 px,
      gate 450; windup_roll = swing-twist of the weapon-frame rotation about the forearm axis, gate 15):
      game f14-e0 rev 276 roll 67.9 | f13-sw0 393 / 13.7 | vmq-f8c sword-z0 98 / 10.1 | vmq-f804 sword-z0 233 / 66.0 |
      replays current solver e0 194 / 77.0, sw0 186 / 46.7 | E1 candidate kfp-e1-keys e0 556 / 159.2, sw0 545 / 144.7.
      => rev 450 separates candidate from game/base; the CURRENT game swing already rolls 46-77 deg in the wind-up (the
      PT17 wfix roll), so roll<=15 fails game + base too: report that to main (it is what Shay asks to remove).
      ratio (a) is info only: game ready frames reach 8.7 (elbow off screen moves with the weapon still), not separable.
      Next: unit test + regress step (candidate FAIL rev+roll; fixed variant PASS), variant patch: lead weight 0 for
      u < g_vm_swk_u[1] (swlin ramp from the wind-up end) + wfix roll held at its ready value through the wind-up, then
      arc (stroke) / wb / churn on f14-e0 + f13-sw0; render.py review sheet (every Nth frame, elbow+grip trails, churn
      frames boxed red); re-render C:\KenshiTestRuns\animlab\e1-compare.mp4 (old: /root/animlab-work/e1/fr-e1base,
      fr-e1k = 190 frames of f14-e0 swing 1) + sheet; message main; patch to fixer only after arc+wb+churn pass.
      Scratch scripts: C:\Users\Shay\AppData\Local\Temp\claude\C--KenshiModding\al7 (churn*.py, runchurn.sh).
   e. New Misses rows from the fixer (agent a6b11f2fff651d5bf, was a7ff9f30a50ed26e7) in order.
   Not yet sent to main: "C3 partly: check animlab.py bolt, f16/c3a FAIL dev95 0.82; no passing build yet".
   Gotchas: /root/animlab-kfp-src is re-synced by the fixer (kfpvm_cur drifts: pin checks with build.sh --rev; new
   globals -> stubs in prelude.h); never Windows python (edit via WSL python scripts; Git Bash /tmp != WSL /tmp);
   detached WSL jobs die with wsl.exe (use Bash run_in_background); animlab.py prints GATE twice (anchor on
   `def cmd_compare`); STATUS.md is edited by others (edit by anchors); ffmpeg needs -nostdin in heredocs;
   untracked *.obj/vc100.pdb are not ours. pending-fixes/kfp-e1-*.py untracked by design (regress -> INFO if missing).
   Scratch /root/animlab-work (f14-e0, f13-sw0, f14-xb0, f16-c3a*, e1/ renders).

## How to resume
Read this file, `git log -- tools/animlab docs/animlab tests/animlab` in the harness repo and
`git log -- components/KenshiFP/animlab` in C:\KenshiModding. Run regress.sh (must be ALL PASS). Continue at "Next steps".
Gotchas: Git Bash: MSYS_NO_PATHCONV=1 + `wsl.exe ... -- bash -s <<'EOF'` heredocs (wsl.exe expands `$VAR` in -c args);
never run Windows `python` (hangs). Other agents (sword fixer) commit to tools/animlab too: commit only your files.
