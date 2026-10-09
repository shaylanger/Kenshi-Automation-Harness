#!/usr/bin/env python3
"""Offline tests for tools/animlab/visual (phase 3, VISUAL LAB): Ogre .mesh/.skeleton reader on synthetic binaries
written here, the rasteriser, and rig posing (bind joints in = bind mesh out, weapon on the prop pose, left-side
prop mirror). No game install, no assets. Run: python3 tests/animlab/test_visual.py (exit 0 = all pass)."""
import json, math, os, struct, subprocess, sys, tempfile, unittest

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
VIS = os.path.join(HERE, '..', '..', 'tools', 'animlab', 'visual')
sys.path.insert(0, VIS)
sys.path.insert(0, os.path.dirname(VIS))
import ogre  # noqa: E402
import render  # noqa: E402


def chunk(cid, body):
    return struct.pack('<HI', cid, 6 + len(body)) + body


def write_mesh(path, pos, tris, bw):
    """one submesh, own geometry, FLOAT3 positions, 16-bit indices, bone assignments [(v, bone, w)]."""
    pos = np.asarray(pos, '<f4'); idx = np.asarray(tris, '<u2').ravel()
    decl = chunk(ogre.M_GEOMETRY_VERTEX_DECLARATION,
                 chunk(ogre.M_GEOMETRY_VERTEX_ELEMENT, struct.pack('<5H', 0, 2, ogre.VES_POSITION, 0, 0)))
    vbuf = chunk(ogre.M_GEOMETRY_VERTEX_BUFFER, struct.pack('<HH', 0, 12) +
                 chunk(ogre.M_GEOMETRY_VERTEX_BUFFER_DATA, pos.tobytes()))
    geom = chunk(ogre.M_GEOMETRY, struct.pack('<I', len(pos)) + decl + vbuf)
    sub = b'mat\n' + struct.pack('<BIB', 0, len(idx), 0) + idx.tobytes() + geom + \
        chunk(ogre.M_SUBMESH_OPERATION, struct.pack('<H', 4)) + \
        b''.join(chunk(ogre.M_SUBMESH_BONE_ASSIGNMENT, struct.pack('<IHf', v, b, w)) for v, b, w in bw)
    mesh = chunk(ogre.M_MESH, b'\x01' + chunk(ogre.M_SUBMESH, sub))
    with open(path, 'wb') as f:
        f.write(struct.pack('<H', ogre.M_HEADER) + b'[MeshSerializer_v1.100]\n' + mesh)


def write_skeleton(path, bones):
    """bones: [(name, handle, parent, pos, (w,x,y,z))]; Ogre's bone chunk size leaves out the name string."""
    out = struct.pack('<H', ogre.M_HEADER) + b'[Serializer_v1.80]\n'
    for name, h, par, p, q in bones:
        w, x, y, z = q
        body = struct.pack('<H3f4f3f', h, *p, x, y, z, w, 1, 1, 1)
        out += struct.pack('<HI', ogre.SK_BONE, 6 + len(body)) + name.encode() + b'\n' + body
    for name, h, par, p, q in bones:
        if par >= 0:
            out += chunk(ogre.SK_BONE_PARENT, struct.pack('<HH', h, par))
    with open(path, 'wb') as f:
        f.write(out)


FLIPY = (0.0, 0.0, 1.0, 0.0)   # 180 deg about Y: left-side bones point along -X
BONES = [('Bip01', 0, -1, (0, 0, 0), (1, 0, 0, 0)),
         ('R Clav', 1, 0, (0.5, 1, 0), (1, 0, 0, 0)), ('R UA', 2, 1, (0.5, 0, 0), (1, 0, 0, 0)),
         ('R FA', 3, 2, (1, 0, 0), (1, 0, 0, 0)), ('R Hand', 4, 3, (1, 0, 0), (1, 0, 0, 0)),
         ('Prop2', 5, 4, (0.5, 0, 0), (1, 0, 0, 0)),
         ('L Clav', 6, 0, (-0.5, 1, 0), FLIPY), ('L UA', 7, 6, (0.5, 0, 0), (1, 0, 0, 0)),
         ('L FA', 8, 7, (1, 0, 0), (1, 0, 0, 0)), ('L Hand', 9, 8, (1, 0, 0), (1, 0, 0, 0)),
         ('Prop1', 10, 9, (0.5, 0, 0), (1, 0, 0, 0))]


class Fixture:
    def __init__(self, d):
        self.d = d
        write_skeleton(os.path.join(d, 'sk.skeleton'), BONES)
        # arm boxes-ish: one triangle per arm segment, each vertex fully weighted to its bone
        P, T, BW = [], [], []
        for side, (ua, fa, ha), sx in (('R', (2, 3, 4), 1), ('L', (7, 8, 9), -1)):
            for b, x0 in ((ua, 1.2), (fa, 2.2), (ha, 3.2)):
                k = len(P)
                P += [(sx * x0, 0.9, 0.1), (sx * (x0 + 0.5), 0.9, 0.1), (sx * (x0 + 0.25), 1.1, 0.1)]
                T.append((k, k + 1, k + 2)); BW += [(k + i, b, 1.0) for i in range(3)]
        self.body_pos = np.array(P, float)
        write_mesh(os.path.join(d, 'body.mesh'), P, T, BW)
        write_mesh(os.path.join(d, 'w.mesh'), [(0, 0, 0), (1, 0, 0), (0, 0.1, 0)], [(0, 1, 2)], [])
        self.cfg = dict(game_dir=d, skeleton='sk.skeleton', body_mesh='body.mesh',
                        weapon_mesh={'R': 'w.mesh', 'L': 'w.mesh'}, weapon_sides=['R'], prop_axes=[[1, 2]],
                        prop_local_q={'0': [1, 0, 0, 0]}, prop_roll_deg={'0': 0},
                        bones={'R': ['R Clav', 'R UA', 'R FA', 'R Hand', 'Prop2'],
                               'L': ['L Clav', 'L UA', 'L FA', 'L Hand', 'Prop1']},
                        fov=[1.0, 1.0], near=0.1)

    def bind_frame(self):
        """joints at the bind pose, in camera numbers (x flipped)."""
        F = render.FLIP
        sk = ogre.load_skeleton(os.path.join(self.d, 'sk.skeleton'))
        j = lambda n: sk.by_name[n].dpos * F
        sides = {s: dict(sh=j(s + ' UA'), el=j(s + ' FA'), wr=j(s + ' Hand')) for s in 'LR'}
        return dict(t=0.0, i=0, cls=0, up=np.array([0, 1.0, 0]), sides=sides)


class TestOgre(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.fx = Fixture(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_mesh_roundtrip(self):
        m = ogre.load_mesh(os.path.join(self.fx.d, 'body.mesh'))
        (P, N, T, BW), = list(m.triangles())
        self.assertEqual(P.shape, (18, 3)); self.assertEqual(T.shape, (6, 3)); self.assertIsNone(N)
        np.testing.assert_allclose(P, self.fx.body_pos, atol=1e-6)
        self.assertEqual(len(BW), 18); self.assertEqual(BW[3], (3, 3, 1.0))

    def test_skeleton_derived(self):
        sk = ogre.load_skeleton(os.path.join(self.fx.d, 'sk.skeleton'))
        self.assertEqual(len(sk.bones), 11)
        np.testing.assert_allclose(sk.by_name['R Hand'].dpos, (3, 1, 0), atol=1e-6)
        np.testing.assert_allclose(sk.by_name['L Hand'].dpos, (-3, 1, 0), atol=1e-6)   # parent rotation applied
        np.testing.assert_allclose(ogre.qmat(sk.by_name['L FA'].dq)[:, 0], (-1, 0, 0), atol=1e-6)
        self.assertEqual([c.name for c in sk.children(4)], ['Prop2'])

    def test_quat(self):
        q = np.array([math.cos(math.pi / 4), 0, 0, math.sin(math.pi / 4)])   # 90 deg about Z
        np.testing.assert_allclose(ogre.qrot(q, (1, 0, 0)), (0, 1, 0), atol=1e-9)
        np.testing.assert_allclose(ogre.qmul(q, ogre.qconj(q)), (1, 0, 0, 0), atol=1e-9)


class TestRaster(unittest.TestCase):
    def test_triangle_and_depth(self):
        V = np.array([[-1, -1, 4], [1, -1, 4], [0, 1, 4], [-1, -1, 2], [1, -1, 2], [0, 1, 2], [0, 0, 0.05]], float)
        T = np.array([[0, 1, 2], [3, 4, 5]]); part = np.array([0, 1])
        img, mask, _ = render.raster(V, T, part, (64, 64), (1.0, 1.0), 0.1, [[255, 0, 0], [0, 0, 255]])
        self.assertEqual(mask[32, 32], 1)          # nearer weapon triangle wins the z test
        self.assertEqual(mask[2, 2], -1)
        self.assertGreater((mask == 1).sum(), (mask == 0).sum())
        img2, mask2, _ = render.raster(V, np.array([[0, 1, 6]]), np.array([0]), (64, 64), (1.0, 1.0), 0.1,
                                       [[255, 0, 0]])
        self.assertEqual((mask2 >= 0).sum(), 0)     # behind the near plane: culled


class TestRig(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.fx = Fixture(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_bind_identity(self):
        rig = render.Rig(self.fx.cfg)
        V, T, part = rig.geometry(self.fx.bind_frame())
        self.assertEqual(len(T), 6)
        np.testing.assert_allclose(V[:18], self.fx.body_pos * render.FLIP, atol=1e-6)

    def test_bent_elbow_keeps_lengths(self):
        rig = render.Rig(self.fx.cfg); f = self.fx.bind_frame()
        f['sides']['R']['wr'] = f['sides']['R']['el'] + np.array([0, 0, 1.0])   # forearm turned forward
        V, _, _ = rig.geometry(f)
        hand = V[6:9]   # R hand triangle follows the wrist
        self.assertLess(np.linalg.norm(hand[0] - (f['sides']['R']['wr'] + np.array([0, -0.1, 0.2]))), 0.5)
        np.testing.assert_allclose(np.linalg.norm(V[4] - V[3]), 0.5, atol=1e-6)   # rigid segment

    def test_weapon_on_prop_and_mirror(self):
        Q = np.array([0.8, 0.3, 0.4, 0.2]); Q = Q / np.linalg.norm(Q)
        cfg = dict(self.fx.cfg, weapon_sides=['R', 'L'],
                   prop_local_q={"0": list(Q)},
                   prop_mirror={'L': {'q_sign': [1, -1, -1, 1], 'roll_sign': 1}})
        rig = render.Rig(cfg); f = self.fx.bind_frame()
        fw, up = np.array([0, 0, 1.0]), np.array([0, 1.0, 0])
        Rl = ogre.qmat(Q)
        for s in 'RL':
            d = f['sides'][s]
            d.update(pp=d['wr'] + fw, pf=fw, pu=up)
        # measured hand X = prop pose x prop_local^-1 (camera numbers); L uses the mirrored local
        Rp = np.column_stack([fw, up, np.cross(fw, up)])
        f['sides']['R']['hx'] = (Rp @ Rl.T)[:, 0] * render.FLIP
        RlL = ogre.qmat(Q * np.array([1, -1, -1, 1]))
        f['sides']['L']['hx'] = (Rp @ RlL.T)[:, 0] * render.FLIP
        err = rig.hand_x_err(f)
        self.assertLess(err['R'], 0.01); self.assertLess(err['L'], 0.01)
        V, T, part = rig.geometry(f)
        self.assertEqual(int(part.sum()), 2)
        W = V[18:]
        np.testing.assert_allclose(W[0], f['sides']['R']['pp'], atol=1e-6)   # weapon origin on the prop point
        np.testing.assert_allclose(W[1] - W[0], (Rp @ np.eye(3))[:, 0] * render.FLIP, atol=1e-6)                # mesh X = prop forward axis
        cfg['prop_mirror'] = None
        self.assertGreater(render.Rig(cfg).hand_x_err(f)['L'], 1.0)          # without the mirror the L hand is off


class TestCli(unittest.TestCase):
    def test_frames_cli(self):
        with tempfile.TemporaryDirectory() as d:
            fx = Fixture(d)
            cfgp = os.path.join(d, 'cfg.json'); 
            with open(cfgp, "w") as fh:
                json.dump(fx.cfg, fh)
            f = fx.bind_frame()['sides']
            v = lambda a: '%.4f,%.4f,%.4f' % tuple(a)
            st = os.path.join(d, 'state.txt')
            with open(st, "w") as fh:
                fh.write('vm ' + ' '.join('%s%s=%s' % (s, k, v(f[s][k])) for s in 'LR' for k in ('sh', 'el', 'wr')) +
                                ' mp=%s mf=0,0,1 mu=0,1,0\n' % v(f['R']['wr'] + np.array([0, 0, 1.0])))
            r = subprocess.run([sys.executable, os.path.join(VIS, 'render.py'), 'still', st, '--config', cfgp,
                                '-o', os.path.join(d, 'o.png'), '--size', '64x36', '--weapons', 'R'],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(os.path.getsize(os.path.join(d, 'o.png')) > 0)


if __name__ == '__main__':
    unittest.main(verbosity=1)
