"""ogre.py -- minimal reader for Ogre binary .mesh (MeshSerializer v1.8-v1.100) and .skeleton (v1.8x) files.

Reads only what the visual lab needs: per submesh positions, normals, triangle indices, bone assignments; skeleton
bones (name, handle, parent, bind local position/orientation/scale) with derived (model space) bind transforms.
Files are read at run time from a game install; nothing here ships assets.
Quaternions are (w, x, y, z) numpy arrays; positions numpy float32/float64 arrays.
"""
import struct

import numpy as np

# chunk ids (OgreMeshFileFormat.h / OgreSkeletonFileFormat.h)
M_HEADER, M_MESH, M_SUBMESH, M_SUBMESH_OPERATION, M_SUBMESH_BONE_ASSIGNMENT, M_SUBMESH_TEXTURE_ALIAS = \
    0x1000, 0x3000, 0x4000, 0x4010, 0x4100, 0x4200
M_GEOMETRY, M_GEOMETRY_VERTEX_DECLARATION, M_GEOMETRY_VERTEX_ELEMENT, M_GEOMETRY_VERTEX_BUFFER, \
    M_GEOMETRY_VERTEX_BUFFER_DATA = 0x5000, 0x5100, 0x5110, 0x5200, 0x5210
M_MESH_SKELETON_LINK, M_MESH_BONE_ASSIGNMENT, M_MESH_BOUNDS = 0x6000, 0x7000, 0x9000
SK_BONE, SK_BONE_PARENT, SK_ANIMATION, SK_ANIMATION_LINK = 0x2000, 0x3000, 0x4000, 0x5000
VES_POSITION, VES_NORMAL = 1, 4
VET_SIZE = {0: 4, 1: 8, 2: 12, 3: 16, 4: 4, 5: 2, 6: 4, 7: 6, 8: 8, 9: 4, 10: 4, 11: 4, 12: 8, 13: 12, 14: 16}


class _R:
    def __init__(self, data):
        self.d, self.p = data, 0

    def u8(self):
        v = self.d[self.p]; self.p += 1; return v

    def u16(self):
        v = struct.unpack_from('<H', self.d, self.p)[0]; self.p += 2; return v

    def u32(self):
        v = struct.unpack_from('<I', self.d, self.p)[0]; self.p += 4; return v

    def f32(self, n):
        v = struct.unpack_from('<%df' % n, self.d, self.p); self.p += 4 * n; return v

    def s(self):
        e = self.d.index(b'\n', self.p)
        v = self.d[self.p:e].decode('latin-1'); self.p = e + 1; return v

    def chunk(self):
        """(id, end offset) or None at end; chunk length includes the 6-byte header."""
        if self.p + 6 > len(self.d):
            return None
        cid = self.u16(); ln = self.u32()
        return cid, self.p - 6 + ln


class SubMesh:
    def __init__(self):
        self.material, self.shared, self.idx, self.op = '', False, None, 4
        self.pos = self.nrm = None
        self.bw = []   # (vertex, bone handle, weight)


class Mesh:
    def __init__(self):
        self.subs, self.skeleton, self.shared_pos, self.shared_nrm, self.shared_bw = [], None, None, None, []

    def triangles(self):
        """yield (positions Nx3, normals Nx3 or None, tris Mx3 int, [(v, bone, w)]) per triangle-list submesh."""
        for s in self.subs:
            if s.op != 4 or s.idx is None:
                continue
            P, N, B = (self.shared_pos, self.shared_nrm, self.shared_bw) if s.shared else (s.pos, s.nrm, s.bw)
            if P is None:
                continue
            yield P, N, s.idx.reshape(-1, 3), B


def _geometry(r, end):
    nv = r.u32()
    elems, bufs = [], {}
    while r.p < end:
        c = r.chunk()
        if c is None:
            break
        cid, cend = c
        if cid == M_GEOMETRY_VERTEX_DECLARATION:
            while r.p < cend:
                c2 = r.chunk(); cid2, cend2 = c2
                if cid2 == M_GEOMETRY_VERTEX_ELEMENT:
                    src, typ, sem, off, ix = r.u16(), r.u16(), r.u16(), r.u16(), r.u16()
                    elems.append((src, typ, sem, off, ix))
                r.p = cend2
        elif cid == M_GEOMETRY_VERTEX_BUFFER:
            bind, vsize = r.u16(), r.u16()
            c2 = r.chunk()
            if c2 and c2[0] == M_GEOMETRY_VERTEX_BUFFER_DATA:
                bufs[bind] = (vsize, r.d[r.p:r.p + nv * vsize])
        r.p = cend
    out = {}
    for src, typ, sem, off, ix in elems:
        if sem in (VES_POSITION, VES_NORMAL) and ix == 0 and src in bufs and typ == 2:   # FLOAT3
            vsize, raw = bufs[src]
            a = np.frombuffer(raw, dtype=np.uint8).reshape(nv, vsize)[:, off:off + 12].copy().view('<f4').reshape(nv, 3)
            out[sem] = a.astype(np.float64)
    return out.get(VES_POSITION), out.get(VES_NORMAL)


def load_mesh(path):
    with open(path, 'rb') as f:
        r = _R(f.read())
    if r.u16() != M_HEADER:
        raise ValueError('%s: not an Ogre mesh' % path)
    ver = r.s()
    m = Mesh(); m.version = ver
    c = r.chunk()
    if not c or c[0] != M_MESH:
        raise ValueError('%s: no M_MESH chunk' % path)
    mend = c[1]
    r.u8()   # skeletally animated
    while r.p < mend:
        c = r.chunk()
        if c is None:
            break
        cid, cend = c
        if cid == M_SUBMESH:
            s = SubMesh()
            s.material = r.s(); s.shared = bool(r.u8())
            ni = r.u32(); wide = bool(r.u8())
            dt = '<u4' if wide else '<u2'
            s.idx = np.frombuffer(r.d, dtype=dt, count=ni, offset=r.p).astype(np.int64); r.p += ni * (4 if wide else 2)
            while r.p < cend:
                c2 = r.chunk()
                if c2 is None:
                    break
                cid2, cend2 = c2
                if cid2 == M_GEOMETRY:
                    s.pos, s.nrm = _geometry(r, cend2)
                elif cid2 == M_SUBMESH_OPERATION:
                    s.op = r.u16()
                elif cid2 == M_SUBMESH_BONE_ASSIGNMENT:
                    s.bw.append((r.u32(), r.u16(), r.f32(1)[0]))
                r.p = cend2
            m.subs.append(s)
        elif cid == M_GEOMETRY:
            m.shared_pos, m.shared_nrm = _geometry(r, cend)
        elif cid == M_MESH_SKELETON_LINK:
            m.skeleton = r.s()
        elif cid == M_MESH_BONE_ASSIGNMENT:
            m.shared_bw.append((r.u32(), r.u16(), r.f32(1)[0]))
        r.p = cend
    return m


# ---------------- quaternion helpers (w, x, y, z) ----------------
def qmul(a, b):
    aw, ax, ay, az = a; bw, bx, by, bz = b
    return np.array([aw * bw - ax * bx - ay * by - az * bz, aw * bx + ax * bw + ay * bz - az * by,
                     aw * by - ax * bz + ay * bw + az * bx, aw * bz + ax * by - ay * bx + az * bw])


def qconj(q): return np.array([q[0], -q[1], -q[2], -q[3]])


def qmat(q):
    w, x, y, z = q / np.linalg.norm(q)
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
                     [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
                     [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)]])


def qrot(q, v): return qmat(q) @ np.asarray(v, dtype=float)


class Bone:
    def __init__(self, name, h, pos, q, scale):
        self.name, self.h, self.pos, self.q, self.scale, self.parent = name, h, np.array(pos), np.array(q), np.array(scale), -1
        self.dpos = self.dq = self.dscale = None


class Skeleton:
    def __init__(self):
        self.bones, self.by_name = {}, {}

    def derive(self):
        """bind-pose derived (model space) transforms, Ogre rules (inherit orientation + scale)."""
        done = set()

        def go(b):
            if b.h in done:
                return
            if b.parent >= 0:
                p = self.bones[b.parent]; go(p)
                b.dq = qmul(p.dq, b.q)
                b.dscale = p.dscale * b.scale
                b.dpos = p.dpos + qrot(p.dq, p.dscale * b.pos)
            else:
                b.dq, b.dscale, b.dpos = b.q.copy(), b.scale.copy(), b.pos.copy()
            done.add(b.h)
        for b in self.bones.values():
            go(b)
        return self

    def children(self, h):
        return [b for b in self.bones.values() if b.parent == h]


def load_skeleton(path):
    with open(path, 'rb') as f:
        r = _R(f.read())
    if r.u16() != M_HEADER:
        raise ValueError('%s: not an Ogre skeleton' % path)
    sk = Skeleton(); sk.version = r.s()
    while True:
        c = r.chunk()
        if c is None:
            break
        cid, cend = c
        if cid == SK_BONE:   # Ogre's bone chunk size leaves out the name: 6 + handle 2 + pos 12 + quat 16 [+ scale 12]
            size = cend - (r.p - 6)
            name = r.s(); h = r.u16()
            pos = r.f32(3); x, y, z, w = r.f32(4)
            scale = r.f32(3) if size >= 48 else (1.0, 1.0, 1.0)
            b = Bone(name, h, pos, (w, x, y, z), scale)
            sk.bones[h] = b; sk.by_name[name] = b
            continue
        elif cid == SK_BONE_PARENT:
            ch, par = r.u16(), r.u16()
            sk.bones[ch].parent = par
        r.p = cend
    return sk.derive()
