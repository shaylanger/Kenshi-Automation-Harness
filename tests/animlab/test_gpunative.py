#!/usr/bin/env python3
"""Offline tests for the Windows-native GPU path of tools/animlab/framecache.py (gpu-native 2026-10-11): decode() via
Windows ffmpeg.exe NVDEC, native_check() via Windows python CuPy, winpath()/win_file() visibility, gpu_slot() cap of WSL
GPU users. Synthetic video only (ffmpeg testsrc). The native/WSL parts skip off WSL (4080 / Windows python).
Run (WSL): python3 tests/animlab/test_gpunative.py   (exit 0 = all pass). ANIMLAB_SRC=<dir> tests another source dir."""
import os, subprocess, sys, tempfile, time, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.environ.get('ANIMLAB_SRC') or os.path.join(HERE, '..', '..', 'tools', 'animlab')
sys.path.insert(0, SRC)
import framecache as FC  # noqa: E402

WSL = FC.on_wsl()
NATIVE = WSL and os.path.exists(FC.WIN_FFMPEG)
PYNATIVE = NATIVE and os.path.exists(FC.WIN_PYTHON)
_vid = {}


def video(where):
    """2 s 320x180 h264 testsrc video, on /mnt/c (Windows sees it) or in /tmp (it does not)"""
    if where not in _vid:
        d = os.path.join(FC.WIN_TMP if where == 'win' else tempfile.gettempdir(), 'gn-test-%d' % os.getpid())
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, 'src.mp4')
        subprocess.run(['ffmpeg', '-nostdin', '-loglevel', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc=size=320x180:rate=30',
                        '-t', '2', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', p], check=True)
        _vid[where] = p
    return _vid[where]


POST = ['-vf', 'fps=5,scale=160:90', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-']


def run_forced(kind, v, popen=False):
    old = os.environ.get('ANIMLAB_DECODE')
    os.environ['ANIMLAB_DECODE'] = kind
    try:
        if popen:
            p = FC.decode(v, post=POST, popen=True)
            b = p.stdout.read(); p.stdout.close(); p.wait()
            return b
        return FC.decode(v, post=POST).stdout
    finally:
        if old is None:
            os.environ.pop('ANIMLAB_DECODE')
        else:
            os.environ['ANIMLAB_DECODE'] = old


def maxdiff(a, b):
    import numpy as np
    x, y = np.frombuffer(a, np.uint8).astype(int), np.frombuffer(b, np.uint8).astype(int)
    return 999 if len(x) != len(y) else int(abs(x - y).max())


@unittest.skipUnless(WSL, 'WSL only')
class Paths(unittest.TestCase):
    def test_winpath(self):
        self.assertEqual(FC.winpath('/mnt/c/Windows'), 'C:\\Windows')
        self.assertIsNone(FC.winpath('/tmp'))
        self.assertIsNone(FC.winpath('/root'))

    def test_paths_order(self):
        if NATIVE and not FC.no_gpu():
            self.assertEqual(FC.decode_paths()[0], 'native')
        os.environ['ANIMLAB_NATIVE'] = '0'
        try:
            self.assertNotIn('native', FC.decode_paths())
        finally:
            os.environ.pop('ANIMLAB_NATIVE')


@unittest.skipUnless(NATIVE, 'needs WSL + Windows ffmpeg.exe')
class Decode(unittest.TestCase):
    def test_native_equals_software(self):
        v = video('win')
        a, b = run_forced('native', v), run_forced('sw', v)
        self.assertEqual(len(a), 10 * 160 * 90 * 3)
        self.assertLessEqual(maxdiff(a, b), 2)

    def test_invisible_video_copied_and_removed(self):
        v = video('tmp')
        self.assertIsNone(FC.winpath(v))
        a, b = run_forced('native', v), run_forced('sw', v)
        self.assertLessEqual(maxdiff(a, b), 2)
        self.assertFalse([n for n in os.listdir(FC.WIN_TMP) if n.startswith('%d-' % os.getpid())])

    def test_popen(self):
        v = video('tmp')
        self.assertLessEqual(maxdiff(run_forced('native', v, popen=True), run_forced('sw', v)), 2)
        self.assertFalse([n for n in os.listdir(FC.WIN_TMP) if n.startswith('%d-' % os.getpid())])


@unittest.skipUnless(PYNATIVE, 'needs WSL + Windows python')
class NativeCheck(unittest.TestCase):
    def test_cursor_overlay_same_verdict(self):
        import frames as FR
        for v in (video('win'), video('tmp')):
            for fn in (FR.cursor_check, FR.overlay_check):
                raw = fn.__wrapped__   # cached_check -> native_check wrapper
                os.environ['ANIMLAB_NATIVE_CHECKS'] = '0'
                try:
                    loc = raw(v)
                finally:
                    os.environ.pop('ANIMLAB_NATIVE_CHECKS')
                nat = FC.native_call(raw.__wrapped__, {'video': v})
                self.assertEqual(tuple(loc), tuple(nat), (fn.__name__, v))

    def test_still_same_verdict(self):
        import frames as FR
        png = os.path.join(os.path.dirname(video('tmp')), 'still.png')
        subprocess.run(['ffmpeg', '-nostdin', '-loglevel', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc=size=640x360',
                        '-frames:v', '1', png], check=True)
        for fn in (FR.still_overlay_check, FR.still_cursor_check):
            os.environ['ANIMLAB_NATIVE_CHECKS'] = '0'
            try:
                loc = fn(png)
            finally:
                os.environ.pop('ANIMLAB_NATIVE_CHECKS')
            self.assertEqual(tuple(loc), tuple(FC.native_call(fn.__wrapped__, {'path': png}, 'path')), fn.__name__)


@unittest.skipUnless(WSL, 'WSL only')
class Slots(unittest.TestCase):
    def test_cap(self):
        d = tempfile.mkdtemp(prefix='gn-slot-')
        env = dict(os.environ, ANIMLAB_GPU_SLOT_DIR=d, ANIMLAB_WSL_GPU_SLOTS='2')
        env.pop('KAH_GPU_SLOT_HELD', None)
        code = ('import sys,time; sys.path.insert(0,%r); import framecache as F\n'
                'with F.gpu_slot():\n  print(time.time(), flush=True); time.sleep(1.5)' % SRC)
        t0 = time.time()
        ps = [subprocess.Popen([sys.executable, '-c', code], env=env, stdout=subprocess.PIPE, text=True) for _ in range(3)]
        starts = sorted(float(p.communicate()[0].split()[0]) - t0 for p in ps)
        self.assertLess(starts[1], 1.2)          # two run at once
        self.assertGreater(starts[2], 1.3)       # the third waited for a slot
        # a child of a holder inherits the slot (no deadlock)
        code2 = ('import sys,subprocess; sys.path.insert(0,%r); import framecache as F\n'
                 'with F.gpu_slot():\n  print(subprocess.run([sys.executable,"-c",%r],timeout=10).returncode)'
                 % (SRC, code.replace('time.sleep(1.5)', 'pass')))
        env1 = dict(env, ANIMLAB_WSL_GPU_SLOTS='1')
        out = subprocess.run([sys.executable, '-c', code2], env=env1, capture_output=True, text=True, timeout=20).stdout
        self.assertTrue(out.strip().endswith('0'), out)


def tearDownModule():
    import shutil
    for p in _vid.values():
        shutil.rmtree(os.path.dirname(p), ignore_errors=True)


if __name__ == '__main__':
    unittest.main(verbosity=1)
