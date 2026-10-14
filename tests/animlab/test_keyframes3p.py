"""Independent analytic keyframe controls; no visual certification."""
import copy
import hashlib
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools/animlab'))
import keyframes3p as k
import numpy as np
ogre=k.ogre

def rig(length=2):
    sk=ogre.Skeleton()
    for name,h,p in [('Root',0,[0,0,0]),('Hand',1,[length,0,0])]:
        b=ogre.Bone(name,h,p,[1,0,0,0],[1,1,1]); sk.bones[h]=b;sk.by_name[name]=b
    sk.bones[1].parent=0
    return sk.derive()

def doc():
    return dict(schema='animlab.3p.keys.v1',name='Test',duration=1.,units='dm',omitted='bind',tracks={'Root':{'keys':[dict(t=0.,q=[1,0,0,0],p=[0,0,0]),dict(t=1.,q=[0,0,0,1],p=[2,0,0])]}})

class Keys(unittest.TestCase):
    def test_midpoint_analytic(self):
        p=k.sample(doc(),rig(),.5)
        np.testing.assert_allclose(p.dpos[0],[1,0,0]);np.testing.assert_allclose(p.dpos[1],[1,2,0],atol=1e-12)
        np.testing.assert_allclose(p.dq[0],[math.sqrt(.5),0,0,math.sqrt(.5)])
    def test_antipodal_quaternion(self):
        d=doc();d['tracks']['Root']['keys'][1]['q']=[-1,0,0,0]
        np.testing.assert_allclose(k.sample(d,rig(),.5).dq[0],[1,0,0,0])
    def test_clamped_endpoints(self):
        for t,expected in [(-1,[2,0,0]),(2,[0,0,0])]: np.testing.assert_allclose(k.sample(doc(),rig(),t).dpos[1],expected,atol=1e-12)
    def test_one_key_hold(self):
        d=doc();d['tracks']['Root']['keys']=d['tracks']['Root']['keys'][:1]
        np.testing.assert_allclose(k.sample(d,rig(),.6).dpos[1],[2,0,0])
    def test_before_after_partial_track_hold(self):
        d=doc();d['tracks']['Root']['keys'][0]['t']=.2;d['tracks']['Root']['keys'][1]['t']=.8
        np.testing.assert_allclose(k.sample(d,rig(),0).dpos[1],[2,0,0]);np.testing.assert_allclose(k.sample(d,rig(),1).dpos[1],[0,0,0],atol=1e-12)
    def test_shared_motion_two_rigs(self):
        a=k.sample(doc(),rig(2),.5);b=k.sample(doc(),rig(3),.5)
        np.testing.assert_allclose(a.dq[1],b.dq[1]);np.testing.assert_allclose(a.dpos[1],[1,2,0],atol=1e-12);np.testing.assert_allclose(b.dpos[1],[1,3,0],atol=1e-12)
    def test_bind_not_mutated(self):
        s=rig();before=[(b.pos.copy(),b.q.copy(),b.scale.copy()) for b in s.bones.values()]
        for t in np.linspace(0,1,21):k.sample(doc(),s,t)
        for b,(p,q,sc) in zip(s.bones.values(),before):np.testing.assert_array_equal(b.pos,p);np.testing.assert_array_equal(b.q,q);np.testing.assert_array_equal(b.scale,sc)
    def test_omitted_bone_local_bind(self):
        s=rig();p=k.sample(doc(),s,.5);np.testing.assert_array_equal(p.pos[1],s.bones[1].pos);np.testing.assert_array_equal(p.q[1],s.bones[1].q)
    def test_export_reader_equivalence(self):
        s=rig();d=doc()
        with tempfile.TemporaryDirectory() as td:
            f=Path(td)/'x.skeleton';k.export(d,s,f);sr=ogre.load_skeleton(str(f));ar=ogre.load_animations(str(f))['Test']
            for t in np.linspace(0,1,101):
                p=k.sample(d,s,t);r=ogre.sample_pose(sr,ar,t,False)
                for h in s.bones:np.testing.assert_allclose(r.dpos[h],p.dpos[h],atol=1e-6);np.testing.assert_allclose(r.dq[h],p.dq[h],atol=1e-6)
    def test_multi_clip_bank_readback_and_duplicate_rejection(self):
        first=doc();second=doc();second['name']='Second';second['tracks']['Root']['keys'][1]['p']=[4,0,0]
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'bank';k.export_bank([first,second],rig(),p);loaded=ogre.load_animations(str(p))
            self.assertEqual(set(loaded),{'Test','Second'});np.testing.assert_array_equal(loaded['Second'].tracks[0].trans[-1],[4,0,0])
            with self.assertRaises(ValueError):k.export_bank([first,first],rig(),p)
    def test_skin_analytic(self):
        s=rig();p=k.sample(doc(),s,.5);pn,a=p.skin(1)
        np.testing.assert_allclose(pn+a@(np.array([3,0,0])-s.bones[1].dpos),[1,3,0],atol=1e-12)
    def test_attachment_follows_hand_and_hash(self):
        class Mesh:
            def triangles(self):yield np.array([[0.,0,0],[1,0,0],[0,1,0]]),None,np.array([[0,1,2]]),[]
        with tempfile.TemporaryDirectory() as td:
            f=Path(td)/'fake.mesh';f.write_bytes(b'synthetic geometry')
            a=dict(name='R',bone='Hand',mesh=str(f),mesh_sha256=hashlib.sha256(f.read_bytes()).hexdigest(),q=[1,0,0,0],p=[.5,0,0],scale=[2,1,1])
            d=doc();d['attachments']=[a];k.validate(d,rig())
            with patch.object(ogre,'load_mesh',return_value=Mesh()):
                v,tr=k.attachment_vertices(a,rig(),k.sample(d,rig(),.5),td)
                np.testing.assert_allclose(v,[[1,2.5,0],[1,4.5,0],[0,2.5,0]],atol=1e-12)
                f.write_bytes(b'changed')
                with self.assertRaises(ValueError):k.attachment_vertices(a,rig(),k.sample(d,rig(),.5),td)
    def test_reduction_removes_linear_interior(self):
        an=ogre.Animation('Linear',1);ts=np.linspace(0,1,21);an.tracks[0]=ogre.Track(0,ts,np.tile([1,0,0,0],(21,1)),np.column_stack([ts*2,ts*0,ts*0]),np.ones((21,3)))
        d,r=k.import_clip(rig(),an);self.assertEqual(len(d['tracks']['Root']['keys']),2);self.assertLess(r['Root']['max_translation_dm'],1e-12)
    def test_lossless_import_preserves_knots_and_values(self):
        sk=rig();d=doc();an=k.animation(d,sk)
        imported,report=k.import_clip(sk,an,lossless=True);copyan=k.animation(imported,sk)
        for h,tr in an.tracks.items():
            other=copyan.tracks[h]
            for field in ('times','rot','trans','scale'):np.testing.assert_array_equal(getattr(tr,field),getattr(other,field))
        self.assertEqual(report['Root']['mode'],'lossless-original-knots')
    def test_reduction_keeps_between_endpoint_excursion(self):
        ts=np.array([0,.5,1]);an=ogre.Animation('Excursion',1);an.tracks[0]=ogre.Track(0,ts,np.tile([1,0,0,0],(3,1)),np.array([[0,0,0],[0,2,0],[0,0,0]]),np.ones((3,3)))
        d,r=k.import_clip(rig(),an);self.assertEqual(len(d['tracks']['Root']['keys']),3)
    def test_additive_import_rejected(self):
        an=ogre.Animation('Base',1);an.base=('other',0)
        with self.assertRaises(ValueError):k.import_clip(rig(),an)
    def test_negative_schema_controls(self):
        cases=[]
        def add(edit):d=doc();edit(d);cases.append(d)
        add(lambda d:d.update(schema='bad'));add(lambda d:d.update(units='m'));add(lambda d:d.update(omitted='native'));add(lambda d:d.update(duration=0));add(lambda d:d.update(duration=float('nan')));add(lambda d:d.update(extra=1));add(lambda d:d.update(tracks={}));add(lambda d:d['tracks'].update(Unknown={'keys':[dict(t=0,q=[1,0,0,0],p=[0,0,0])]}))
        for field,value in [('t',-.1),('t',float('inf')),('q',[2,0,0,0]),('q',[float('nan'),0,0,0]),('p',[1,2]),('p',[float('inf'),0,0]),('s',[0,1,1]),('t',True)]:add(lambda d,f=field,v=value:d['tracks']['Root']['keys'][0].update({f:v}))
        add(lambda d:d['tracks']['Root']['keys'][1].update(t=0));add(lambda d:d['tracks']['Root']['keys'][1].update(t=2));add(lambda d:d['tracks']['Root']['keys'].append(dict(t=1,q=[1,0,0,0],p=[0,0,0])));add(lambda d:d['tracks']['Root']['keys'][0].update(extra=0))
        for d in cases:
            with self.subTest(d=d):
                with self.assertRaises(ValueError):k.validate(d,rig())
    def test_float32_time_collapse_rejected(self):
        d=doc();d['tracks']['Root']['keys']=[dict(t=.999999999,q=[1,0,0,0],p=[0,0,0]),dict(t=1,q=[1,0,0,0],p=[0,0,0])]
        with self.assertRaises(ValueError):k.validate(d,rig())
    def test_malformed_rig_rejected(self):
        for mode in ('cycle','parent','scale'):
            s=rig()
            if mode=='cycle':s.bones[0].parent=1
            elif mode=='parent':s.bones[0].parent=99
            else:s.bones[1].scale[0]=0
            with self.assertRaises(ValueError):k.validate(doc(),s)
    def test_output_aliases_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'keys.json';p.write_text('{}');q=Path(td)/'alias';q.symlink_to(p);h=Path(td)/'hardlink'
            import os
            os.link(p,h)
            for dest in (p,q,h):
                with self.assertRaises(ValueError):k.protect_output(dest,[p])
            k.protect_output(Path(td)/'new',[p])
    def test_cli_rejects_key_source_overwrite(self):
        import subprocess
        with tempfile.TemporaryDirectory() as td:
            bank=Path(td)/'source.skeleton';k.export(doc(),rig(),bank)
            author=Path(td)/'keys.json';author.write_text(json.dumps(doc()));before=author.read_bytes()
            for cmd in ('export','sample'):
                result=subprocess.run([sys.executable,str(Path(k.__file__)),cmd,str(author),'--skeleton',str(bank),'-o',str(author)],capture_output=True,text=True)
                self.assertNotEqual(result.returncode,0);self.assertIn('refusing input overwrite',result.stderr);self.assertEqual(author.read_bytes(),before)
    def test_attachment_parse_cache(self):
        class Mesh:
            def triangles(self):yield np.array([[0.,0,0],[1,0,0],[0,1,0]]),None,np.array([[0,1,2]]),[]
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'fake';p.write_bytes(b'fixture');a=dict(mesh=str(p),mesh_sha256=hashlib.sha256(p.read_bytes()).hexdigest(),bone='Hand',q=[1,0,0,0],p=[0,0,0],scale=[1,1,1]);cache={}
            with patch.object(ogre,'load_mesh',return_value=Mesh()) as loader:
                for t in np.linspace(0,1,20):k.attachment_vertices(a,rig(),k.sample(doc(),rig(),t),td,cache)
                self.assertEqual(loader.call_count,1)
    def test_duplicate_json_fields_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'duplicate.json';p.write_text('{"schema":"a","schema":"b"}')
            with self.assertRaises(ValueError):k.load_document(p)
    def test_invalid_attachment_rejected(self):
        d=doc();d['attachments']=[dict(name='R',bone='Hand',mesh='x',mesh_sha256='wrong',q=[1,0,0,0],p=[0,0,0],scale=[1,1,1])]
        with self.assertRaises(ValueError):k.validate(d,rig())

if __name__=='__main__':unittest.main(verbosity=2)
