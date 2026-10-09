# Animation lab: status (durable state)

Owner: animation-lab builder agent (ordered by Shay, 2026-10-09). This file + git are the
ONLY state (no temp handoffs). Update, commit and push at every milestone.
Builder #1 stopped at its context limit; builder #2 resumed 2026-10-09 evening.

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
- [ ] P1 replay: adapter + CLI work; gate fixes in progress (see Next steps)
- [ ] P2 metrics lab
- [ ] P3 visual lab

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

## WSL scratch (not git, may be lost; rebuildable)
`/root/animlab-kfp-src` (rsync copy), `/root/animlab-src-archive/e80aa2a5` (source at DLL e80aa2a5),
`/root/animlab-build/` (binaries), `/root/animlab-work/` (copied recordings + sims).

## Results so far (gate)
Gate pairing: recordings in `C:\KenshiTestRuns\vmq-f8c` (made right after workspace commit 6c9516b =
DLL 419D164F) replayed with source 6c9516b.
- sword-z0-a PASS (grip95 0.23 dm, elbow95 0.22, blade95 0.01 deg, edge95 1.8, wb95 0.4; game/replay
  wb_p95 11.2/11.2, st_max 2.80/2.78).
- crossbow-z0: ready/aim match (0.13-0.14 dm, blade 0.00); reload FAILS (elbow95 0.62, st_max 2.40 vs
  2.70, elb_h_max 0.17 vs 1.55).
- sword-z0 (swings): close but FAIL (swing elbow95 0.58, edge95 13.6, ready edge95 6.2, block jit 6.6 vs 3.4).
- z25 recordings: viewmodel faded (zf<1 = native anim), not comparable yet.

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
1. P1 gate fixes: (a) apply only when napply increments; (b) native prop local transform from the
   recording; (c) exclude frames with zf<0.99. Re-run gate (vmq-f8c sword-z0, sword-z0-a, crossbow-z0).
2. Build against CURRENT /root/KenshiFP (rsync copy); check crossbow jitter X1 (p95 5-6 px in game) on
   newest crossbow recording (C:\KenshiTestRuns\f13 or opt).
3. Offline regression tests (tests/animlab), docs/animlab/USAGE.md, tag animlab-p1, SendMessage main.
4. Rec metadata patch as pending-fixes script, send path to main.
5. P2, then P3.

## How to resume
Read this file, `git log -- tools/animlab docs/animlab tests/animlab` in the harness repo and
`git log -- components/KenshiFP/animlab` in C:\KenshiModding. Continue at "Next steps".

## Builder #2 handoff (copied by coordinator 2026-10-09)
# Animation lab handoff #2 (builder #2 stopped at the context limit, 2026-10-09 ~18:40)

Task source: coordinator "main" brief (3 phases; see C:\KenshiModding\Kenshi-Automation-Harness\docs\animlab\STATUS.md
"Goal"/"Rules" for the full order). Durable state = STATUS.md (committed 8519a42) + this file.

## Git state
- Harness repo (main), pushed: 8519a42 (tools/animlab/*.py + STATUS.md). UNCOMMITTED (all mine, commit them):
  M tools/animlab/recfmt.py (napp, zf default, native group -> r['nat']), M tools/animlab/metrics.py ('native' state
  zf<0.99, 'settle' in STATE_ORDER), M tools/animlab/animlab.py (NOCMP, gated states ready/block/aim, settle_s 0.3 +
  frame-before-transition, mark_settle()), M docs/animlab/STATUS.md? (not edited since commit), NEW tests/animlab/test_animlab.py
  (7 tests, pass), NEW docs/animlab/USAGE.md (done). Ignore untracked *.obj / vc100.pdb (not mine).
- KenshiModding repo (main), pushed: de545db (adapter). UNCOMMITTED (mine): M components/KenshiFP/animlab/kfpvm_replay.c
  (napply-aware apply, native group parse+use, # set lines applied, --set ordering, --no-native/--no-rec-sets/
  --apply-all/--bw-lag, scene-node identity stubs, elb_cb warm start, silent set reply), M build.sh (AL_HAVE_ELB_CB),
  M prelude.h (node-map stubs), NEW regress.sh (ALL PASS), NEW pending-fixes/kfp-rec-native-meta.py (the KenshiFP rec
  metadata patch: build stamp, # set log, native pre-IK pose group; tested on a copy, compiles, round trip exact).
  pending-fixes script must NOT be committed by me? -> it's a pending-fix for the coordinator; just SendMessage its path.

## Done (P1)
- (a) napply: implemented; finding: only 1 frame per recording lacks an apply with the viewmodel up (the 181/233
  zero-delta frames are w=0 frames) -> not a deviation source.
- (b) native prop local: only possible with the rec-native patch (plfix=3 default makes it irrelevant except rlnat
  reload). Implemented in the adapter from the native group.
- (c) zf<0.99 -> state 'native', not compared.
- Gate (6c9516b, vmq-f8c): sword-z0-a PASS 556 fr, crossbow-z0 PASS 1380 fr (ready+aim); sword-z0 FAIL only block
  jit 6.57 game vs 3.40 replay; reload/swing = info (native pose not recorded). Native round trip (current source +
  patch) reproduces crossbow incl. reload exactly. Sword round trip diverges from frame 3 (bistable elbow, hidden
  state) -> documented limitation.
- X1: replay does NOT reproduce the game jitter: xv-f14base ready jit game 1.23 vs replay 0.01; rec-xb0 1.44/0.64;
  crossbow-z0 1.74/0.42. Replay map world<->skeleton is exact; fixer's new mapnode (scene-node map) source compiles
  with stubs. --bw-lag (full 1-frame lag of bone-world in apply) overshoots (7.2 vs 1.7) -> partial-lag/other source.
  With stretch=1+elb=0 replay jitter stays ~0 too.

## Left
1. Run regress.sh (WSL: `bash /mnt/c/KenshiModding/components/KenshiFP/animlab/regress.sh`), commit harness files
   (one commit: gate states/settle/native parsing + tests + USAGE.md) and KenshiModding animlab files; push; tag
   `animlab-p1` in the harness repo (and KenshiModding). Update STATUS.md (results, P1 done) and commit.
2. SendMessage "main": PHASE 1 READY + usage one-liner (see USAGE.md) + can/can't (jitter under-reported; swing/reload
   need the rec-native patch) + X1: not reproduced + path C:\KenshiModding\pending-fixes\kfp-rec-native-meta.py
   (apply to /root/KenshiFP, rebuild, re-record VMQUICK so swing/reload/jitter replays use the native pose).
3. P2 metrics lab (separate module tools/animlab/author/, adapter --drive mode), P3 visual lab (Ogre mesh reader;
   reference /root/KenshiFP/client/kfp_meshray.h). Not started.

## Gotchas
- Git Bash: use MSYS_NO_PATHCONV=1 + `wsl.exe ... --cd <path> -- python3 - <<'EOF'`; backslash-n inside heredoc python
  strings gets collapsed: use chr(92) or the Edit tool. Never run Windows `python -` (hangs).
- animlab.py `--args=--quiet` (with `=`).
- /root/KenshiFP is being edited by the fixer (mapnode etc.); prelude may need new stubs when it changes.
- Recordings copied to /root/animlab-work (vmrec-q-*.txt from vmq-f8c, xv-*.txt + rec-xb0.txt from opt).
