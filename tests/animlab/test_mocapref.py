#!/usr/bin/env python3
"""Offline tests for tools/animlab/mocapref.py (open mocap reference): BVH and ASF/AMC forward kinematics, first-person
view scaling, strike detection + measurements, swing-twist roll. Synthetic files written here; no mocap data.
Run: python3 tests/animlab/test_mocapref.py."""
import math, os, sys, tempfile, unittest

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'tools', 'animlab'))
import mocapref as MR  # noqa: E402

# Bandai-style skeleton (cm, Y up, actor faces +Z, right arm along -X)
JOINTS = [  # name, parent, offset
    ('Hips', None, (0, 100, 0)), ('Spine', 'Hips', (0, 10, 0)), ('Chest', 'Spine', (0, 20, 0)),
    ('Neck', 'Chest', (0, 20, 0)), ('Head', 'Neck', (0, 10, 0)),
    ('Shoulder_R', 'Chest', (-5, 15, 0)), ('UpperArm_R', 'Shoulder_R', (-12, 0, 0)), ('LowerArm_R', 'UpperArm_R', (-30, 0, 0)),
    ('Hand_R', 'LowerArm_R', (-25, 0, 0)),
    ('Shoulder_L', 'Chest', (5, 15, 0)), ('UpperArm_L', 'Shoulder_L', (12, 0, 0)), ('LowerArm_L', 'UpperArm_L', (30, 0, 0)),
    ('Hand_L', 'LowerArm_L', (25, 0, 0)),
    ('UpperLeg_R', 'Hips', (-10, 0, 0)), ('LowerLeg_R', 'UpperLeg_R', (0, -45, 0)), ('Foot_R', 'LowerLeg_R', (0, -45, 0)),
    ('Toes_R', 'Foot_R', (0, -5, 12)),
    ('UpperLeg_L', 'Hips', (10, 0, 0)), ('LowerLeg_L', 'UpperLeg_L', (0, -45, 0)), ('Foot_L', 'LowerLeg_L', (0, -45, 0)),
    ('Toes_L', 'Foot_L', (0, -5, 12)),
]
ENDS = {'Head', 'Hand_R', 'Hand_L', 'Toes_R', 'Toes_L'}


def write_bvh(path, elbow_deg, fps=60):
    """every joint: 3 rotation channels (Z X Y); root also position. elbow_deg[i] = LowerArm_R Y rotation per frame."""
    kids = {}
    for n, p, o in JOINTS:
        kids.setdefault(p, []).append(n)
    off = {n: o for n, p, o in JOINTS}
    out = []

    def emit(n, d):
        ind = '  ' * d
        out.append('%s%s %s' % (ind, 'ROOT' if d == 0 else 'JOINT', n)); out.append(ind + '{')
        out.append('%s  OFFSET %g %g %g' % ((ind,) + off[n]))
        out.append(ind + ('  CHANNELS 6 Xposition Yposition Zposition Zrotation Xrotation Yrotation' if d == 0 else
                          '  CHANNELS 3 Zrotation Xrotation Yrotation'))
        for c in kids.get(n, []):
            emit(c, d + 1)
        if n in ENDS:
            out.extend([ind + '  End Site', ind + '  {', ind + '    OFFSET 0 0 0', ind + '  }'])
        out.append(ind + '}')
    out.append('HIERARCHY'); emit('Hips', 0)
    names = []

    def order(n):
        names.append(n)
        for c in kids.get(n, []):
            order(c)
    order('Hips')
    out += ['MOTION', 'Frames: %d' % len(elbow_deg), 'Frame Time: %g' % (1.0 / fps)]
    for e in elbow_deg:
        v = []
        for n in names:
            if n == 'Hips':
                v += [0, 100, 0, 0, 0, 0]
            elif n == 'LowerArm_R':
                v += [0, 0, e]
            else:
                v += [0, 0, 0]
        out.append(' '.join('%g' % x for x in v))
    with open(path, 'w') as f:
        f.write('\n'.join(out) + '\n')


class TestBVH(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def test_fk_bind_and_elbow(self):
        p = os.path.join(self.d, 'a.bvh')
        write_bvh(p, [0, 90])
        c = MR.load(p)
        self.assertEqual(c.n, 2); self.assertAlmostEqual(c.fps, 60.0, 3)
        # bind: wrist = hips + spine + chest + shoulder + upper + lower offsets (m)
        np.testing.assert_allclose(c.p('Rwr')[0], np.array([-0.72, 1.45, 0.0]), atol=1e-6)
        # zero end site: continues the hand bone (40% of its offset)
        np.testing.assert_allclose(c.p('Rhand')[0] - c.p('Rwr')[0], [-0.10, 0, 0], atol=1e-6)
        # elbow 90 deg about Y: forearm turns into +/-Z, length kept
        fo = c.p('Rwr')[1] - c.p('Rel')[1]
        self.assertAlmostEqual(np.linalg.norm(fo), 0.25, 6); self.assertAlmostEqual(abs(fo[2]), 0.25, 6)

    def test_strike_detection(self):
        n, fps = 120, 60
        # rest bent 90 -> fast extension to 0 over 0.2 s at t=0.8 -> hold
        e = [90.0 if i < 48 else max(0.0, 90.0 - (i - 48) * 90.0 / 12) for i in range(n)]
        p = os.path.join(self.d, 'b.bvh'); write_bvh(p, e, fps)
        c = MR.load(p)
        rows = MR.strike_metrics(c, 'R', None, min_peak=1.0)[0]
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertGreater(r['elbow_ext'], 60.0)            # the arm opens in the stroke
        self.assertAlmostEqual(r['t_peak'], 0.9, delta=0.1)
        self.assertLess(r['wshare'], 0.05)                  # hand rigid on the forearm
        self.assertLess(r['torso_share'], 0.01)
        self.assertEqual(len(r['curve']), 21)


class TestASF(unittest.TestCase):
    def test_amc_chain(self):
        d = tempfile.mkdtemp()
        asf = os.path.join(d, '01.asf'); amc = os.path.join(d, '01_01.amc')
        with open(asf, 'w') as f:
            f.write(':version 1.10\n:name t\n:units\n  length 0.45\n  angle deg\n:root\n  order TX TY TZ RX RY RZ\n'
                    '  axis XYZ\n  position 0 0 0\n  orientation 0 0 0\n:bonedata\n  begin\n    id 1\n    name a\n'
                    '    direction 1 0 0\n    length 2\n    axis 0 0 0 XYZ\n    dof rz\n  end\n  begin\n    id 2\n    name b\n'
                    '    direction 1 0 0\n    length 1\n    axis 0 0 0 XYZ\n    dof rz\n  end\n:hierarchy\n  begin\n'
                    '    root a\n    a b\n  end\n')
        with open(amc, 'w') as f:
            f.write(':FULLY-SPECIFIED\n:DEGREES\n1\nroot 0 0 0 0 0 0\na 0\nb 90\n')
        c = MR.load_amc(amc)
        s = MR.CMU_SCALE
        np.testing.assert_allclose(c.P['a.end'][0], [2 * s, 0, 0], atol=1e-9)
        np.testing.assert_allclose(c.P['b.end'][0], [2 * s, 1 * s, 0], atol=1e-9)   # b turned 90 deg about Z


class TestTwist(unittest.TestCase):
    def test_twist_vs_swing(self):
        self.assertAlmostEqual(MR._twist(MR._rx(math.radians(30)), [1, 0, 0]), 30.0, 4)
        self.assertAlmostEqual(MR._twist(MR._ry(math.radians(30)), [1, 0, 0]), 0.0, 4)


if __name__ == '__main__':
    unittest.main()
