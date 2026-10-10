# Animation lab: setup misses (take / setup flaws)

Companion of STATUS.md "Misses" (pose flaws the lab missed). A setup miss = a take that was filmed or judged although its
setup was wrong (night, wrong cwd, unloaded crossbow, cursor, wall, bystanders, black frames, ...). Standing order (Shay
via coordinator, 2026-10-10): every setup miss becomes a check in the shared take preflight
`components/KenshiFP/tests/ingame/take-preflight.sh` (KenshiModding repo) that would have stopped the take BEFORE filming
with `RESULT <row> FAIL setup: <reason>`, or, when it can only be seen after filming, a post-take check (takecheck.py /
frames.py) named here. Review flaws of the setup class are appended automatically by
`tools/automation/review-verdict.ps1` (KenshiModding) as `PENDING (review)` rows.

Installed 2026-10-10 (KenshiModding 8352239/19d4b25); wired into fp-zoom-sweep.sh, fp-block-guard.sh, fp-e6-strokes.sh.

Format: date | point | what the take showed | take / evidence | build | status (check that catches it now) found:lab|review|shay|game
(`found:` = who saw it first, read by the catch-rate ledger `components/KenshiFP/animlab/ledger.py`).

- 2026-10-10 | kfx-b1 zoom-sweep "setup: sky" | take refused at night (game hour outside the day window), the batch lost the slot | kfx-b1 (cleaned) | - | CHECK: `pf_day` (50x to 10-13 h, verified, then a clear-sky screenshot test); part of `pf_all` found:game
- 2026-10-10 | kfx-b2 zoom-sweep 4 failed takes | `mkdir: cannot create directory .../kfx-b2/zs: File exists`: the out dir was unusable, the script did not stop, every take wrote its .out nowhere (`line 15: zs-switch-on.out: No such file or directory`) and was retried unchanged 4 times | C:\KenshiTestRuns\kfx-b2\zs.txt, excerpts\zs.txt | - | CHECK: `pf_outdir <dir>` (created, a directory, writable); unchanged retries are a script bug (CLAUDE.md test efficiency) found:game
- 2026-10-10 | T6 take with no RESULT line | f36/take5.sh exited 0 without a RESULT/VERDICT line (batch: `RESULT t6 FAIL no RESULT/VERDICT line`) | C:\KenshiTestRuns\kfx-b2\t6.txt | - | CHECK: `pf_begin <row>` EXIT guard prints `RESULT <row> FAIL setup: take script ended without a RESULT line (exit N)` unless `pf_result` ran found:game
- 2026-10-10 | crossbow unloaded: "Crossbow aim (RMB)" was a reload | zoom-sweep label said aim, the game reloaded an empty crossbow | corpus kept/vm-rework_zoom-sweep.mp4 | 550d5ba era | CHECK: `pf_weapon crossbow` (`pf_ready` + `pf_loaded` via `fp_combat state` loaded>=1); post-take: takecheck `pre ... loaded>=1` found:review
- 2026-10-10 | mouse cursor in frame | Windows cursor in sword-z25-block (~7 s, 12-16 s, 35-36 s) | corpus takes/videos/sword-z25-block-f36.mp4 | - | CHECK: `pf_open` clip runs `frames.py cursor`; post-take: `takecheck --video` (regress 27, mutation vid-cursor-overlay) found:shay
- 2026-10-10 | steep slope / wall in frame | sword-z25-block: slope fills most of the frame for the first half; the ray-clearance setup check had passed | corpus takes/videos/sword-z25-block.mp4 | - | CHECK: `pf_open` (frames.py openground on a pre-take clip); post-take regress 24 found:review
- 2026-10-10 | combat / bystanders in the take | turret-fp: "Tassilo is attacking!", blood pool; refilm: hungry-bandit group walks in | corpus takes/t6old, t6rev | - | CHECK: `pf_clean` (pin + KO within 3000) then `pf_area` (3 sampler rounds: near=0 down=0 msgs=0); post-take takecheck forbid (mutations take-bystander, take-combat-message) found:review
- 2026-10-10 | video past the end label | turret-fp refilm ran 7.5 s past `end` | corpus takes/t6rev | - | POST-TAKE ONLY (cannot be seen before filming): takecheck `end` (mutation take-video-past-end); take scripts stop the recorder at the `end` label found:review
- 2026-10-10 | display sleep -> black frames | display sleeps after 60 min without input, gdigrab records black (HANDOFF gotcha) | - | - | CHECK: `pf_display` (tools/automation/display-keeper.ps1 heartbeat < 60 s, started when down) + `pf_open` min luma (YAVG >= 35; mutations vid-black-frames / vid-dark-night) found:game
- 2026-10-09 | game rendered at 958x510 | windowed game on DISPLAY2 rescaled by DPI, screenshots/takes not 1600x900 (kenshi-ctl.ps1 fit) | - | - | CHECK: `pf_rig` (harness screenshot size = RES_W x RES_H, ffmpeg present, harness answers) found:game

Wiring: `pf_all <me> <x> <z> sword|crossbow [allow]` runs rig, display, day, clean, area, weapon, open in that order.
Take scripts call `pf_begin <row>` + `pf_outdir <out>` first and `pf_all` right before the recorder starts.
- 2026-10-10 | 4080 takes with no capture | the 4080 had no Active user session (Shay not logged in / RDP closed): gdigrab grabbed nothing or black, takes could not film | 4080-filming handoff | - | CHECK: `pf_rig` calls `rig_preflight` (tools/automation/rig-env.sh: quser Active + C:\KAH\display-check.ps1 LIVE) -> `RESULT <row> FAIL setup: 4080 session not active` found:game
