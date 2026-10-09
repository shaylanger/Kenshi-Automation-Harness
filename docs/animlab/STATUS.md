# Animation lab: status (durable state)

Owner: animation-lab builder agent (ordered by Shay, 2026-10-09). This file + git are the
ONLY state (no temp handoffs). Update, commit and push at every milestone.
Builders #1-#3 stopped (context limit); builder #4 (2026-10-09 evening) finished P2, works on P3.

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
- [ ] P3 visual lab: in progress (see Next steps)

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
P2 drive gate: crossbow-z0 345-1097 @6c9516b PASS (elbow95 0.07); sword-z0-a 83-232 @current PASS (elbow95 0.05), FAILS
@6c9516b (wrist95 1.1, elbow95 5.2) = open question, not investigated (that build's frozen-replay path vs sword wrist
roll; current source fine). Dual-wield example PASS (R wb_max 13, L wb_max 24: L/R asymmetry in the windup/cut on a
mirrored motion, worth a look by the FP fixer if dual wield goes ahead; ww_min 0.22 dm).

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
1. P3 visual lab (generic in harness `tools/animlab/visual/`, KenshiFP specifics in the workspace adapter):
   (a) Ogre .mesh/.skeleton binary reader in python (reference /root/KenshiFP/client/kfp_meshray.h, read-only), reading
   from the game install at runtime (never commit assets); (b) drive/replay adapter option to dump full bone world
   transforms per frame (arms + Prop1/Prop2) so meshes can be skinned; (c) software rasteriser (numpy) of arm +
   weapon meshes from the eye, frames -> MP4 (ffmpeg in WSL if present); (d) side-by-side vs a real game frame from an
   existing recording (copy out of C:\KenshiTestRuns, never modify there); (e) tests, USAGE section, tag animlab-p3.
2. Open: sword drive @6c9516b mismatch (see Results); L/R asymmetry in dualwield-alternate.

## How to resume
Read this file, `git log -- tools/animlab docs/animlab tests/animlab` in the harness repo and
`git log -- components/KenshiFP/animlab` in C:\KenshiModding. Run regress.sh (must be ALL PASS). Continue at "Next steps".
Gotchas: Git Bash: MSYS_NO_PATHCONV=1 + `wsl.exe ... -- bash -s <<'EOF'` heredocs (wsl.exe expands `$VAR` in -c args);
never run Windows `python` (hangs). Other agents (sword fixer) commit to tools/animlab too: commit only your files.
