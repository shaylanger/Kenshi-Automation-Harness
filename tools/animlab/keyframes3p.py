#!/usr/bin/env python3
"""Sparse third-person local skeletal authoring. See docs/animlab/KEYFRAMES_3P.md."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import struct
import sys
import numpy as np
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / 'visual'))
import ogre

IDENTITY = [1., 0., 0., 0.]

def finite(v, n, label):
    if not isinstance(v, list) or len(v) != n or any(isinstance(x, bool) or not isinstance(x, (int, float)) for x in v):
        raise ValueError(label + ': expected numeric vector')
    a = np.asarray(v, float)
    if not np.isfinite(a).all() or np.max(np.abs(a)) > np.finfo(np.float32).max: raise ValueError(label + ': nonfinite/unexportable')
    return a

def number(v, label):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise ValueError(label + ': expected finite number')
    return float(v)

def fields(obj, required, optional=()):
    if not isinstance(obj, dict) or not set(required) <= set(obj) or set(obj) - set(required) - set(optional):
        raise ValueError('missing/unknown fields: ' + repr(obj))

def validate_skeleton(sk):
    if not sk.bones: raise ValueError('empty skeleton')
    names=set()
    for h,b in sk.bones.items():
        if h != b.h or not 0 <= h <= 65535 or b.name in names or not b.name or '\n' in b.name: raise ValueError('invalid skeleton handle/name')
        names.add(b.name)
        if b.parent != -1 and b.parent not in sk.bones: raise ValueError('missing parent')
        if not np.isfinite(b.pos).all() or not np.isfinite(b.q).all() or not np.isfinite(b.scale).all() or np.any(b.scale <= 0) or abs(np.linalg.norm(b.q)-1)>1e-5: raise ValueError('invalid bind')
        seen=set(); cur=h
        while cur != -1:
            if cur in seen: raise ValueError('hierarchy cycle')
            seen.add(cur); cur=sk.bones[cur].parent
    if set(sk.by_name)!=names: raise ValueError('name map mismatch')
    return sk

def validate(doc, sk=None):
    if sk is not None: validate_skeleton(sk)
    fields(doc, ('schema', 'name', 'duration', 'units', 'omitted', 'tracks'), ('attachments',))
    if doc['schema'] != 'animlab.3p.keys.v1' or doc['units'] != 'dm' or doc['omitted'] != 'bind':
        raise ValueError('unsupported schema/units/omitted policy')
    if not isinstance(doc['name'], str) or not doc['name'] or '\n' in doc['name'] or not doc['name'].isascii():
        raise ValueError('invalid animation name')
    duration = number(doc['duration'], 'duration')
    if not 0 < duration <= 3600: raise ValueError('duration out of range')
    if not isinstance(doc['tracks'], dict) or not doc['tracks']: raise ValueError('tracks empty')
    for name, tr in doc['tracks'].items():
        if not isinstance(name, str) or not name: raise ValueError('invalid bone name')
        if sk is not None and name not in sk.by_name: raise ValueError('unknown bone: ' + name)
        fields(tr, ('keys',))
        keys = tr['keys']
        if not isinstance(keys, list) or not 1 <= len(keys) <= 100000: raise ValueError('invalid key count')
        prev = -1
        fprev = -1
        for k in keys:
            fields(k, ('t', 'q', 'p'), ('s',))
            t = number(k['t'], 'time'); ft = float(np.float32(t))
            if not 0 <= t <= duration or t <= prev or ft <= fprev: raise ValueError('times not ordered/exportable')
            prev, fprev = t, ft
            q = finite(k['q'], 4, 'quaternion')
            if abs(np.linalg.norm(q) - 1) > 1e-6: raise ValueError('quaternion must be unit')
            finite(k['p'], 3, 'translation')
            s = finite(k.get('s', [1., 1., 1.]), 3, 'scale')
            if np.any(s <= 0): raise ValueError('scale must be positive')
    attachments = doc.get('attachments', [])
    if not isinstance(attachments, list): raise ValueError('attachments must be list')
    names = set()
    for a in attachments:
        fields(a, ('name', 'bone', 'mesh', 'mesh_sha256', 'q', 'p', 'scale'))
        if not isinstance(a['name'], str) or not a['name'] or a['name'] in names: raise ValueError('duplicate/invalid attachment')
        names.add(a['name'])
        if not isinstance(a['bone'], str) or sk is not None and a['bone'] not in sk.by_name: raise ValueError('unknown attachment bone')
        if not isinstance(a['mesh'], str) or not a['mesh']: raise ValueError('invalid mesh')
        if not isinstance(a['mesh_sha256'], str) or len(a['mesh_sha256']) != 64 or any(c not in '0123456789abcdef' for c in a['mesh_sha256']): raise ValueError('mesh hash required')
        q = finite(a['q'], 4, 'attachment q')
        if abs(np.linalg.norm(q)-1) > 1e-6: raise ValueError('attachment q must be unit')
        finite(a['p'], 3, 'attachment p')
        if np.any(finite(a['scale'], 3, 'attachment scale') <= 0): raise ValueError('attachment scale positive')
    return doc

def load_document(path):
    def unique(pairs):
        out={}
        for key,value in pairs:
            if key in out: raise ValueError('duplicate JSON field: '+key)
            out[key]=value
        return out
    return json.loads(Path(path).read_text(),object_pairs_hook=unique)

def animation(doc, sk):
    validate(doc, sk)
    an = ogre.Animation(doc['name'], doc['duration'])
    for name, tr in doc['tracks'].items():
        keys = tr['keys']; h = sk.by_name[name].h
        an.tracks[h] = ogre.Track(h, np.array([k['t'] for k in keys]), np.array([k['q'] for k in keys]),
            np.array([k['p'] for k in keys]), np.array([k.get('s', [1.,1.,1.]) for k in keys]))
    return an

def sample(doc, sk, t):
    return ogre.sample_pose(sk, animation(doc, sk), number(t, 'sample time'), loop=False)

def chunk(cid, data): return struct.pack('<HI', cid, len(data)+6)+data

def export(doc, sk, output):
    return export_bank([doc],sk,output)

def export_bank(docs, sk, output):
    if not isinstance(docs,list) or not docs: raise ValueError('bank requires clips')
    animations=[animation(doc,sk) for doc in docs]
    if len({an.name for an in animations})!=len(animations): raise ValueError('duplicate clip name')
    data = struct.pack('<H', 0x1000)+b'[Serializer_v1.80]\n'
    for h, b in sorted(sk.bones.items()):
        # Ogre legacy bone length excludes its newline-terminated name.
        payload = struct.pack('<H3f4f3f', h, *b.pos, *b.q[1:], b.q[0], *b.scale)
        data += struct.pack('<HI', 0x2000, 6+len(payload))+b.name.encode('latin-1')+b'\n'+payload
    for h, b in sorted(sk.bones.items()):
        if b.parent >= 0: data += chunk(0x3000, struct.pack('<HH', h, b.parent))
    for an in animations:
        tracks = b''
        for h, tr in sorted(an.tracks.items()):
            keys = b''
            for t, q, p, s in zip(tr.times, tr.rot, tr.trans, tr.scale):
                keys += chunk(0x4110, struct.pack('<f4f3f3f', t, *q[1:], q[0], *p, *s))
            tracks += chunk(0x4100, struct.pack('<H', h)+keys)
        data += chunk(0x4000, an.name.encode('ascii')+b'\n'+struct.pack('<f', an.length)+tracks)
    Path(output).write_bytes(data)
    return hashlib.sha256(data).hexdigest()

def errors(tr, reduced, times, duration):
    out = []
    for t in times:
        q,p,s = ogre.track_at(tr,t,duration,False); qr,pr,sr = ogre.track_at(reduced,t,duration,False)
        angle = 2*math.acos(min(1., abs(float(np.dot(q,qr)))))
        out.append((angle, float(np.linalg.norm(p-pr)), float(np.max(np.abs(s-sr)))))
    return out

def reduce_track(tr, duration, angle, distance, scale, fps):
    # Deterministic worst-error insertion, never parameter search. Checks original knots and uniform validation times.
    ts = sorted(set(tr.times.tolist()) | set(np.linspace(0,duration,max(1,math.ceil(duration*fps))+1)))
    keep = {0,len(tr.times)-1}
    while True:
        ix = sorted(keep); red = ogre.Track(tr.bone,tr.times[ix],tr.rot[ix],tr.trans[ix],tr.scale[ix])
        err = errors(tr,red,ts,duration)
        scores = [max(a/angle,p/distance,s/scale) for a,p,s in err]
        worst = int(np.argmax(scores))
        if scores[worst] <= 1+1e-9: return red, {'tested_times':len(ts),'max_angle_rad':max(e[0] for e in err),'max_translation_dm':max(e[1] for e in err),'max_scale':max(e[2] for e in err)}
        t = ts[worst]; j = int(np.searchsorted(tr.times,t))
        candidates = [k for k in (j-1,j) if 0 <= k < len(tr.times) and k not in keep]
        if not candidates:
            candidates = [k for k in range(len(tr.times)) if k not in keep]
        if not candidates: raise ValueError('reduction tolerance below numerical precision')
        keep.add(min(candidates,key=lambda k:abs(tr.times[k]-t)))

def import_clip(sk, an, angle=.001, distance=.001, scale=.00001, fps=144, lossless=False):
    if an.base is not None: raise ValueError('additive base animation import unsupported')
    if min(angle,distance,scale,fps) <= 0 or not all(math.isfinite(x) for x in (angle,distance,scale,fps)): raise ValueError('invalid tolerances')
    doc = dict(schema='animlab.3p.keys.v1',name=an.name,duration=an.length,units='dm',omitted='bind',tracks={})
    report = {}
    for h,tr in sorted(an.tracks.items()):
        if len(tr.times)==0: continue
        if lossless:
            red=tr; metrics=dict(tested_times=len(tr.times),max_angle_rad=0.,max_translation_dm=0.,max_scale=0.,mode='lossless-original-knots')
        else: red, metrics = reduce_track(tr,an.length,angle,distance,scale,fps)
        name = sk.bones[h].name
        doc['tracks'][name]={'keys':[dict(t=float(t),q=q.tolist(),p=p.tolist(),s=s.tolist()) for t,q,p,s in zip(red.times,red.rot,red.trans,red.scale)]}
        report[name]=dict(original=len(tr.times),reduced=len(red.times),**metrics)
    validate(doc,sk)
    return doc, report

def attachment_vertices(a, sk, pose, base, cache=None):
    path = Path(a['mesh']); path = path if path.is_absolute() else Path(base)/path
    key=(str(path.resolve()),a['mesh_sha256'])
    if cache is None: cache={}
    if key not in cache:
        raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=a['mesh_sha256']: raise ValueError('attachment mesh changed')
        mesh=ogre.load_mesh(str(path)); vertices=[]; triangles=[]
        for p,_,t,_ in mesh.triangles():
            triangles.append(t+sum(len(x) for x in vertices)); vertices.append(p)
        if not vertices: raise ValueError('attachment mesh empty')
        cache[key]=(np.vstack(vertices),np.vstack(triangles))
    v,tr=cache[key]
    localkey=(key,tuple(a['scale']),tuple(a['q']),tuple(a['p']))
    if localkey not in cache:
        cache[localkey]=(v*a['scale'])@ogre.qmat(np.array(a['q'])).T+np.array(a['p'])
    v=cache[localkey]; h=sk.by_name[a['bone']].h
    return pose.dpos[h]+(v*pose.dscale[h])@pose.mat(h).T,tr

def protect_output(output, inputs):
    target=Path(output)
    for source in inputs:
        source=Path(source)
        if target.resolve()==source.resolve() or target.exists() and source.exists() and target.samefile(source):
            raise ValueError('refusing input overwrite: '+str(source))


def main():
    p=argparse.ArgumentParser(description=__doc__); sub=p.add_subparsers(dest='cmd',required=True)
    for cmd in ('validate','sample','export','render','import'):
        a=sub.add_parser(cmd); a.add_argument('--skeleton',required=True); a.add_argument('-o','--output')
        if cmd=='import':
            a.add_argument('--lossless',action='store_true'); a.add_argument('--clip',required=True); a.add_argument('--angle',type=float,default=.001); a.add_argument('--distance',type=float,default=.001); a.add_argument('--scale-error',type=float,default=.00001)
        else: a.add_argument('keys')
        if cmd=='export': a.add_argument('--clip-json',action='append',default=[])
        if cmd in ('sample','render','import'): a.add_argument('--fps',type=float,default=30)
        if cmd=='sample': a.add_argument('--t',type=float)
        if cmd=='render':
            a.add_argument('--config',required=True); a.add_argument('--views',default='front,side,back'); a.add_argument('--keys-only',action='store_true')
    a=p.parse_args();
    if hasattr(a,'fps') and (not math.isfinite(a.fps) or not 0 < a.fps <= 1000): p.error('fps must be finite in (0,1000]')
    sk=ogre.load_skeleton(a.skeleton); source=hashlib.sha256(Path(a.skeleton).read_bytes()).hexdigest()
    inputpaths=[a.skeleton]+([a.keys] if hasattr(a,'keys') else [])+getattr(a,'clip_json',[])
    inputpins={str(path):hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in inputpaths}
    if a.output and a.cmd in ('import','export','sample'): protect_output(a.output,inputpaths)
    if a.output and a.cmd=='import': protect_output(a.output+'.reduction.json',inputpaths)
    if a.cmd=='import':
        doc,report=import_clip(sk,ogre.load_animations(a.skeleton)[a.clip],a.angle,a.distance,a.scale_error,a.fps,a.lossless)
        if not a.output: p.error('import requires -o')
        Path(a.output).write_text(json.dumps(doc,indent=2)+'\n'); Path(a.output+'.reduction.json').write_text(json.dumps(dict(source_sha256=source,scope='lossless original knots' if a.lossless else 'sampled local error bound; not visual acceptance',tracks=report),indent=2)+'\n')
    else:
        doc=validate(load_document(a.keys),sk)
        if a.cmd=='export':
            if not a.output: p.error('export requires -o')
            if Path(a.output).resolve()==Path(a.skeleton).resolve(): raise ValueError('refusing source overwrite')
            export_bank([doc]+[load_document(path) for path in a.clip_json],sk,a.output)
        elif a.cmd=='sample':
            ts=[a.t] if a.t is not None else np.linspace(0,doc['duration'],max(1,math.ceil(doc['duration']*a.fps))+1)
            rows=[]
            for t in ts:
                pose=sample(doc,sk,float(t)); rows.append(dict(t=float(t),bones={b.name:dict(p=pose.dpos[h].tolist(),q=pose.dq[h].tolist()) for h,b in sk.bones.items()}))
            result=json.dumps(dict(source_sha256=source,frames=rows),indent=2)
            if a.output: Path(a.output).write_text(result+'\n')
            else: print(result)
        elif a.cmd=='render':
            if not a.output: p.error('render requires -o directory')
            import native
            cfg=native.load_cfg(a.config); inputs={str(Path(a.config)):hashlib.sha256(Path(a.config).read_bytes()).hexdigest()}
            for mesh in cfg.get('body_meshes',[]):
                path=Path(native.gpath(cfg,mesh)); inputs[str(path)]=hashlib.sha256(path.read_bytes()).hexdigest()
            for at in doc.get('attachments',[]):
                path=Path(at['mesh']); path=path if path.is_absolute() else Path(a.keys).parent/path
                inputs[str(path)]=at['mesh_sha256']
            out=Path(a.output); out.mkdir(parents=True,exist_ok=True)
            n=native.Native(cfg,a.skeleton); an=animation(doc,sk)
            n.pose=lambda clip,t,loop=False: ogre.sample_pose(n.sk,clip,t,False)
            views=tuple(a.views.split(','))
            if not views or any(v not in ('front','side','back','left','top') for v in views): raise ValueError('invalid views')
            keytimes=set(k['t'] for tr in doc['tracks'].values() for k in tr['keys'])|{0.,doc['duration']}
            ts=sorted(keytimes if a.keys_only else keytimes|set(native.times_of(doc['duration'],a.fps)))
            renderer=native.Render3P(n,an,None,views)
            # Cache exact posed geometry once per sample; body + both props share projection and depth buffer.
            geometry=[]; meshcache={}
            for t in ts:
                pose=n.pose(an,t); verts=[renderer.body.verts(pose)]; tris=[renderer.body.T]; parts=[np.zeros(len(tris[0]),int)]
                for at in doc.get('attachments',[]):
                    v,tr=attachment_vertices(at,sk,pose,Path(a.keys).parent,meshcache)
                    tris.append(tr+sum(len(x) for x in verts)); verts.append(v); parts.append(np.ones(len(tr),int))
                geometry.append((np.vstack(verts),np.vstack(tris),np.concatenate(parts)))
            lo=np.minimum.reduce([v.min(0) for v,_,_ in geometry])-2.5
            hi=np.maximum.reduce([v.max(0) for v,_,_ in geometry])+2.5
            renderer.center=(lo+hi)/2; renderer.ext=hi-lo
            width,height=renderer.size; asp=width/height
            for view in views:
                axes=native.cam_axes(native.VIEWS[view]); r,u,d=axes
                dist=max(.5*float(np.abs(u)@renderer.ext)/renderer.tan,.5*float(np.abs(r)@renderer.ext)/(renderer.tan*asp))+.5*float(np.abs(d)@renderer.ext)
                renderer.cams[view]=(renderer.center-d*dist,axes)
            ledger=[]
            for i,(t,(v,tr,part)) in enumerate(zip(ts,geometry)):
                tiles=[]
                for view in views:
                    eye,axes=renderer.cams[view]; camera=native.to_cam(v,eye,axes)
                    img,_,_=renderer.raster(camera,tr,part,renderer.size,(renderer.tan*asp,renderer.tan),.5,cfg.get('colors',[[205,160,130],[190,195,205]]),np.full((height,width,3),48,np.float32))
                    renderer._ground(img,eye,axes); tiles.append(native.label(img,[doc['name']+' '+view,'t %.6f'%t]))
                path=out/('f%05d.png'%i); protect_output(path,inputpaths+list(inputs)); native.save_png(np.concatenate(tiles,1),str(path))
                ledger.append(dict(index=i,t=t,file=path.name,sha256=hashlib.sha256(path.read_bytes()).hexdigest(),body_and_props_finite=bool(np.isfinite(v).all())))
            for path,expected in inputs.items():
                if hashlib.sha256(Path(path).read_bytes()).hexdigest()!=expected: raise ValueError('render input changed: '+path)
            protect_output(out/'sampling.json',inputpaths+list(inputs))
            (out/'sampling.json').write_text(json.dumps(dict(source_sha256=source,keys_sha256=hashlib.sha256(Path(a.keys).read_bytes()).hexdigest(),inputs=inputs,tool_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),attachments=doc.get('attachments',[]),mode='keys-only' if a.keys_only else 'dense-plus-keys',frames=ledger,visual_acceptance=False),indent=2))
    for path,sha in inputpins.items():
        if hashlib.sha256(Path(path).read_bytes()).hexdigest()!=sha: raise ValueError('source modified: '+path)
    print('RESULT KEYFRAMES3P PASS '+a.cmd)
if __name__=='__main__': main()
