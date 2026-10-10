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
- [x] P4 native: DONE (builder 2026-10-10): `tools/animlab/native.py` (list/sample/render incl. z25 view/traj/adapt/run/catalog/fists),
  `visual/ogre.py` skeleton animations + Ogre sampling, tests `tests/animlab/test_native.py`, USAGE.md "Phase 4", regress step P4,
  workspace `components/KenshiFP/animlab/native.json`. Not exact game blending. Tag `animlab-p4`. Open: fist candidates (NA1) do not
  pass yet (wrist fold 80-110 deg after the guard map; next: forearm-aligned hand orientation that converges, finger curl in the
  visual lab for fists); STATUS Next steps history (#7-#12 blocks) still to be condensed.

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
Format: date | point | what the game showed | recording path | build | status | class (failure class the check covers; rows
before 2026-10-10 11:30 unclassed)
- 2026-10-09 | C1 aim | aim pose did not play in background: the combat layer read only real keys, the viewmodel read harness input | C:\KenshiTestRuns\f14\xb0.txt (pre-fix) | pass: vmq-125c crossbow-z0 (build Oct 9 19:32:36) | CLOSED (lab): `animlab.py metrics` moves line, regress step 14: f14/xb0 FAIL aim:MISSING (also f13/x3, xb0b), vmq-125c crossbow-z0 PASS aim 6.2dm/23deg (vmq-cbaf 19:15, vmq-f804 19:24 also PASS). The input-layer cause itself is outside the solver; the lab detects the missing state
- 2026-10-09 | X1 crossbow jitter | game jitter p95 5-6 px vs replay ~0: bone-world map quantised at the floating origin (fixed in game by the node map, e948f86) | C:\KenshiTestRuns\vmq-f8c\vmrec-q-crossbow-z0.txt | 419D164F (6c9516b) | CLOSED (lab): `animlab.py compare` jitter line (game jit_p95 > 1 px at most 2.5x the replay, swings skipped), regress step 12: crossbow-z0 vs its 6c9516b replay FAIL (ready 1.74/0.42 x4.2, reload 2.73/0.41 x6.6); f14/xb0 (node map) vs the current solver PASS (ready x2.3, close to the limit; f13/sw0 without build stamp x2.5). The quantised-map mode (kfpvm_replay --abs-world: absolute float32 world, game magnitudes ~54100) does NOT reproduce it: float32 ulp ~0.004 units, far below a pixel; --bw-lag overshoots ready (7.3) -> the game mechanism is not modelled, only detected
- 2026-10-09 | jitter under-reported | lab jitter generally below the game's | vmq-f8c recordings | 419D164F | CLOSED with X1: the compare jitter line flags any state where the game is noisier than the replay (detects, does not model)
- 2026-10-09 | sword elbow branch drift | elbow switches branch on long replays/drives (e.g. drive @6c9516b sword-z0-a 83-232: elbow on the right branch, game low; no S2 re-seed + no elbow warm start in the drive) | C:\KenshiTestRuns\vmq-f8c\vmrec-q-sword-z0-a.txt | 419D164F (6c9516b) | CLOSED (lab): branch history dependence reproduced by check regress step 10 (cold drive @6c9516b elbow95 5.16 vs seeded 0.05). Drift (maintainer 7): long REPLAYS do not drift (sword-z0 full replay @6c9516b ready elb95 0.23); long DRIVES did, because `metricslab.py faithful` targeted the RENDERED pose: the rendered swing tail differs from the commanded one, the drive elbow stays at x~2 while the game elbow moves out to x~4.4 (frames 90-98), then sits on the other branch for the rest of the recording (elb 5.2 dm). New `faithful --commanded` drives the commanded pose (what the game solver got) and tracks the game through every swing. Regress step 16: sword-z0 0-520 @6c9516b rendered FAIL elbow95 5.15, commanded PASS 0.16. (Passing the recorded ui state/ti/swing flag into the drive did not help: tried, reverted.)
- 2026-10-09 | E1 edge leads | game swing led with the back of the blade (edge_arc -0.9 in the main stroke) | C:\KenshiTestRuns\f14\e0.txt | build Oct 9 18:21:44 | CLOSED (lab): `animlab.py metrics` arc gate (stroke frames after the wind-up u>=0.28: edge_arc>=0.7 on >=85%, swing wb_max<=30), regress step 11: game e0 arc_ok 0.50 FAIL, current solver replay 0.56 FAIL. Patch pending-fixes/kfp-e1-swlead.py: arc_ok 1.00 but wb_max 107 (the lead comes from fading the PT17 wfix roll = wrist fold); sweep with components/KenshiFP/animlab/patches/e1-lead-variants.py (e1wfix 0..1, e1clamp, edgeclamp, swlse/swlin/swlout): no variant has arc_ok>=0.85 with wb<=30 (e1wfix 0: wb 27 but arc 0.56). The lead roll must come from the forearm, not the wrist. Root cause (lab): straight-wrist edge sits ~-70 deg from the forearm projection about the blade, the strike velocity at +110..170 deg (keys sweep the blade along its length). CANDIDATE (sent to fixer + main): pending-fixes/kfp-e1-keys.py = kfp-e1-swlead.py + kfp-e1-rollcap.py (lead roll <= e1cap 50 deg off the straight wrist) + re-authored strike keys sw2..sw4 (found by components/KenshiFP/animlab/e1-climb.py, e1-mkpatch.py): arc_ok 1.00/1.00/0.97 on e0/f13-sw0/vmq sword-z0, wb_max 47.9/48.5/47.6 (current 50.7/53.2/63.7), elb_h_max <= 0.89; regress step 11 requires it. Video /root/animlab-work/e1/e1-compare.mp4. Rejected: kfp-e1-elbfollow.py (elbow follows the rolled hand: worse, the off-screen elbow pass rules block it)
- 2026-10-09 | C2 stock height | stock top high on screen; first fix (18:21 c2c) rotated the crossbow 24.5 deg (Shay) | C:\KenshiTestRuns\f16\c2a.txt, c2c.txt | build Oct 9 18:21:44 | CLOSED (lab): `animlab.py stock` (stock top line mp - k*mf + 1.45*mu, p95 <= 25% from the bottom in ready; --ref: ready fwd/up within 3 deg of f14/xb0 = d40b6ad-era pose), regress step 15: c2a FAIL 67%, c2c FAIL ori 24.5 deg, vmq-125c crossbow-z0 (19:32) PASS 15%/0.0 deg. Same numbers as the fixer's f16/c2.py + c2ori.py
- 2026-10-09 | C3 bolt jitter on walk | bolt + strings hang under a gun node the game sets to the native (pre-IK) Prop2 pose; fixed by kfp-c3-boltpin.py (node set to the post-IK Prop2 pose at the end of vm_apply) | C:\KenshiTestRuns\f16\r0.txt (pin off) | KenshiFP F8041381 | CLOSED (lab): `animlab.py bolt` now reads .bolt column group 5 (sl = bolt in the post-IK Prop2 frame; group 1 bl uses mp, measured at another time = false drift, only a fallback for old sidecars, `--source`), regress step 13: r0 FAIL dev95 0.52, r1 (pin on) PASS 0.000. Earlier "all f16 FAIL" results were bl false drift
- 2026-10-09 | crossbow READY commanded->rendered | game never reaches its own C2-era crossbow ready target: mp-out 0.69 dm constant (prop frame +0.39 f, +0.1 u, -0.56 n; elbow+wrist+hand shifted together, shoulder same; game stretch 1.88 vs lab 1.64), lab replay reaches it exactly (plain `gate` FAIL ready grip95 6.36 on vmq-85a7; same build sword-z0 also FAILs the plain gate). Drive gate with rendered targets PASSES (grip95 0.001 elbow95 0.023), --commanded FAILS 0.69 => the lab arm is right, a game-only step between g_vm_out and the IK target is unmodelled (also f16 c2c/r0/r1, vmq125c; old 6c9516b rec 0.1) | C:\KenshiTestRuns\vmq-85a7\vmrec-q-crossbow-z0.txt | KenshiFP 85A74C9B (69bc401) | CLOSED (lab, cause found by #11): the game solver's cached native upper-arm length g_vm_l1n (vm_l1: |fpn| * upper-arm derived scale .x, l1fix since 484c8bc, after 6c9516b = the 0.1 dm recs) is ~0.87 x the rendered upper arm: game/lab stch = 1.147-1.156 in every ready frame (sword too), rendered SE/stch 2.79 both, so elbow/wrist/hand/prop overshoot along the upper arm (crossbow 0.69, sword 0.7-0.9 dm, 1.4 deg off the arm line). Lab key l1k (components/KenshiFP/animlab/patches/l1-scale.py) scales g_vm_l1n: l1k 0.871 -> crossbow ready grip game-vs-replay median 0.69 -> 0.13 dm (@69bc401), sword-z0 plain gate FAIL -> PASS (l1k 0.86, @f41f862); regress step 20. Fix suggested to fixer #21 (true L1 = |ds (x) fpn| or |pe-ps| on a native frame; confirm with a game log line first; moves every tuned pose ~0.7 dm). LAB CONSEQUENCE: replays of builds since 484c8bc should use --set l1k=0.871 to match the game (until the game fix); without it the ready elbow sits on a lab-only branch B (see next row)
- 2026-10-09 | E1 inline | blade held ~90 deg to the forearm on screen, the wrist (not the arm) turns it through the swing (Shay: reference photos e1.PNG, e1 part 2.png vs Chivalry "right to left swing reference 1/2.png", "swing swing2.png") | C:\KenshiTestRuns\f14\e0.txt, f13\sw0.txt | build Oct 9 18:21:44 + current source (ad419c0) | CHECK ADDED: `animlab.py inline` (metrics.inline_series/inline_table/inline_check, unit test test_inline_check, regress step 18): wind-up + stroke forearm-blade angle median <= 30 / max <= 40 deg, screen max <= 40, stroke wrist share <= 0.6. Game e0 FAIL windup 42/58 stroke 51/62 sc 65 wr 1.00; sw0 FAIL 49/61, 47/62 wr 0.87; current solver replay FAIL 33/42, 50/62 wr 0.89. Cause (#9): the PT17 wfix elbow cone (half-angle acos(g_vm_hcos) ~50 deg around the blade). Also: arc gate now stroke frames only (u 0.28..0.58, Shay: the edge lines up from the stroke start; game e0 stroke arc_ok 0.00 = back of the blade leads the whole stroke). CANDIDATE (not installed, waiting for Shay's OK via main): pending-fixes/kfp-e1-inline.py = cone shrink (e1inl 0.88) + climbed keys sw1..sw4 + e1cap/e1hr/swlin (al10 climb c3b), regress step 18: f14-e0 inline PASS (windup 16/38, stroke 21/30 sc 29 wr 0.55), arc 0.91 wb 46.8, churn rev 137 windup roll 11.2 stroke roll 31.3/9.5; vmq85a7-sw all PASS (arc 0.93, roll 10.0, sroll 31.7/10.8); f13-sw0 INFO: swings 2+3 pass, swing 1 starts from the replay-only ready branch B (sroll 129). Renders C:\KenshiTestRuns\animlab\e1-compare.mp4, e1-sheet.png, e1-vs-chivalry.png
- 2026-10-09 | sword ready branch B (lab-found) | replays start f13-sw0 swing 1 and f14-e0 runs 87/495 from a second ready elbow solution (elbow 5.1,-4.1,5.0, edge ~100 deg off A); game recordings f14-e0 / vmq-85a7 are always A | /root/animlab-work/f13-sw0.txt, f14-e0.txt | 74A481A8 (f41f862) | CHECK ADDED (#11): `animlab.py branch [--ref]` (metrics.ready_runs/ready_branch, unit test test_ready_branch, regress step 19: @f41f862 replays FAIL, game PASS, kfp-rb-single.py + kfp-rb-camup.py PASS). Cause = the L1 mismatch above: with l1k 0.871 the replays stay on A everywhere (ready elbow z 3.7-3.8 like the game; lab 3.0 at l1k 1). Fixer #21 rb-single anchored rbe in the output (f,u) frame that rolls with the edge (A/B only ~24 deg apart there; rbcos 0.7 put every ready on B); kfp-rb-camup.py (f, camera up off f) separates them by ~70 deg -> all A; fixer applied it in /root/KenshiFP. Game f13-sw0 (older build) itself alternates two ready branches (edge 155 deg apart) = INFO
- 2026-10-09 | E1 wb36 arc wrist limit | game anim-sword-z0 (4 swings, 1st after draw): `metrics` arc FAIL only on wb_max 36.4/30 (arc_ok 0.95; PASS at --wb-max 50); the replay of the same rec agrees (36.3, arc_ok 0.94). STATUS #11 said wb36 "all checks PASS (arc)", but the default limit 30 can never pass wb36. inline/churn --stroke/branch PASS in game and replay | C:\KenshiTestRuns\vid\vmrec-anim-f23-sword-z0d.txt (replay C:\KenshiTestRuns\f23\replay-f23-sword-z0d.txt) | 9E5422A6 (c6a1eda) | CLOSED (coordinator: Shay accepted wb36 knowingly; arc wrist limit default 30 -> 50 = the vmcheck limit, metrics.ARC_WB; regress step 11b: this game rec must PASS at the default)
- 2026-10-09 | ready faithfulness gate | `replay` GATE FAIL by a hair on the same build: z0d ready grip_p95 0.25>0.25 and wrist_p95 0.25>0.25; f23-sword-z0 ready st_max game 2.94 vs replay 2.85 (|d|>0.08); swing per-frame error info only (edge95 9-15 deg) | C:\KenshiTestRuns\vid\vmrec-anim-f23-sword-z0d.txt, vmrec-anim-f23-sword-z0.txt | 9E5422A6 | OPEN (maintainer 2026-10-09: not a hair: the commanded pose is exact (out_p 0.000) and the shoulders match (0.004 dm), but the rendered right elbow/wrist/grip sit a near-constant 0.24 dm off the game (p50 0.239 p99 0.259; mean vector ready -0.10,-0.15,-0.15, block +0.10,-0.16,-0.14: x flips with the state). An l1k sweep (0.84-0.88) cannot fix both recordings at once (0.86: ready 0.22 but block elbow 0.38>0.35), so the 1-D L1 model is not the whole commanded->rendered offset; needs a model of the arm translation, not a tolerance change)
- 2026-10-09 | E1 swing 3 forearm flip | Shay: anim-sword-z0 swing 3 (same input as swings 2/4, from ready) the forearm rolls ~180 deg mid-stroke: bracer/sleeve side on top, hand flipped (palm/fingers under), blade edge-on vertical; swing 2 normal. Screenshots C:\KenshiModding\reference photos\swing2 normal forearm, good wrist.png + swing3_rotated froame, bad wrist.png. Lab branch/inline/churn checks all passed this rec | C:\KenshiTestRuns\vid\vmrec-anim-f23-sword-z0d.txt | 9E5422A6 (c6a1eda) | CLOSED (fixer #27: cause = vm_ik rolled the NATIVE upper arm/forearm minimally onto the target, so the bone roll came from the native attack variant playing (swing 3: native forearm ~100 deg off the target vs ~30 in swings 2/4); new check `animlab.py hinge` (same input -> same bone roll across swings from ready; recordings with group H also gate the upper-arm roll on the bend plane) FAILS on this rec (dev 112 deg @ swing 3) and on the game rec with the fix off (f27-h0a dev 179), PASSES with the KenshiFP E5 hinge fix (f27-h1a dev 10, abs 0))
- 2026-10-09 | lab build vs X4 | `build.sh` failed on c6a1eda: kfp_viewmodel.inc X4 uses ULONGLONG/GetTickCount64 (fixer #23 added both to components/KenshiFP/animlab/prelude.h on the virtual clock) | - | c6a1eda | CLOSED (prelude shim)
- 2026-10-09 | X7 crossbow zoom 25 | anim-xbow-z25.mp4 (12 segments, KenshiFP 550d5ba, fp_camera distance 25 orbit 2.36): the game shows the third-person body animating draw/ready/walk/aim/fire/reload/holster, but the recording has every frame as state `native` (1874 frames): `replay` GATE FAIL 0 comparable frames, `metrics` gives only draw/native rows, and `bolt` FAILs on the native frames (dev95 0.773 dm, step95 0.264, src=sl) where at zoom 0 it passes. The lab cannot judge any zoomed-out pose (PT29 hand-away/weapon-visible/wrist checks live only in fp-viewmodel.sh), and the bolt check needs a native/zoom-out rule (pass, skip or its own limit) | C:\KenshiTestRuns\vid\vmrec-anim-f26-xbow-z25.txt | 550d5ba | OPEN
- 2026-10-09 | E5 hinge replay vs game | re-rendered anim-sword-z0.mp4 (5 swings from ready, hinge on): game rec `hinge` PASS (dev 11, abs 0; forearm roll fa ~-16..+5 across swings), the replay of the same rec (build.sh --sync, kfpvm_e5) `hinge` FAIL dev 157: forearm roll sits ~60 deg off the game (fa 35-85) and swing 2 flips 80 -> -89 at u 0.90; replay upper-arm roll 0 like the game. Likely: the replay captures its own local hinge (first 30 bent-elbow frames of the replayed native pose) instead of the game's captured hinge (rec has no hinge-capture record) | C:\KenshiTestRuns\vid\vmrec-anim-f28-sword-z0c.txt (replay /tmp/f28-rep.txt via f27/replay.sh) | KenshiFP E334DB71 (830c781) | CLOSED (lab, maintainer 2026-10-09): cause = the replay's fake arm bones had a synthetic roll (local Y nearest camera up) and the replay captured its own hinge from it; native bone roll is not recorded. The game rig's arm bones bend about local -Y (in-game `fp_vm hinge`, outbox 20261009-230703: L_ua=L_fa=R_ua=R_fa=0,-1,0, cap 30) and the game captured before the recording. kfpvm_replay now gives the bones local Y = -(native bend normal) and starts the E5 hinge captured (0,-1,0) (`--up-roll`/`--hinge-capture` = old behaviour). Replay @830c781: hinge PASS dev 29, per-frame forearm roll vs game median 0.7 deg p95 1.4 (was 58.4; new `animlab.py hinge --vs`); --up-roll FAIL dev 157 (miss reproduced). z0d still FAILS: game rec dev 112, replay through its own solver c6a1eda dev 109, through 830c781 hinge 0 dev 120 (flip reproduced), hinge 1 PASS dev 7. Regress step 11d. Left: dev 29 comes from the blade-roll divergence row below
- 2026-10-09 | sword blade roll divergence, swing 2 tail | replay of f28-sword-z0c: frames 827-843 (end of swing 2, swu 0.84-1) rendered blade up (mu) up to 97 deg off the game while the commanded pose (out_f/out_u) and blade forward (mf) are exact; the replay rolls the other way at 827 (out_u-vs-mu game 98 -> 48, replay 113 -> 147) and comes back at ~7 deg/frame; same with --up-roll, so not the bone roll model; elsewhere mu error median 1.5 p95 2.5 deg. Likely the wrist-roll refinement state (warm start / jerk limit) is not recorded | C:/KenshiTestRuns/vid/vmrec-anim-f28-sword-z0c.txt | E334DB71 (830c781) | OPEN (lab)
- 2026-10-09 | E6 stroke 2 roll flicker | game f30-k2a (stroke 2 overhead, KenshiFP 8DD2CB41): one-frame blade roll flick -21/+24 deg at u .38-.40 in every swing (churn stroke step 35 FAIL); the replay of the same rec is smooth (step 12): target out_f/out_u identical, game hand axes (mh/hz) jump one frame. A/B in game: wroll 0 removes it (elbow-pick blade roll), hinge 0 / wrllag 40 / elbla 0 do not. Worked around by moving key 2 (sw2 p 0.9,0.3,5.0) | C:\KenshiTestRuns\vid\vmrec-f30-k2a.txt | 8DD2CB41 | OPEN (fixer #30)
- 2026-10-09 | E6 stroke 3 arc game < replay | game f30-k3a stroke 3 arc_ok 0.81 vs replay 0.89 on the same rec: extra bad frames at u .43-.44 (arc 0.64-0.70) only in the game | C:\KenshiTestRuns\vid\vmrec-f30-k3a.txt | 8DD2CB41 | OPEN (fixer #30)
- 2026-10-10 | E6 stroke 0 arc replay < game | anim-e6 (KenshiFP 9DA35EE0) stroke 0 (unchanged, approved) arc_ok game 0.92 vs replay 0.83 of the same rec (replay FAIL < 0.85, game PASS): the reverse of the stroke 3 row; stroke 0 keys untouched since E6 | C:\KenshiTestRuns\vid\vmrec-anim-anim-e6.txt | 9DA35EE0 | OPEN (fixer #33)
- 2026-10-10 | E6 stroke 2 wind-up snap | anim-e6 raw 13.43->13.47 s (30 fps): at the wind-up top the hand+sword jump in ONE video frame (guard edge-on bar -> tilted disc, blade ~25 deg): sword frame rotation 27 deg per 33 ms right after the slowest frame of the top (strokes 0/1: 20/13, rising smoothly into the strike). Churn step (per game frame) and arc passed. Check `animlab blade` snap (max rotation per 33 ms in [top, top+.10 u] <= 22): FAILS game 27, replay 28, f31-k2w 31 | C:\KenshiTestRuns\vid\vmrec-anim-anim-e6.txt | 9DA35EE0 | check added (fixer #33); stroke 2 refit pending
- 2026-10-10 | E6 end-on blade frame (vis metric miss) | anim-e6 raw 13.67 s: one frame shows only hand+guard (tsuba face-on, blade an edge-on hairline pointing into the scene); the fixer's vis metric (screen length, windowed u .38-.62, median) said min .48. Same frame type in stroke 0 at 3.68 s (u .65-.67). Check `animlab blade` seen = per-frame min of screen length x |flat normal . view ray| over u .45-.95 >= 0.05: FAILS stroke 2 0.021 (u .67); stroke 1 0.072 PASS. BASELINE EXCEPTION stroke 0: seen 0.020 (u .65, the same one-frame end-on at 3.68 s) stays as is (coordinator 2026-10-10: Shay accepted stroke 0 at zoom 0, do not change it); strokes 1 and 2 must pass the full blade check, thresholds not to be loosened. Time-aligned to the video (rec t - 0.24 s) | C:\KenshiTestRuns\vid\vmrec-anim-anim-e6.txt | 9DA35EE0 | check added (fixer #33); stroke 2 refit pending; stroke 0 = documented baseline exception

- 2026-10-10 | E6 stroke 1 foreshortened / stroke 2 overhead diagonal (coordinator review) | anim-sword-e6.mp4: stroke 1 backhand blade ~90 deg to the forearm, foreshortened (5.7-5.9 s); stroke 2 overhead read as a diagonal; inline + blade PASSED both (inline: 0.5 dm straight grip segments + 3D angle ~30; blade: end-on facing only) | /root/animlab-work/e6-anim-b2.txt | A2C2E8AC | CHECK ADDED (maintainer #12): `animlab.py stroke --overhead 2` (harness 5e7ba25, regress 22): FAILS stroke 1 len 147/240 px @u.70, stroke 2 tilt 60/35 deg @u.78 (follow-through lays over; middle path vertical 5 deg); approved stroke-0 swings PASS 271-292 px. Pass case = fixer's fixed rec C:\KenshiTestRuns\vid\vmrec-e6-fix.txt (pending)
- 2026-10-10 | take: label vs game state (zoom-sweep "Crossbow aim (RMB)" was a reload of an unloaded crossbow; turret-fp "crossbow READY back" true ~1 s; refilm "crossbow back" while HUD HOLSTERED) | labelled takes had no or one-sample-per-label evidence | vidscripts/f36 labels+ev (orig), f36 10:03 refilm (snapshots /root/animlab-work/takes/t6old, t6rev) | - | CHECK ADDED: harness `tools/animlab/takecheck.py` (fb687a3) + `components/KenshiFP/animlab/take-sample.sh` / `take-rules.txt` (regress 23): claims must hold over the whole label segment (no unsampled gap > 1 s), `pre` loaded>=1 before aim, cover; t6rev FAILS "crossbow back" vs hud_text=holstered @50.63, t6old FAILS unverified. Zoom sweep has no state: unit tests only (aim on ui_state=reloading + loaded=0 FAIL). Sampler mock-tested only; pass case = first take recorded with it (fixer)
- 2026-10-10 | take: combat / bystanders during the take (turret-fp "Tassilo is attacking!", Self preservation, blood pool; refilm: hungry-bandit group walks into frame, speech bubbles) | - | same | - | CHECK ADDED (takecheck + sampler): forbid msgs>0 (harness `messages`), near>0 (non-squad chars within 20 m of the fp character, allowed handles excluded), down>0, ui_state down/staggered; old takes FAIL (never sampled = unproven). Hostile AI goal not sampled (messages + near cover it)
- 2026-10-10 | take: video ~7 s past the `end` label (turret-fp refilm) | - | f36/turret-fp.mp4 10:04 (59.00 s, end 51.51) | - | CHECK ADDED: takecheck end (video length - end label within [-0.2, 1.0] s): t6rev FAILS +7.49 s
- 2026-10-10 | crossbow sliver above the UI at zoom 0 (zoom-sweep) | - | - | - | DROPPED (coordinator: Shay's accepted C2b pose; the 1600x900 test window's UI panel covers it, at 2560x1440 it shows)
- 2026-10-10 | open ground on recorded frames (sword-z25-block: steep slope fills most of the frame for the first half; setup check had passed) | - | C:\KenshiTestRuns\vm-rework\sword-z25-block.mp4 (copy /root/animlab-work/takes/videos) | - | CLOSED (check): harness `tools/animlab/frames.py openground` (6fa4b44, regress 24): sky share of the scene band >= 0.08 on >= 90% of frames; FAILS open 0.49, closed 0.0-17.5 s (sky 0.05); anim-sword-e6 / anim-xbow-z25 / turret-fp PASS (0.29 / 0.11 / 0.22)
- 2026-10-10 | Z1 crossfade 2-8 dm: own headless torso/shoulders, floating hand, oversized hand on the stock (zoom-sweep 3:44 ... 5:07-5:14) | the take had no vm rec | - | - | CHECK ADDED: `animlab.py zoomband` (0688e89, regress 26): no own neck/spine/shoulder (elbows/wrists once zf < 0.99) in the zoom camera's view between the eye and head_show 16 dm (camera `zoom` dm behind the eye, orbit 0). Real body of VMQUICK crossbow-z25 at 5 dm FAILS (nk+Lsh+Rel+wrists), as recorded (25 dm) / z0 PASS. Game fail/pass recs pending: C:\KenshiTestRuns\vid\vmrec-zoom-sweep-old.txt / -fix.txt (fixer)
- 2026-10-10 | z25 block guard: blade hanging straight down, hilt at the face (sword-z25-block orbit 3.0, 21-22 s) | the take had no vm rec; native Kenshi block anim (hanging guard) seen from the front | - | - | CHECK ADDED: `animlab.py guard` (75d8f25, regress 25): median blade elevation over block frames >= -60 deg (hanging guard ~-80..-90); VMQUICK z25/z0 block recs PASS (35 / 4 deg: that build's z25 block did not animate, S3). Whether the native hanging guard is acceptable is a product/Shay call; fail/pass recs pending: vmrec-z25-block-old.txt / -fix.txt (fixer)
- 2026-10-10 | take: Windows mouse cursor in frame (Shay, ticket A: sword-z25-block ~7 s, 12-16 s, 35-36 s) | - | C:\KenshiTestRuns\f36\sword-z25-block.mp4 (copy /root/animlab-work/takes/videos/sword-z25-block-f36.mp4) | - | CLOSED (check): harness `tools/animlab/frames.py cursor` (arrow shape at any cursor size on full-res frames, 5 fps), run automatically by `takecheck.py --video` (fail `cursor`; `--no-cursor` skips), regress 27: FAILS 46/205 frames at 7.0-9.6 s (cursor moving), 12.4-16.6 s, 33.8-37.2 s; turret-fp PASS 0/316, anim-sword-e6 PASS. Also found: older takes anim-xbow-z25 (0-6.6 s, over the play button) and vm-rework sword-z25-block (whole take, parked at 1280,720) show it too
- 2026-10-10 | free block guard random per press (coordinator: chooseBlock picks the native technique per press; 228c60/2245b0/223cc0 raised, 223090/226e50/227e90 hanging) | the guard check judged the whole-take median | C:\KenshiTestRuns\blk-survey\blk-table.tsv, blk-table-repeats.tsv, blk-sheet-per-tech.jpg | - | CHECK ADDED: `animlab.py guard` judges EVERY press (runs of block frames, median over the settled 70%; any press < -60 deg = FAIL); `guard <survey>.tsv` judges the per-press survey rows: blk-table FAIL 14/45 hanging (226e50 -75, 227e90 -68, 223090 -62), repeats FAIL 17/45; VMQUICK sword-z25 / f28-sword-z0c PASS (2 presses each). Unit test test_guard_check. GAME REC FOUND (maintainer): vmq-f059 vmrec-q-sword-z25 (F0595751) press 0 hangs -75 -> `guard` FAIL press0@frame468; the 4080 rec of the same build PASS (61/61); corpus copies C:\KenshiTestRuns\corpus\poolslock-guard, `pool --motion block` FAIL take 0.67, regress 28. Lab-vs-game: replaying the z25 rec re-solves the native block (press 0 game -75, replay +44): block pool judges recs as recorded (see X7 row). PASS rec of the raised-guard build pending (fixer) | class: random native variant per occurrence (every press judged; predict over the press pool)
- 2026-10-10 | E6 stroke 1 blade seen / len: game below replay | game e6fix (F0595751) stroke 1 seen 0.048 (FAIL < 0.05) at swing1 u .93, len 237 (FAIL < 240) at u .78; replay of the same rec with the same source: seen 0.075, len 245 (both PASS) | C:\KenshiTestRuns\kfx-b2\e6\e6fix.vmrec.txt (= /root/animlab-work/e6fix-game.txt) | F0595751 | OPEN (fixer refit 4 adds margin: replay seen 0.087, len 262)
- 2026-10-10 | E6 stroke 2 blade seen: replay below game (reverse) | game e6fix stroke 2 seen 0.116 at swing1 frame 1318 u .94; replay (F0595751 source and refit 4) 0.030 at the same frame: replay FAIL, game PASS, at the recovery end | same rec | F0595751 | OPEN
- 2026-10-10 | taste R8 wrist (vmcheck) | Shay accepted f28-sword-z0c (sword zoom 0, 3912d09) and picked wb36 (f23-sword-z0d) but vmcheck (fp-viewmodel.sh PT30) still gates sword SWING frames at wb 30: FAILS both (wb 37.8 / 36.4); spec.py wrist + arc.wb (swing 50) PASS | corpus rec/f28-sword-z0c.txt, rec/f23-sword-z0d.txt | E334DB71 / 9E5422A6 | OPEN (taste, class taste): vmcheck swing limit should follow metrics.ARC_WB 50 (fp-viewmodel.sh owner: KenshiFP fixer)
- 2026-10-10 | taste R17 blade on stroke 0 | `animlab blade` FAILS the Shay-accepted stroke 0 (f28 snap 26/22 + seen 0.000 @u.65; e6-anim stroke 0 seen 0.000): the documented "baseline exception" is not in the check, so every stroke-0 swing is a false alarm | corpus rec/f28-sword-z0c.txt, rec/e6-anim.txt | E334DB71 / 9DA35EE0 | CLOSED (spec 2026-10-10): R17 snap/end-on now native-referenced (`spec.py blade`: snap <= 32, end-on <= 67 ms, from the game's katana attacks); stroke 0 passes with no exception (t65/t66 TN). New disagreement t62 (coordinator reject of stroke 2: snap 27, end-on 23 ms) is inside the native range | class: taste, rule threshold vs native
- 2026-10-10 | taste t62 R17 FN (native reference) | coordinator rejected E6 stroke 2 (wind-up snap 27 deg/33 ms + one end-on frame 23 ms); `spec.py blade` (native katana attacks: snap 7-32, end-on <= 67 ms) passes it: the flaw is inside what the game's own swings do | corpus rec/e6-anim.txt (--only-stroke 2) | 9DA35EE0 | CLOSED (coordinator 2026-10-10): superseded by native rule R17 (coordinator reject 10-10 predates native reference; stroke 2 refit passes anyway); taste t62 relabelled superseded | class: taste, coord verdict vs native reference
- 2026-10-10 | taste R2 inline per swing (working tree) | the uncommitted per-swing `inline` (metrics.py "each: swings k/n", working tree 2026-10-10 ~12:40) FAILS the Shay-accepted f28-sword-z0c (swings 3/5, worst swing3@1182) and f23-sword-z0d; the committed whole-take inline PASSED both | corpus rec/f28-sword-z0c.txt, rec/f23-sword-z0d.txt | E334DB71 / 9E5422A6 | OPEN (taste): maintainer to recheck the per-swing limits against the taste set (`bash components/KenshiFP/animlab/taste/run.sh --only R2`) before committing
- 2026-10-10 | fists-badpunch (FAIL) | hands are open splayed claws, not fists (even half-open is closer than this); strike hand arrives palm-up with wrist cocked = reads as a reach/grab, not a straight-wrist punch; at u.82 left forearm crosses over the right hand mid-screen | C:\KenshiTestRuns\fists-cand\badpunch\sheet-z0.png | - | FIXED 2026-10-10 (fists): class 'fist hand frame + arm crossing' -> spec.py unarmed U19 (knuckles lead at contact: hand X <= 30 deg over the sight line, palm hidden/not up/not palm-heel), U20 (guard palm hidden), U21 (arms cross on screen); U18 closure out of reach (no finger bones, face-only mesh poses: the game hand is the same fixed half-open mesh). FAIL corpus fists/fail-20261010 (all 4), PASS fists/pass-20261010; candidates fixed in native.py (palm-down guard, flex 18/22, badpunch strikes L only) found:review
- 2026-10-10 | fists-ma_chudan (FAIL) | same class: open claw hands; strike hand at contact (u.36-.73) palm-up/cocked wrist, fingers curled up = reach, not a knuckles-leading punch; lab spec passed it (lab miss: fist closure + knuckles lead) | C:\KenshiTestRuns\fists-cand\ma_chudan\sheet-z0.png | - | FIXED 2026-10-10 (fists): class 'fist hand frame + arm crossing' -> spec.py unarmed U19 (knuckles lead at contact: hand X <= 30 deg over the sight line, palm hidden/not up/not palm-heel), U20 (guard palm hidden), U21 (arms cross on screen); U18 closure out of reach (no finger bones, face-only mesh poses: the game hand is the same fixed half-open mesh). FAIL corpus fists/fail-20261010 (all 4), PASS fists/pass-20261010; candidates fixed in native.py (palm-down guard, flex 18/22, badpunch strikes L only) found:review
- 2026-10-10 | PT30-FLIP vmcheck time base | vmcheck (fp-viewmodel.sh PT30) flagged a sword strike onset (4080 pt30-sword rec frame 158, du 24.5 vs 7.1) next to a 0.100 s hitch: the solver advances its animation by min(dt, maxdt 0.05) but vmcheck scaled the neighbour rates by raw dt; not a solver flip (all 3 swings carry the same commanded sequence) | corpus pools/sword-swing/pt30-sword.txt | 4080 PT30 build | FIX READY: pending-fixes/kfp-pt30-flip.py part 1 (vmcheck neighbour rates per animation step min(dt, maxdt)); flag 158 gone, game rec 2 -> 1 flag. Check for the maintainer: regress step "new vmcheck on pt30-sword (game + replay): frame 158 not flagged" | class: check time base (per-time rates must use the solver's animation step)
- 2026-10-10 | PT30 follow-through edge roll spikes | game pt30-sword frame 284 (u .92, du 73.6): the rendered edge rolled away and snapped back in the follow-through; the lab replays showed the same class on 9/10 pool recs (vmcheck du 15-56 deg vs 2-10 neighbours at u .6-.96, 28 flags) but no animlab check (churn/inline/blade/arc/stroke) caught it: only vmcheck run on replays. Causes: E1 lead tangent flips at the strike-end key while the lead fades; the wfix straight-wrist roll refinement (elbow dir ~along the blade, a.f .9-.98) overshoots back and forth and the 6 deg lag cap passes the one-frame spikes | corpus pools/sword-swing/*.txt (replays), pt30-sword.txt | KenshiFP ad419c0 + working tree | FIX READY: kfp-pt30-flip.py parts 2-3 (pool flags 28 -> 5, max spike 56 -> 32 deg; ready/block recs 4 -> 0; pool stroke-0 arc take .74 -> .89); OPEN for the maintainer: an animlab check for one-frame edge roll spikes in swings (du spike vs neighbours, per animation step) run on the pool replays | class: roll spike (one-frame edge roll about the blade)
- 2026-10-10 | foreign overlay (cursor class -> any overlay) | NPC speech bars / chatter lines, name tags ([Malzin], [Axima], Tassilo), damage numbers, hint lists and popups over the scene went unflagged (only the cursor was checked); mutation vid-popup-overlay (grey dialog box) was a known gap | C:\KenshiTestRuns\corpus\takes\videos\turret-fp.mp4, sword-z25-block-f36.mp4, anim-xbow-z25.mp4, kept/vm-rework_zoom-sweep.mp4 | - | CHECK ADDED: `frames.py overlay` (text lines: outlined thin text / text on flat dark panels; flat UI panels with straight edges; take baseline = own HUD; zones = centred label band x .15-.85 top 20% + bottom UI 30%), run by takecheck --video (`--no-overlay`), unit tests test_frames Overlay, regress 31, mutate vid-popup-overlay CAUGHT (base kept/kfx-b2_e6_e6fix.mp4), taste R15 overlay (t80-t83). FAIL: turret-fp (speech), sword-z25-block(-f36) (name tags), anim-xbow-z25 (hint list + chatter + tag), zoom-sweep (tags), anim-sword-e6 + vm-rework anim-sword-z0 (NPC chatter line top-left: accepted before the rule, t83 superseded); PASS: e6fix, vm-rework anim-xbow-z0 | class: foreign overlay (any UI/text drawn over the scene; use `chatter off` for takes)

## Catch-rate ledger (animlab-loop; `python3 components/KenshiFP/animlab/ledger.py`)
Who found each flaw first (lab / coordinator review / Shay / game rows), per build and per class, from the Misses rows
above and SETUP_MISSES.md (tag a row `found:lab|review|shay|game` to override the guess). Regenerate after every build or
new Misses row; the goal is the lab column growing and the Shay column shrinking.
<!-- ledger:start -->
Generated by `components/KenshiFP/animlab/ledger.py` (KenshiModding) from the Misses + SETUP_MISSES rows; do not edit by hand. "game" = found in game rows/takes after the lab passed; "lab" = the lab found it first.

**Per date / build** (build = column 5 of the row, `-` = take/setup rows without a build)

| date / build | lab | review | Shay | game | total |
|---|---|---|---|---|---|
| 2026-10-09 Oct 9 19:32:36 | 0 | 0 | 0 | 1 | 1 |
| 2026-10-09 419D164F | 0 | 0 | 0 | 3 | 3 |
| 2026-10-09 Oct 9 18:21:44 | 0 | 0 | 1 | 1 | 2 |
| 2026-10-09 F8041381 | 0 | 0 | 0 | 1 | 1 |
| 2026-10-09 85A74C9B | 0 | 0 | 0 | 1 | 1 |
| 2026-10-09 ad419c0 | 0 | 0 | 1 | 0 | 1 |
| 2026-10-09 74A481A8 | 1 | 0 | 0 | 0 | 1 |
| 2026-10-09 9E5422A6 | 0 | 0 | 1 | 2 | 3 |
| 2026-10-09 c6a1eda | 0 | 0 | 0 | 1 | 1 |
| 2026-10-09 550d5ba | 0 | 0 | 0 | 1 | 1 |
| 2026-10-09 E334DB71 | 0 | 0 | 0 | 2 | 2 |
| 2026-10-09 8DD2CB41 | 0 | 0 | 0 | 2 | 2 |
| 2026-10-10 9DA35EE0 | 0 | 0 | 0 | 3 | 3 |
| 2026-10-10 A2C2E8AC | 0 | 1 | 0 | 0 | 1 |
| 2026-10-10 - | 0 | 9 | 2 | 4 | 15 |
| 2026-10-10 F0595751 | 0 | 1 | 0 | 2 | 3 |
| 2026-10-10 E334DB71 | 0 | 0 | 3 | 0 | 3 |
| 2026-10-10 550d5ba | 0 | 1 | 0 | 0 | 1 |
| 2026-10-09 - | 0 | 0 | 0 | 1 | 1 |
| **all** | 1 | 12 | 8 | 25 | 46 |

**Per flaw class**

| class | lab | review | Shay | game | total |
|---|---|---|---|---|---|
| crossbow | 0 | 0 | 1 | 4 | 5 |
| lab-infra | 0 | 0 | 0 | 4 | 4 |
| setup | 0 | 8 | 2 | 5 | 15 |
| sword-pose | 1 | 3 | 5 | 11 | 20 |
| zoom | 0 | 1 | 0 | 1 | 2 |

Lab catch rate (lab-first / all flaws): 1/46 = 2%; gate runs that blocked a build on a returned miss: 0.
<!-- ledger:end -->

## Taste score (spec/taste builder, 2026-10-10)
Shay's (and the coordinator's) accept/reject decisions as labelled recordings: workspace `components/KenshiFP/animlab/taste/taste.tsv`
(71 rows: 67 scored, 4 listed: superseded/open/decision-only), recordings/videos/takes in the protected corpus (C:\KenshiTestRuns\corpus,
MANIFEST rows `taste:<rule>`). Weights: shay 1.0, shay-sym / shay-fix 0.75, coord 0.5. Rerun (WSL, ~1.5 min cold, cached after):
`bash /mnt/c/KenshiModding/components/KenshiFP/animlab/taste/run.sh [--only R1,R2] [--md out.md]` (harness `tools/animlab/taste.py`).
Every FN / FP is a Misses row of class "taste".

| rule | n | TP (rej+FAIL) | TN (acc+PASS) | FN (lab missed) | FP (false alarm) |
|---|---|---|---|---|---|
| R1 edge lines up at the stroke start and leads through the stroke (wind-u | 7 | 4 | 3 | 0 | 0 |
| R2 blade roughly in line with the forearm; shoulder/elbow drive the arc,  | 5 | 2 | 3 | 0 | 0 |
| R3 no hand/forearm roll in the wind-up; no sudden wrist/blade roll | 6 | 3 | 3 | 0 | 0 |
| R4 no arm churn: elbow/forearm must not swing out and back while the weap | 4 | 1 | 3 | 0 | 0 |
| R5 same swing input -> same forearm roll (no forearm flip mid-stroke) | 2 | 1 | 1 | 0 | 0 |
| R6 ready pose stable: no sudden ~90 deg roll mid-walk, one ready branch | 4 | 2 | 2 | 0 | 0 |
| R7 sharp edge never faces the camera at rest (ready/walk/block) | 4 | 2 | 2 | 0 | 0 |
| R8 wrist bend: holds <= 30 deg (PT30), swings <= 50 (Shay accepted wb36) | 4 | 2 | 0 | 0 | 2 |
| R9 every state visibly plays: pose moves vs ready (aim, block, reload, sw | 3 | 1 | 2 | 0 | 0 |
| R10 stock low (<= 25% from the bottom in ready), crossbow orientation unch | 5 | 3 | 2 | 0 | 0 |
| R11 bolt and strings rigid on the crossbow | 2 | 1 | 1 | 0 | 0 |
| R12 no shake in still poses (aim) | 3 | 1 | 2 | 0 | 0 |
| R13 no clipped or hollow limbs (near-plane cut) | 4 | 2 | 2 | 0 | 0 |
| R14 zoom 25 looks natural: hand away from the head, weapon visible, wrist  | 1 | 0 | 1 | 0 | 0 |
| R15 every frame judgeable: open ground, nothing solid in frame, full res,  | 6 | 3 | 3 | 0 | 0 |
| R17 blade reads on screen: wind-up-top rotation within the native rate, en | 4 | 2 | 2 | 0 | 0 |
| R20 take labels match game state; no combat / bystanders; video ends at th | 2 | 2 | 0 | 0 | 0 |

Items 66 scored (+5 open/superseded listed), weighted agreement 0.96 (was 0.89; fresh cache 2026-10-10 after the native-reference
R17 + the maintainer's per-swing inline). Disagreements: t33 (R8 FP f28-sword-z0c.txt), t34 (R8 FP f23-sword-z0d.txt): vmcheck.wrist
gates swings at 30. t62 (coordinator reject of E6 stroke 2: snap 27, end-on 23 ms, inside the native range) relabelled superseded
by native rule R17 (coordinator 2026-10-10); the Shay-accepted stroke 0 (snap 20-26 / end-on 12-30 ms) passes with no exception.

## Rule -> check map (spec-first; `bash .../taste/run.sh map --md`)
Rules file `components/KenshiFP/animlab/taste/rules.tsv` (owner shay / coord / native / inferred), checks `taste/checks.json` (check id ->
lab command + verdict regex). `spec.py run <rules> --checks <checks> --class sword|crossbow <rec>` runs every rule of a class on a
new recording; `run.sh unarmed <candidate dir>` runs the unarmed spec on fist candidates (pose.txt).

| rule | class | source | owner | check ids | status |
|---|---|---|---|---|---|
| R1 edge lines up at the stroke start and leads through the stroke (wind-up may be off) | sword | memory sword-edge-leads-arc; E1/E2 | shay | arc.edge | covered: stroke frames u .28-.58 only |
| R2 blade roughly in line with the forearm; shoulder/elbow drive the arc, wrist little | sword | memory sword-inline-with-forearm; Misses E1 inline | shay | inline | covered |
| R3 no hand/forearm roll in the wind-up; no sudden wrist/blade roll | sword | memory sword-edge-leads-arc; E1 wind-up flip | shay | churn.roll | covered |
| R4 no arm churn: elbow/forearm must not swing out and back while the weapon barely moves | all | memory no-arm-churn | shay | churn.rev | covered: sword recordings; unarmed U9 |
| R5 same swing input -> same forearm roll (no forearm flip mid-stroke) | sword | E5 (Shay review anim-sword-z0 swing 3) | shay | hinge | covered: needs >= 3 swings from ready |
| R6 ready pose stable: no sudden ~90 deg roll mid-walk, one ready branch | sword | E3 | shay | branch | covered: --ref a known-good recording of the same build |
| R7 sharp edge never faces the camera at rest (ready/walk/block) | sword | S1 | shay | restedge | covered: new (spec.py restedge, p05 of edge cos >= 0) |
| R8 wrist bend: holds <= 30 deg (PT30), swings <= 50 (Shay accepted wb36); solver-posed frames only, native-animation frames exempt (Shay 2026-10-10) | all | PT17-W, PT30, X3, X5, c6a1eda, Shay 2026-10-10 | shay | wrist,arc.wb,vmcheck.wrist | partial: vmcheck.wrist gates swings at 30 too (FAILs Shay-accepted f28); spec.py wrist splits holds/swings, skips native frames (metrics.NATIVE_STATES) |
| R9 every state visibly plays: pose moves vs ready (aim, block, reload, swing) | all | memory state-must-visibly-play; C1 | shay | moves | covered: unarmed U3 |
| R10 stock low (<= 25% from the bottom in ready), crossbow orientation unchanged | crossbow | C2, C2b accepted (13bca46) | shay | stock | covered: --ref f14-xb0 (d40b6ad-era orientation) |
| R11 bolt and strings rigid on the crossbow | crossbow | C3 | shay | bolt | covered: needs the .bolt sidecar |
| R12 no shake in still poses (aim) | crossbow | X1 | shay | stilljit | partial: new absolute check (aim jit_p95 <= 1.5 px), calibrated on 3 recordings; the replay-relative `compare` jitter line needs a build-matched solver |
| R13 no clipped or hollow limbs (near-plane cut) | all | PT17, X2, C4 | shay | vmcheck.cut | covered: vmcheck (fp-viewmodel.sh) on the zoom-0 frames; unarmed U7 |
| R14 zoom 25 looks natural: hand away from the head, weapon visible, wrist limit | all | memory zoomout-every-build; PT29 | shay | vmcheck.zo | partial: vmcheck zo only (PT29); `animlab.py` has no zoom-25 judgement (Misses X7 row OPEN); no Shay-labelled z25 recording |
| R15 every frame judgeable: open ground, nothing solid in frame, full res, no cursor | all | memory screenshots-must-be-judgeable; ticket A | shay | openground,cursor | covered: videos (frames.py) |
| R16 review before handing over: every frame reviewed, flaws fixed first | all | memory review-before-handing-over | shay | - | out-of-reach: process rule (coordinator), not a property of a recording |
| R17 blade reads on screen: wind-up-top rotation within the native rate, end-on in the follow-through at most two video frames, full length, overhead descends vertically | sword | native reference (snap, end-on: game katana attacks, Shay 2026-10-10); E6 coordinator reviews (len, overhead) | native | blade.snap,blade.seen,stroke.len,stroke.oh | covered: spec.py blade: snap <= 32 deg/33 ms (native downward combo 32 @x1.2, chop down 15, bigchopv2 14, heavy downcut 10, desperate attack 7; chop left 47 starts at the top = engine crossfade, not counted); end-on (seen < 0.05 on screen) <= 67 ms (native bigchopv2 67, desperate attack 33). No stroke-0 exception needed: stroke 0 snap 20-26, end-on 12-30 ms PASS. len/overhead stay coord |
| R18 block guard not hanging (blade not straight down, hilt not at the face) | sword | Misses z25 block guard | coord | guard | covered: whether the native hanging guard is acceptable is Shay's call (open) |
| R19 zoom crossfade band: no own headless torso / floating hand between eye and head-show distance | all | Z1 coordinator review | coord | zoomband | covered: no game recording of the fail case yet |
| R20 take labels match game state; no combat / bystanders; video ends at the end label | all | T6 coordinator review | coord | takecheck | covered: takes only |
| R21 hand grips the hilt (no open palm, fingers wrapped) | sword | PT33 | shay | - | out-of-reach: recordings hold no finger bones; the visual lab renders fingers in the bind pose |
| R22 do not enlarge the arm / change framing to match Chivalry; only the movement matters | all | memory sword-inline-with-forearm | shay | - | out-of-reach: a negative design rule: nothing to measure (framing changes show up as stock/stroke regressions) |
| U1 guard: both fists on screen at rest (zoom 0), below the eye line | unarmed | native reference: ma idle1 stance hands below the eye (wrists y -3.7 / -8.5 dm, all clip starts -3.1..-3.8); on-screen = FP visibility (U3/R9, Shay) | native | spec:U1 | covered: native guard is below the FP view (y/z -2.0 R, -3.2 L); FP keeps the native 'below the eye' shape, lifted onto the screen |
| U2 every technique returns to the guard (last key = guard, <= 0.5 dm) | unarmed | native reference: clips end 0.4-3.5 dm off their start (arms vs chest) and the engine crossfades back to the stance; the FP key set has no crossfade | native | spec:U2 | covered: badpunch end-start 1.5/3.5, chudan 2.6/1.9, 2strike 0.5/0.4, shoteiL 0.4/0.6 dm (L/R) |
| U3 the technique visibly plays (fist moves >= 1 dm from the guard) | unarmed | memory state-must-visibly-play | shay | spec:U3 | covered |
| U4 a punch drives toward the screen centre, at or below the centre line | unarmed | native reference: striking fists land at |x/z| <= 0.29, y/z -0.28..-0.09 (badpunch L, chudan L/R, 2strike R, shoteiL L) | native | spec:U4 | covered: limits |x/z| <= 0.30, y/z -0.35..+0.05 |
| U5 no hand at / above / behind the eye (forearm/fist >= 2.5 dm from the eye, <= eye level +0.5 dm) | unarmed | PT29 hands at the head (Shay), NA1 row | shay | spec:U5 | covered: thresholds 2.5 / +0.5 dm are the lab's (native.py fists) |
| U6 wind-up never rises above the strike (wrist/fist highest at the strike) | unarmed | native reference: every native striking hand is highest AT the strike; wind-up stays 0.62-2.64 dm below it | native | spec:U6 | covered: was 'wind-up below eye level' (inferred); limit rise <= 0.1 dm; hands at the head stay U5 (Shay) |
| U7 no near-plane cut of forearm/fist | unarmed | PT17 (Shay) | shay | spec:U7 | covered |
| U8 wrist bend <= 30 deg | unarmed | PT17-W / PT30 (Shay) | shay | spec:U8 | covered |
| U9 no arm churn | unarmed | memory no-arm-churn | shay | spec:U9 | covered: same limits as the sword churn (450 px within 0.4 s, fist <= 250 px) |
| U10 punch driven by shoulder/elbow, not the wrist (wrist share of fist motion <= 0.45) | unarmed | native reference: native striking hands 0.04-0.41 (straight punches 0.04-0.25, palm strikes 0.40/0.41) | native | spec:U10 | covered: was 0.6 (inferred) |
| U11 no sudden fist roll (<= 40 deg per 33 ms on straight-wrist frames) | unarmed | native reference: native fist roll on straight-wrist frames (wb <= 30) up to 36.5 deg/33 ms (2strike L; badpunch 23, shoteiL 27.5, chudan 5) | native | spec:U11 | covered: was 30 on every frame (inferred); bent-wrist frames skipped (prop axis tilts without a roll; U8 judges the bend) |
| U12 the game's half-open hand is accepted: no fist-closed check (skeletons have no finger bones) | unarmed | Shay 2026-10-10 (via coordinator) | shay | - | dropped: decision, nothing to gate; replaces the inferred "fist closed" rule |
| U13 zoom 25 = the native third-person animation, unchanged | unarmed | NA1 plan row; zoomout-every-build (Shay) | shay | vmcheck.zo | partial: only after an in-game build (game recording + VMQUICK sheet); offline: native.py sheet-z25 |
| U14 kicks: the arms move with the body (no held guard), the camera follows the head; headbutt: the guard holds while the head moves | unarmed | native reference: kicklow/megakick/flykick/flyknee wrists travel 6.4-9.5 dm vs the chest, head 9.6-44 dm; headbutt wrists <= 1.8 dm, head 10.7 dm | native | - | missing: was 'guard holds' (inferred, contradicted by the native kicks); no kick candidate format yet (camera motion is not in pose.txt) |
| U15 solver reaches every key (no IK failure) | unarmed | lab | coord | spec:U15 | covered |
| U16 unarmed has no block: the defence is the native dodge back (guard kept at its height, the view moves back) | unarmed | native reference: game data has no unarmed block technique (dodgeback/dodgefall/dodgefly only); dodgeback wrists dy -0.7..+0.4 dm (L 1.6, R 4.8 dm travel), head 17 dm back | native | - | missing: was 'block raises the guard' (inferred, no native counterpart); no dodge candidate yet |
| U17 palm-heel techniques become straight-wrist punches (wrist <= 30 deg); native palm strikes are not kept | unarmed | Shay 2026-10-10 (via coordinator) | shay | spec:U17 | covered: spec.py unarmed: candidates named shotei*/palm* get U17 (wb_max <= 30 every frame) |
# rules=39 covered=29 dropped=1 missing=2 out-of-reach=3 partial=4

## Unarmed spec (NA1, before the fists are built)
`spec.py unarmed` on metricslab/native.py fist candidates (dir with <technique>/pose.txt; `_*` helper dirs skipped): U1 guard view,
U2 return to guard, U3 moves, U4 strike to centre, U5 eye clear, U6 wind-up not above the strike, U7 near-plane cut, U8 wrist <= 30, U9 churn,
U10 arm-driven (wrist share), U11 fist roll per 33 ms, U15 ikfail, U17 palm-heel = straight-wrist punch (shotei*/palm*). Shay
decisions 2026-10-10: half-open hand accepted (U12 dropped: no finger bones), palm-heel -> straight-wrist punch (U17), and the
formerly inferred rules (U1 U2 U4 U6 U10 U11 U14 U16, plus R17 snap/end-on) take their shape and limits from the game's own
animations ("use the native in-game animations to guide you"): owner `native`, hard rules. Numbers below.

### Native reference (animlab-spec, 2026-10-10)
Measured with the same check code (`spec.unarmed_checks`, `spec.blade_native`) on the native clips: `native.py trajectory`, unarmed =
target hand, pelvis stab, shoulder anchor on the FP body (vmrec-q-sword-z0-a frame 100); katana = weapon target, fit anchor, torso
stab; sampled at 30 fps x the technique's anim speed mult (game data). Strikers from the game data (badpunch L, ma chudan LR,
ma 2strike R, ma shotei L). Scratch scripts: WSL /root/animlab-work/spec-native (rebuildable, not kept).

| rule | native measurement | old (inferred) | new (native) |
|---|---|---|---|
| U1 guard | ma idle1 wrists y -3.7 (R) / -8.5 (L) dm, clip starts -3.1..-3.8: below the eye and below the FP view (y/z -2.0 / -3.2) | both fists on screen | on screen AND below the eye line (y <= 0) |
| U2 return | clip end vs start (arms vs chest) 0.4-3.5 dm; the engine crossfades back to the stance | end <= 0.5 dm | unchanged (FP keys have no crossfade: last key = guard) |
| U4 strike | strikers' nearest-centre point abs(x/z) .16-.29, y/z -.28..-.09 | abs(x/z) <= .30, abs(y/z) <= .35 | abs(x/z) <= .30, y/z -.35..+.05 |
| U6 wind-up | every striker highest AT the strike; wind-up 0.62-2.64 dm below it | wind-up y <= eye | wind-up never above the strike (rise <= 0.1 dm); eye cap stays U5 |
| U10 arm-driven | wrist share .04-.41 (straight punches .04-.25, palm strikes .40/.41) | <= 0.6 | <= 0.45 |
| U11 roll | roll per 33 ms on straight-wrist frames up to 36.5 (2strike L; badpunch 23.4, shotei 27.5, chudan 4.7); bent-wrist frames up to 88 (prop axis tilts with the bend) | <= 30, every frame | <= 40, straight-wrist frames (wb <= 30) |
| U14 kicks | kicklow / megakick / flykick / flyknee: wrists travel 6.4-9.5 dm vs the chest, head 9.6-44 dm; headbutt: wrists <= 1.8 dm, head 10.7 dm | guard holds | arms move with the body in kicks; guard holds only in the headbutt (no candidate format yet) |
| U16 block | game data: no unarmed block technique (dodgeback / dodgefall / dodgefly); dodgeback wrists dy -0.7..+0.4 dm, head 17 dm back | block raises the guard | no block: native dodge back, guard kept at its height (no candidate yet) |
| R17 snap | rotation per 33 ms after the wind-up top: downward combo 32 (x1.2), chop down 15, bigchopv2 14, heavy downcut 10, desperate attack 7 (chop left 47 starts at the top = engine crossfade, not counted) | <= 22 + stroke-0 exception | <= 32, no exception (`spec.py blade`) |
| R17 end-on | follow-through on-screen visible blade < 0.05: bigchopv2 67 ms (0.038), desperate attack 33 ms (0.001), downward combo / heavy downcut 0 (disabled chop down 100 ms) | seen >= 0.05 every frame + stroke-0 exception | end-on stretch <= 67 ms (`spec.py blade`) |

Fist candidates (fists 5a03b7d, /root/animlab-work/fists/cand) under the native rules: all 4 PASS (were badpunch FAIL U11 37 > 30,
shoteiL FAIL U6 0.05 dm above the eye). Marginal: badpunch L roll 37.0 deg/33 ms (above the native max 36.5, inside the 40 limit);
badpunch R wind-up rise +0.09 dm (limit 0.1; native badpunch strikes with L only, the candidate keys R as a striker too).
The metrics.py `blade` default (snap 22, seen >= 0.05) and regress row 21 are unchanged (maintainer's): only the spec/taste R17
checks use `spec.py blade`.

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
   E1 INLINE STATE (maintainer #10 since 2026-10-09, copied from #9's temp handoff). NEW DIRECTION (Shay via main, overrides
      the churn-era brief): (1) blade roughly IN LINE with the forearm through wind-up + stroke; the arc comes from shoulder/elbow,
      little wrist. Checks: forearm-blade angle per phase + wrist share of tip motion; current E1 must FAIL them. Miss row:
      E1 | blade ~90 deg to forearm, wrist-driven | C:\KenshiModding\reference photos (e1.PNG, e1 part 2.png vs Chivalry
      "right to left swing reference 1/2.png", "swing swing2.png"). (2) Edge must line up from the STROKE START and lead through
      it (wind-up may be off; old version overcorrected): edge-lead gate on stroke frames only. No wind-up hand roll, no churn.
      (3) Keep framing/camera; NO screen-coverage check. (4) Deliverables: patch in pending-fixes (not installed),
      C:\KenshiTestRuns\animlab\e1-compare.mp4 (labelled, 1x, current vs candidate), e1-sheet.png (elbow/grip trails), still of
      candidate mid-stroke next to the Chivalry refs; review at full res, message main with paths + numbers; to fixer only after Shay OKs.
      Prototype metric (#9): %TEMP%\claude\C--KenshiModding\al9\inline.py: phases windup u<0.28, stroke <0.58, follow <0.78, recov;
      fb = 3D angle forearm (Rel->Rwr) vs blade mf (median/max), sc = same on screen, wr = sum|tip - tip-if-blade-rigid-with-forearm|
      / sum|dtip|. Numbers: game f14-e0 stroke fb 51/62 sc 50/65 wr 1.11 | f13-sw0 47/62 wr 0.88 | current replay 50/62 0.88 |
      kfp-e1-keys 56/71 0.75. Ready fb 35-42 (grip angle, g_vm_hcos 0.64). Gate idea: stroke fb med <= 25-30, max <= 40, wr <= ~0.4.
      Root cause: PT17 wfix elbow pick puts the elbow on a cone of half-angle acos(g_vm_hcos) ~50 deg around the blade.
      Candidate pending-fixes/kfp-e1-inline.py (runs noroll -> keys -> swlead/rollcap first): cone th*(1-e1inl*w), w smoothstep
      0->1 over u [0,e1ia], 1->0 over [e1ib,1]; keys e1inl 0.6, e1ia 0.2, e1ib 0.8; build /root/animlab-build/kfpvm_e1i. f14-e0:
      windup fb 18/41, stroke 36/44, wr 0.73. Next: e1inl 0.8-0.9, climb sw1..sw4 keys (al8/climb2.py, runp.py) on stroke fb, wr,
      arc (stroke only), wb <= 50, churn rev <= 450, windup_roll <= 15, stroke roll <= 45 / step 12. climb1 BEST (kfpvm_e1n) passed
      arc/wb/rev/windup roll but stroke roll 100 deg (59 deg steps). Current game (kfpvm_cur): arc 0.56/0.58, windup roll 77/47,
      stroke roll 75/73 (all FAIL). Rigid-pivot keys (al9 rig.py) dead end (fb 69); planar keys (al9 plane.py) fail arc.
      #10 progress: inline check + stroke-only arc committed (harness 2a4e662, regress step 18 c6cf95f). Climb tools in
      %TEMP%\claude\C--KenshiModding\al10 (ev.py = all checks on f14-e0 + f13-sw0 + vmq85a7-sw, climb.py = sw1..sw4 p/f/u +
      e1inl/ia/ib/e1cap/e1hr/swlin, mkpatch.py BEST -> pending-fixes/kfp-e1-inline.py, vid.sh side-by-side mp4). Results in
      /root/animlab-work/al10-c*.txt. FINDING: the ready pose has a second elbow branch in replays (B: elbow 5.1,-4.1,5.0,
      edge mu 0.79,0.5,-0.37 vs A: 1.4,-4.4,3.0, mu 0.42,-0.24,0.88; roll ~100 deg apart): f13-sw0 first swing after the
      draw always starts from B, current solver e0 swing 2 too; game recordings f14-e0 / vmq85a7 are always A. With no
      wind-up roll allowed, a swing from B cannot line the edge up (stroke roll ~120). ev.py scores branch-A swings and
      penalises B readies (the recovery decides the next ready branch).
   #11 RESUME (maintainer #11 since 2026-10-09, copied from #10's temp handoff): kfp-e1-inline.py (untracked by design, from
      al10/mkpatch.py on /root/animlab-work/al10-c3b.best) + renders C:\KenshiTestRuns\animlab\e1-compare.mp4, e1-sheet.png,
      e1-vs-chivalry.png are WITH SHAY via main: never replace that script; variants go into separate pending-fixes scripts.
      Patch goes to the fixer (#21, agent a37dcef1911e6c866, owns the 5090 + lock fixer-pt30) only after Shay OKs via main.
      If rejected: re-climb with al10 tools (ev.py score, climb.py, mkpatch.py, vid.sh). Order for #11: (1) reduce the
      candidate's ulnar wrist bend (wb ~47) keeping inline/arc/churn/roll; (2) lab check for ready branch B (must FAIL f13-sw0
      swing 1); (3) crossbow READY 0.69 dm miss (kfpvm_replay --set-at 400:state); (4) other open Misses. al10-*.png in
      C:\KenshiTestRuns\animlab are deletable review crops. Gotchas: detached WSL jobs die with wsl.exe (Bash
      run_in_background + `wait`); `pkill -f al10/climb.py` inside `bash -c` kills its own shell (use `bash -s`); ev.py
      scores branch-A swings, each B ready costs 3; climb ~1.5 min/gen at POP 100 / NP 15.

   #11 STATE (2026-10-09, end of #11): DONE: (2) branch check `animlab.py branch` + regress 19; fixer #21's kfp-rb-single.py frame
      fixed by pending-fixes/kfp-rb-camup.py (applied in /root/KenshiFP by the fixer). (3) crossbow READY miss CLOSED: game L1n ~0.87 x
      rendered upper arm (Misses row). COORDINATOR DECISION: do NOT change the game's L1 (Shay approved the crossbow look; a ~0.7 dm
      shift would undo it): true-L1 game fix PARKED pending Shay. The lab's DEFAULT game model is now l1k 0.871 (build.sh applies
      patches/l1-scale.py to every replay build; --no-l1 = old lab; --drive builds stay exact); regress 20. (1) wrist bend: variant
      pending-fixes/kfp-e1-wb36.py (+ kfp-e1-inlwb.py; al11 climb c2, %TEMP%/claude/C--KenshiModding/al11 tools, WBT/WBK env in ev.py)
      wb 47 -> 36, stroke fb 28/39, roll 14; still C:\KenshiTestRuns\animlab\e1-wb36-still.png; forwarded to Shay as an alternative.
      RE-SCORE under l1k 0.871 (@f41f862): review candidate kfp-e1-inline.py arc 0.86/0.82/0.86 (f13-sw0 FAILS arc 0.85), wb36
      0.94/0.91/0.96 all checks PASS (inline, arc, churn --stroke, branch). Regress 18 now shows the inline candidate f13-sw0 arc FAIL
      as INFO. Left: (4) no other open Misses; if Shay picks an E1 version, re-render e1-compare with the L1 model; climb tools
      (al10/al11 ev.py) predate the default L1 model: rebuild their binaries to use it.

   #12 STATE (maintainer #12, 2026-10-10): the 2026-10-10 coordinator-review misses (8 + T6 refilm items) all have checks
      (rows above; regress 22-26 ALL PASS, 64 PASS lines). Waiting on the KenshiFP fixer (a5aa229d98a3cead0, successor of
      a03a9444) for game recordings: vmrec-e6-fix, vmrec-zoom-sweep-old/fix, vmrec-z25-block-old/fix (copied by regress from
      C:\KenshiTestRuns\vid) and a take recorded with take-sample.sh (copy labels.txt/ev.txt/video-len.txt to
      /root/animlab-work/takes/ok-<name>/: regress 23 requires PASS). New files of #12: harness tools/animlab/takecheck.py,
      frames.py, tests/animlab/test_takecheck.py, test_frames.py; workspace components/KenshiFP/animlab/take-sample.sh,
      take-rules.txt. Phase-4 builder (a0bf79e3fd0cce93a) owns native.py/ogre.py/render.py and appends its regress step at the
      end; it will clean up STATUS/USAGE later (Misses rows unchanged). Scratch: %TEMP%\claude\C--KenshiModding\al12.
      Sampler v2 (workspace 7c396ed, harness 06de228 kah.send_many): v1 (5 stobe-auto calls/sample) gave in-game gaps up to
      3.1 s and near ALWAYS 0 (one-line chars reply); v2 = take_sample.py, one inbox write per sample every 0.6 s, mock
      (take_sample_mock.py: fake harness on /mnt/c + concurrent take script) max gap 0.63 s, no take slowdown. zoomband skips
      band_hidden frames (rec H 5th token, KenshiFP 3AFB09A4+; harness c7aa9a8).

## How to resume
Read this file, `git log -- tools/animlab docs/animlab tests/animlab` in the harness repo and
`git log -- components/KenshiFP/animlab` in C:\KenshiModding. Run regress.sh (must be ALL PASS). Continue at "Next steps".
Gotchas: Git Bash: MSYS_NO_PATHCONV=1 + `wsl.exe ... -- bash -s <<'EOF'` heredocs (wsl.exe expands `$VAR` in -c args);
never run Windows `python` (hangs). Other agents (sword fixer) commit to tools/animlab too: commit only your files.
- 2026-10-10 | E6 kfx-b2 lab predicted PASS, game FAILED | e6fix take (KenshiFP F0595751): stroke 1 arc_ok 0.62 + seen 0.048, stroke 0 snap 23 + seen 0 (accepted baseline); the fixer's offline check (replay of e6-anim-b2 through kfpvm_f059) said stroke 1 arc 1.00, seen 0.073 | C:\KenshiTestRuns\kfx-b2\e6\e6fix.vmrec.txt (corpus pools/sword-swing/e6fix.txt) | F0595751 | CLOSED (lab, maintainer 2026-10-10): the lab is faithful (replay of e6fix: stroke 1 arc 0.67, swings 0.83/0.50 vs game 0.83/0.42; stroke 0 snap 23 / seen 0 both); the prediction used ONE recording with one native swing per stroke, and the native attack variant (random per swing) changes the rendered stroke. New `animlab.py pool` (harness 7974133, regress 28): every swing of the corpus pool (8 old game recs, 36 full swings) replayed with the stroke forced, predicted 2-swing take pass rate >= 0.95: F059 stroke 1 FAIL arc 0.35 (predicts the game), refit4 arc PASS 0.97 but blade 0.60 FAIL (end-on at u .94-.95 in 9/41 swings; sent to fixer), stroke 2 blade 0.89. Left: seen 0.048 game vs 0.071 replay at frame 897 = the open "blade roll divergence, swing tail" row (mu off 5-20 deg at u .85-.93) | class: random native variant per occurrence (predict over the variant pool, never one rec)
- 2026-10-10 | free block progress never live (fb_lives 0) | fb_lives stayed 0 over 90+ free blocks (p 1.010, pmin 9.000) while the body took the block pose; neither the vm rec (prog = free swing only) nor the take evidence (fp_keys/fp_combat state) carries it; `fp_keys set ...` prints fb_lives only as a side effect of a set | C:\KenshiTestRuns\logs61010-111249-stop\KenshiFP.log (corpus logs/animlive/kfp-fblock-live0.log) | KenshiFP F0595751 | CHECK ADDED (maintainer): `takecheck.py --kfplog LOG [--log-t0 T]` = `animlive` (every PT34 free block end / free swing end in the take window live=1), regress 29: that log FAILS 4/4 blocks never live, free-swing log (07:36, 61 ends live=1) PASSES; unit test test_animlive. Take scripts must pass --kfplog + the take's wall-clock t0 (fixer). Not in the rec: the pre-IK native pose would show it only indirectly (no rise of the guard) = out of reach without a rec field; a rec field `fbp` (free block progress) would be the in-rec signal if wanted | class: native animation the take relies on never ran (progress not live)
- 2026-10-10 | crossbow reload replay faithfulness: one game rec off | game vmrec-pt30-xbow (4080, PT30 xbow: draw, aim, fire, reload from aim) reload mf.y median 0.33 / max 0.76; replay with the F0595751 solver (kfpvm_f059, also every rev f41f862..de4e703) 0.57 / 0.93; the 5090 VMQUICK rec of the same build matches (game 0.33, replay 0.34); the same pt30-sword replay adds du flags 116/164 the game does not have (game flags 33/158; 158 reproduced 24.31 vs 24.47) | C:\KenshiTestRuns\kfp-regress\vmrec-pt30-xbow.txt, vmrec-pt30-sword.txt (27 fps 4080 recs, 0.100 s hitch frames) | F0595751 | OPEN (kfp-regress)
- 2026-10-10 | agree: ready grip/wrist p95 0.25-0.26 > 0.25 | `agree` gate disagreement on 4 F059 recs (e6fix, pt30-sword, q-sword-z0-f059, pt26-f059-4080): game PASS (self), replay FAIL by 0.00-0.01 dm | corpus agree/agree.list | F0595751 | OPEN = the "ready faithfulness gate" row (near-constant 0.24 dm rendered offset, needs an arm translation model) | class: pose table (ready) commanded->rendered offset
- 2026-10-10 | agree: f13/f14 recs have no exact solver | f14-e0 / f13-sw0 / f14-xb0 ("build Oct 9 18:21:44") replayed through kfpvm_d40b6ad (nearest rev): gate elbow95 0.8 / 5.8 / 3.5 dm, f13-sw0 branch game FAIL replay PASS, churn game PASS replay FAIL (windup roll 14 vs 81) | corpus rec/f13-sw0.txt, f14-e0.txt, f14-xb0.txt | 18:21:44 (rev unknown) | OPEN (lab): agree needs the exact solver per rec; recs carry only a build time stamp. Fix: KenshiFP rec header `# src <git rev or snapshot hash>` (fixer) + the manifest maps it; until then these rows are provenance, not solver errors | class: rec -> build provenance
- 2026-10-10 | agree: sword-z0 block jitter | vmrec-q-sword-z0 (6c9516b) block jit_p95 game 6.6 vs replay 3.4 px | corpus rec/vmrec-q-sword-z0.txt | 419D164F | OPEN = X1 (game jitter detected, not modelled) | class: game-only noise not modelled
- 2026-10-10 | agree: E6 swing tail blade roll | e6fix stroke 1 blade seen game 0.048 (FAIL) vs replay 0.071; stroke 2 seen game 0.116 vs replay 0.030 (FAIL), both at u .93-.95 (mu 5-20 deg off at u .85-.93) | corpus pools/sword-swing/e6fix.txt | F0595751 | OPEN = "sword blade roll divergence, swing 2 tail" row (wrist-roll refinement state not recorded) | class: stroke table, swing tail
- 2026-10-10 | agree: threshold-marginal stroke checks | e6fix stroke 0 inline stroke fb game 28 / replay 31 (limit 30), stroke 1 swing 1 len game 237 / replay 245 (limit 240): small game-replay differences cross the limit | corpus pools/sword-swing/e6fix.txt | F0595751 | OPEN (lab): report a margin band (|value - limit| < game-replay spread = "marginal") so a marginal stroke is flagged before a game take; pool predictions already average over swings | class: stroke table, marginal vs limit
- 2026-10-10 | agree: zoomed-out block re-solved | q-sword-z25-f059 guard game FAIL (press 0 -75 deg) vs replay PASS (-34): the replay solves the viewmodel on frames the game shows as the native third-person block | corpus pools/block-guard/q-sword-z25-f059.txt | F0595751 | OPEN = X7 (lab cannot model zoomed-out native poses); block pool judges recs as recorded | class: native/zoomed-out pose not modelled

## Lab agreement (lab replay vs game, per check)
<!-- agree:begin (written by `animlab.py agree --status`, do not edit by hand) -->
2026-10-10, manifest `agree.list`: 21 recs; agreement per check (agree/compared): arc 9/9, blade 7/9, branch 6/7, churn 8/9, gate 5/13, guard 8/9, hinge 6/6, inline 8/9, moves 13/13, stock 4/4, stroke 8/9; disagreements 15 (each one has an open Misses row):

- vmrec-q-sword-z0 gate: game PASS, replay FAIL (frames=378 block jit_p95 game=6.57 replay=3.40 (|d|>2.00); adapter kfpvm_6c9516b)
- f14-e0 gate: game PASS, replay FAIL (frames=551 ready grip_p95=0.26>0.25; ready elbow_p95=0.80>0.35; adapter kfpvm_d40b6ad)
- f13-sw0 gate: game PASS, replay FAIL (frames=626 ready grip_p95=0.66>0.25; ready elbow_p95=5.80>0.35; adapter kfpvm_d40b6ad)
- f13-sw0 branch: game FAIL, replay PASS (elb 6.6/1.4 roll 155/0 elb 5.5/0.1; adapter kfpvm_d40b6ad)
- f13-sw0 churn: game PASS, replay FAIL (rev 393/305 grip 155/247 windup_roll 13.7/80.6; adapter kfpvm_d40b6ad)
- f14-xb0 gate: game PASS, replay FAIL (frames=801 ready grip_p95=0.54>0.25; ready elbow_p95=3.54>0.35; adapter kfpvm_d40b6ad)
- e6fix gate: game PASS, replay FAIL (frames=1286 ready grip_p95=0.25>0.25; ready wrist_p95=0.25>0.25; adapter kfpvm_f059)
- e6fix inline[s0]: game PASS, replay FAIL (fb 25/24 sc 13/15 wr 0.83/0.85; adapter kfpvm_f059)
- e6fix blade[s1]: game FAIL, replay PASS (snap 16/15 u 0.37/0.34 seen 0.048/0.071; adapter kfpvm_f059)
- e6fix stroke[s1]: game FAIL, replay PASS (len 237/245 len 245/252; adapter kfpvm_f059)
- e6fix blade[s2]: game PASS, replay FAIL (seen 0.116/0.03; adapter kfpvm_f059)
- pt30-sword gate: game PASS, replay FAIL (frames=257 ready grip_p95=0.25>0.25; ready wrist_p95=0.25>0.25; adapter kfpvm_f059)
- q-sword-z0-f059 gate: game PASS, replay FAIL (frames=413 ready grip_p95=0.26>0.25; ready wrist_p95=0.26>0.25; adapter kfpvm_f059)
- q-sword-z25-f059 guard: game FAIL, replay PASS (hanging 1/0 elev_press_min -75/-34 elev_min -79/-73; adapter kfpvm_f059)
- pt26-f059-4080 gate: game PASS, replay FAIL (frames=49 ready grip_p95=0.26>0.25; ready wrist_p95=0.26>0.25; adapter kfpvm_f059)

Full table: `/mnt/c/KenshiTestRuns/corpus/agree/agree-table.md`
<!-- agree:end -->
