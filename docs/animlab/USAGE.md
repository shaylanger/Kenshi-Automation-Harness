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

## Regression (run before every animlab commit)

`bash components/KenshiFP/animlab/regress.sh` (WSL): offline unit tests, the gate above, and the native round trip.
Unit tests only: `python3 tests/animlab/test_animlab.py`. Phase 1 is tagged `animlab-p1`.
