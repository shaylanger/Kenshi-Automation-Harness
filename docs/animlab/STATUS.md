# Animation lab: status (durable state)

Owner: animation-lab builder agent (ordered by Shay, 2026-10-09). This file + git are the
only state. A fresh agent resumes from here (see "How to resume").

## Goal
An offline animation lab for Kenshi first-person viewmodels, built in 3 phases:
1. **REPLAY** (urgent): feed recorded per-frame bone/camera data from the game (KenshiFP `rec`
   recordings from fp-viewmodel.sh / VMQUICK) into the REAL KenshiFP viewmodel solver, compiled
   offline (g++ in WSL), and print the in-game vmcheck metrics per state; variants (tunable
   overrides + patched source) run in parallel, one compact comparison table. Faithfulness gate:
   >= 2 recordings reproduce in-game values within a stated tolerance.
2. **METRICS LAB**: author new motions (time-keyed hand/weapon targets, JSON) on Kenshi's real
   skeleton through the solver; same metrics + reach limits + weapon/weapon and weapon/camera
   intersection.
3. **VISUAL LAB**: render arms + weapon meshes (Ogre mesh/skeleton read from the game install at
   runtime) to frames/MP4 offline; validated by a side-by-side vs a real game frame.

## Split (decision)
- Public harness repo (`tools/animlab/`, `docs/animlab/`): generic code only (rec parser,
  metrics, runner, variant table, authoring, renderer). No KenshiFP source, no game assets.
- Workspace repo `C:\KenshiModding\components\KenshiFP\animlab\`: the KenshiFP solver adapter
  (C++ shim + stubs + build script) compiled against a COPY of `/root/KenshiFP/client`
  (`/root/animlab-kfp-src`, rsync read-only). The harness runner calls the adapter binary as a
  subprocess.

## Phase plan / current phase
- [ ] P1 replay: STARTED (2026-10-09)
- [ ] P2 metrics lab
- [ ] P3 visual lab

## Decisions
(see Split)

## Next steps
1. Study kfp_viewmodel.inc inputs/outputs and the rec format; pick 2+ recordings.

## File map
- docs/animlab/STATUS.md (this file)

## How to resume
Read this file, `git log -- tools/animlab docs/animlab` in the harness repo and
`git log -- components/KenshiFP/animlab` in C:\KenshiModding. Continue at "Next steps".
