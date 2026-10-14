# Sparse third-person skeletal keyframes

This additive authoring/player tool is independent of KenshiFP's screen-space weapon keys. The latter drives FP arm IK; these keys drive named native skeletal bones in local bind-relative space. No game installation, GPU kernels, live tables, IK parameter sweeps or videos are involved.

Run from the harness root with WSL Python (numpy and Pillow installed). Replace BANK, KEYS, CFG and OUT with absolute private paths. The current dual-wield v23 banks remain read-only diagnostic inputs.

```sh
python3 tools/animlab/keyframes3p.py validate KEYS --skeleton BANK
python3 tools/animlab/keyframes3p.py render KEYS --skeleton BANK --config CFG -o OUT/preview --keys-only
python3 tools/animlab/keyframes3p.py sample KEYS --skeleton BANK --fps 144 -o OUT/poses.json
python3 tools/animlab/keyframes3p.py render KEYS --skeleton BANK --config CFG --fps 30 -o OUT/dense
python3 tools/animlab/keyframes3p.py export KEYS --skeleton BANK -o OUT/authored.skeleton
python3 tools/animlab/keyframes3p.py import --skeleton BANK --clip DW_Strike_L --fps 144 --angle .002 --distance .002 --scale-error .00001 -o OUT/strike-L.keys.json
python3 tests/animlab/test_keyframes3p.py
```

`render --keys-only` renders the union of authored times and endpoints once, making quick authoring previews cheap. `render --fps` renders the union of those keys and the native uniform endpoint-inclusive schedule. `sample --fps` emits dense bone world transforms. The library API `animation(doc, sk)` feeds existing native body/contact/edge/transition validators directly; `sample(doc,sk,t)` is clamped, never looping. Neither preview nor RESULT PASS means visual acceptance. Dense checks between keys, transitions, and actual frame review remain required.

## Format

```json
{
  "schema": "animlab.3p.keys.v1",
  "name": "DW_Example",
  "duration": 0.8,
  "units": "dm",
  "omitted": "bind",
  "tracks": {
    "Bip01 L Forearm": {
      "keys": [
        {"t": 0, "q": [1, 0, 0, 0], "p": [0, 0, 0]},
        {"t": 0.4, "q": [0.9238795325, 0, 0, 0.3826834324], "p": [0, 0, 0]},
        {"t": 0.8, "q": [1, 0, 0, 0], "p": [0, 0, 0]}
      ]
    }
  }
}
```

Times are seconds in [0,duration], strictly increasing, including after float32 export. Each bone can have independent sparse times; one key holds. No arbitrary six-key cap applies to a full body. Quaternions are unit [w,x,y,z], interpolated using Ogre shortest-path normalized linear interpolation. Translation is linear. Optional `s` is a positive three-component multiplier, default [1,1,1]. Runtime local position = bind position + p; local quaternion = bind quaternion * q; scale = bind scale * s. Values before/after a track hold its first/last key. Units are decimetres.

Omitted bones explicitly retain their native bind local transforms and follow their animated parents. This is NOT a live locomotion preservation policy. Runtime composition with incoming locomotion uses the separate existing blend/support gates. No easing or spline overshoot is hidden; to express a eased swing add deliberate authored timing knots. Unknown fields, duplicate JSON fields, nonfinite values, unknown bones, malformed hierarchy, nonunit rotations, invalid scales/times are rejected.

A single named-bone motion maps onto both rigs' own bind transforms. Same authored deltas do not guarantee identical world paths; run compatibility/contact/anatomy tests on both body meshes. Separate banks can be exported as packaging needs, without inventing separate fighting styles.

## Calibrated hand attachments

Optional top-level `attachments` is a list. Each entry contains exactly `name, bone, mesh, mesh_sha256, q, p, scale`. Example:

```json
{
  "name": "R",
  "bone": "Bip01 R Hand",
  "mesh": "/absolute/path/katana05_bare.mesh",
  "mesh_sha256": "REPLACE_WITH_ACTUAL_64_LOWERCASE_HEX_SHA256",
  "q": [1, 0, 0, 0],
  "p": [0, 0, 0],
  "scale": [1, 1, 1]
}
```

This example is structural, NOT a usable grip calibration. Supply the verified hand-local rotation and offset per actual rig/model. Alternatively attach to a native Prop bone whose verified parent is the hand and whose bind/animated transform already supplies that calibration. Matrix relationship: local vertex = rotation(q) * (mesh vertex * item scale) + p; world vertex = bone position + bone rotation * (bone derived scale * local vertex). Mesh paths relative to KEYS are allowed. Use actual drawn/bare weapon geometry and actual FCS item scale; never substitute sheathed meshes.

Body config is the existing native.json style: game_dir, skeleton, body_meshes, bones L/R lists with Prop names, fov_3p, colors. CPU full-body rendering uses native weighted skinning and the existing rasterizer. It shares one depth buffer for both props and body and frames actual vertices. Source meshes are read once per distinct path/hash, local attachment geometry once per calibration, then transformed per pose. Hashes are checked after rendering; sampling.json pins source skeleton, keys, body/config/prop files, tool, images/times and states visual_acceptance=false. Raw source fingers are rendered; this tool does NOT install or automatically select a privately fitted finger mesh. The dual-wield fitted-body reviewer remains the acceptance renderer.

## Import/reduction and provenance

Import reads an existing Ogre clip without altering it. Deterministic worst-error insertion retains original endpoints/necessary knots, testing original knot times plus the requested uniform schedule. It reduces authored DATA, not validation coverage, and is not a parameter/grid search. The .reduction.json reports original/reduced counts and sampled local angle, translation and scale errors. Tolerances are radians, dm and dimensionless scale. Additive-base clips are rejected. This sampled local bound is not a continuous mathematical guarantee or world-space collision guarantee: errors accumulate through the hierarchy.

Read-only v23 Strike_L diagnostic: 4,770 original keys per rig reduced to 847 male / 982 female with .002rad/.002dm/.00001 limits, 144FPS samples. Export/reader maximum world-position roundtrip discrepancy was 3.31e-7dm. Reduced motion differed from original by up to .02084dm (~2.1mm); such changes can break tight grip/contact clearance. These converted files need new full QA and are NOT accepted mod replacements.

Export produces a native Ogre v1.80 skeleton with original rig bindings and this one clip; it does not merge or install into native banks. CLI refuses source author/skeleton overwrite, including symlink/hardlink aliases. All CLI inputs are rehashed after work. Shared harness additions are applied with the separate manifest checker; no existing file is replaced.

Next speed improvement: author or edit a handful of meaningful pose/timing knots, preview keys only, then reuse the existing strict validators on dense interpolated poses. Content-addressed validator results can reuse unchanged clip/rig/model combinations; do not cache review acceptance across changed hashes.

## Lossless adoption before editing

Use this mode first when adopting existing v23 motion. It preserves ALL original decoded local key times/quaternion/translation/scale values; it does not compress, normalize, retime or change motion. All omitted-bind and strict schema checks still apply. Source banks remain untouched. Separate acceptance of the original candidate is still pending.

```sh
python3 tools/animlab/keyframes3p.py import --skeleton BANK --clip DW_Strike_L --lossless -o OUT/strike-L.lossless.keys.json
python3 tools/animlab/keyframes3p.py export OUT/strike-L.lossless.keys.json --skeleton BANK -o OUT/strike-L.lossless.skeleton
```

Lossless key times can be numerous; keys-only previews are fastest for NEW sparse authored motion. Preserve originals and edit only the intended bone/timing knots, then rerun the relevant full validation. Compression remains opt-in and its reduction diagnostics confer no acceptance.

## Multi-clip bank export

`export_bank(docs,sk,output)` validates every clip against the same rig, rejects duplicate animation names, preserves original rig binds, and writes all clips into one Ogre skeleton. CLI adds any number of `--clip-json` arguments, protecting/rechecking every author input.

```sh
python3 tools/animlab/keyframes3p.py export OUT/idle.keys.json --clip-json OUT/strike-R.keys.json --clip-json OUT/strike-L.keys.json --skeleton BANK -o OUT/combined.skeleton
```

Each clip has one motion definition. Same-named clips cannot silently replace one another. For all11 dual-wield clips use the lossless diagnostic directory's per-clip JSONs and export_bank; this packaging step does not change native load order or certify runtime integration.
