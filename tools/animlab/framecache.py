#!/usr/bin/env python3
"""framecache.py -- decode a take video once, share it between every consumer (Shay 2026-10-10: the 5090 sat at ~79% CPU
with one take decoded and judged five times at once: 2 ffmpeg + 2 identical `frames.py overlay` runs + test runs).

Two caches, both in `<video dir>/.framecache/<video stem>-<sha1[:12]>/` (deleting the take dir removes them):
  frames(video, fps, w, h, t0=None, t1=None) -> uint8 array (N, h, w, 3), memory-mapped
      The whole video decoded once at fps and w x h (ffmpeg `fps=<fps>,scale=<w>:<h>`, rgb24); frame i is at t = i / fps;
      t0/t1 slice it. Only while the array is <= ANIMLAB_FRAMECACHE_MAX_MB (default 256 MB): bigger requests return
      None and the caller streams (full-resolution frames of a long take do not fit; the result cache below still makes
      that decode happen once per check).
  cached_check(name, fn) -> fn wrapped so a call on a video file returns the stored result of an earlier identical call
      (same video content, same check, same arguments, same source of the checking module); concurrent identical calls
      wait on the lock and reuse the first one's result instead of decoding and judging again.
GPU (gpu-native 2026-10-11): decode(video, pre, post) runs every NVDEC decode; under WSL it uses Windows ffmpeg.exe
-hwaccel cuda (no WSL GPU-PV: the 13:16 BSOD + afternoon TDRs), WSL NVDEC only as fallback inside gpu_slot (<= 2 WSL GPU
processes). native_check(fn) runs a CuPy check in Windows python (native_run.py). ANIMLAB_NATIVE=0 = old WSL path.
Key = sha1 of the video content (so a re-recorded take with the same name never hits a stale entry). Locks: fcntl.flock
(WSL / Linux), msvcrt.locking (Windows python on the 4080). ANIMLAB_FRAMECACHE=0 disables both caches.
CLI: framecache.py info <video>   (lists the cache entries)   framecache.py clear <video>
"""
import hashlib, inspect, json, os, subprocess, sys, time

MAX_MB = float(os.environ.get('ANIMLAB_FRAMECACHE_MAX_MB', '256'))
_fp_memo = {}
_src_memo = {}


def enabled():
    return os.environ.get('ANIMLAB_FRAMECACHE', '1') != '0'


def fingerprint(video):
    st = os.stat(video)
    k = (os.path.abspath(video), st.st_size, st.st_mtime_ns)
    if k not in _fp_memo:
        h = hashlib.sha1()
        with open(video, 'rb') as f:
            for b in iter(lambda: f.read(1 << 22), b''):
                h.update(b)
        _fp_memo[k] = h.hexdigest()
    return _fp_memo[k]


def cache_dir(video):
    stem = os.path.splitext(os.path.basename(video))[0]
    vdir = os.path.dirname(os.path.abspath(video))
    d = os.path.join(vdir, '.framecache', '%s-%s' % (stem, fingerprint(video)[:12]))
    try:
        if '/corpus/' in vdir.replace('\\', '/').lower() + '/':   # the corpus is never cleaned: no cache files in it
            raise OSError('corpus')
        os.makedirs(d, exist_ok=True)
        return d
    except OSError:   # corpus / read-only take dir: per-user temp cache (testruns-sweep cleans /tmp/animlab-*)
        import tempfile
        d = os.path.join(os.environ.get('TMPDIR') or tempfile.gettempdir(), 'animlab-framecache', '%s-%s' % (stem, fingerprint(video)[:12]))
        os.makedirs(d, exist_ok=True)
        return d


class Lock:
    """Exclusive lock on <path>.lock; blocks until it is free."""
    def __init__(self, path):
        self.path = path + '.lock'

    def __enter__(self):
        self.f = open(self.path, 'a+b')
        try:
            import fcntl
            fcntl.flock(self.f.fileno(), fcntl.LOCK_EX)
        except ImportError:   # Windows python (4080)
            import msvcrt
            while True:
                try:
                    self.f.seek(0); msvcrt.locking(self.f.fileno(), msvcrt.LK_LOCK, 1); break
                except OSError:
                    time.sleep(0.5)
        return self

    def __exit__(self, *a):
        try:
            import fcntl
            fcntl.flock(self.f.fileno(), fcntl.LOCK_UN)
        except ImportError:
            import msvcrt
            try:
                self.f.seek(0); msvcrt.locking(self.f.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
        self.f.close()


_hw = None
_wsl = None
_slot = None   # this process's held WSL GPU slot (gpu_slot.hold)

# Windows-native GPU path (gpu-native 2026-10-11, tdr-cause handoff): WSL CUDA/NVDEC goes through dxgkrnl's GPU-PV vmbus
# host code (the 13:16 BSOD 0xD1 in DXG_SIGNAL_GUEST_CPU_EVENT_CBLT::ReleaseReference + 4 TDRs in the same second as WSL
# `dxgkio_create_allocation: Ioctl failed: -12` bursts). Under WSL the decode runs in Windows ffmpeg.exe (-hwaccel cuda)
# and the CuPy checks in Windows python (native_check), so no CUDA context lives in WSL. Measured on the 5090, 56 s
# 1600x900 corpus take, best of 2: fps=5 full-res 5.29 s WSL NVDEC -> 2.82 s native (WSL cpu 5.2 -> 1.6 s);
# fps=2 160x90 3.57 -> 1.85 s; 256x144 passthrough 4.29 -> 1.53 s. WSL NVDEC/CuPy stays as fallback only, at most
# ANIMLAB_WSL_GPU_SLOTS (2) WSL processes at once (gpu_slot; the others queue, never CPU).
WIN_FFMPEG = os.environ.get('ANIMLAB_WIN_FFMPEG', '/mnt/c/Users/Shay/AppData/Local/Microsoft/WinGet/Packages/'
                            'Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe/ffmpeg-8.0.1-full_build/bin/ffmpeg.exe')
WIN_PYTHON = os.environ.get('ANIMLAB_WIN_PYTHON', '/mnt/c/Users/Shay/AppData/Local/Programs/Python/Python312/python.exe')
WIN_TMP = os.environ.get('ANIMLAB_WIN_TMP', '/mnt/c/Users/Shay/AppData/Local/Temp/kah-native')
GPU_SLOTS = max(1, int(os.environ.get('ANIMLAB_WSL_GPU_SLOTS', '2')))
SLOT_DIR = os.environ.get('ANIMLAB_GPU_SLOT_DIR', '/run/kah-gpu')   # /run: shared by kfp-pipeline's gate namespaces (they rebind /tmp)


def no_gpu():
    return os.path.exists('/etc/kah-no-gpu')


def on_wsl():
    global _wsl
    if _wsl is None:
        import platform
        _wsl = sys.platform.startswith('linux') and 'microsoft' in platform.release().lower()
    return _wsl


def native_on():
    """True in WSL when GPU work goes to Windows-native processes (ANIMLAB_NATIVE=0 or /etc/kah-no-gpu: off)."""
    return on_wsl() and os.environ.get('ANIMLAB_NATIVE', '1') != '0' and not no_gpu()


def _mountpoints():
    out = []
    try:
        with open('/proc/self/mountinfo') as fh:
            for ln in fh:
                out.append(ln.split()[4].replace('\\040', ' '))
    except OSError:
        pass
    return out


def winpath(path):
    """Windows path of a WSL file when Windows sees the same file: a /mnt/<drive> path whose nearest mount is the drive
    itself (not a bind mount of a private namespace: kfp-pipeline's gate snapshots, its /tmp). Else None."""
    import re
    p = os.path.realpath(path)
    mp = max((m for m in _mountpoints() if p == m or p.startswith(m.rstrip('/') + '/')), key=len, default='')
    m = re.match(r'^/mnt/([a-z])$', mp)
    if not m:
        return None
    return m.group(1).upper() + ':' + (p[len(mp):] or '/').replace('/', '\\')


class win_file:
    """with win_file(path) as wp: wp = the Windows path of path; a file Windows cannot see is copied to WIN_TMP first and
    removed on exit (self.copied)."""
    def __init__(self, path):
        self.path, self.tmp, self.copied = path, None, False

    def __enter__(self):
        wp = winpath(self.path)
        if wp:
            return wp
        import shutil
        os.makedirs(WIN_TMP, exist_ok=True)
        self.tmp = os.path.join(WIN_TMP, '%d-%s' % (os.getpid(), os.path.basename(self.path)))
        shutil.copyfile(self.path, self.tmp)
        self.copied = True
        wp = winpath(self.tmp)
        if not wp:
            raise OSError('WIN_TMP %s not visible to Windows' % WIN_TMP)
        return wp

    def __exit__(self, *a):
        if self.tmp:
            try:
                os.remove(self.tmp)
            except OSError:
                pass
            self.tmp = None


class gpu_slot:
    """with gpu_slot(): at most GPU_SLOTS WSL processes use CUDA/NVDEC at once (flock on SLOT_DIR/slot<i>); the others
    wait for a slot (never the CPU path). Re-entrant per process; children of a slot holder inherit it (KAH_GPU_SLOT_HELD),
    so a holder waiting on its own child cannot deadlock. No-op off WSL. gpu_slot.hold(): keep one until the process exits
    (a CuPy context lives that long)."""
    def __enter__(self):
        global _slot
        self.mine = False
        if not on_wsl() or _slot is not None or os.environ.get('KAH_GPU_SLOT_HELD'):
            return self
        import fcntl
        try:
            os.makedirs(SLOT_DIR, exist_ok=True)
            os.chmod(SLOT_DIR, 0o777)
        except OSError:
            pass
        t0, warned = time.time(), False
        while True:
            for i in range(GPU_SLOTS):
                try:
                    f = open(os.path.join(SLOT_DIR, 'slot%d' % i), 'a')
                except OSError:
                    return self   # no slot dir: run unlocked rather than fail the check
                try:
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError:
                    f.close()
                    continue
                try:
                    f.seek(0); f.truncate(); f.write('%d %s\n' % (os.getpid(), ' '.join(sys.argv)[:200])); f.flush()
                except OSError:
                    pass
                _slot, self.mine = f, True
                os.environ['KAH_GPU_SLOT_HELD'] = str(os.getpid())
                return self
            if not warned and time.time() - t0 > 60:
                sys.stderr.write('framecache: waiting for a WSL GPU slot (%s, %d slots busy)\n' % (SLOT_DIR, GPU_SLOTS))
                warned = True
            time.sleep(0.2)

    def __exit__(self, *a):
        global _slot
        if self.mine and _slot is not None:
            try:
                import fcntl
                fcntl.flock(_slot.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
            _slot.close()
            _slot = None
            os.environ.pop('KAH_GPU_SLOT_HELD', None)

    @staticmethod
    def hold():
        gpu_slot().__enter__()


def hwdec():
    """ffmpeg input args for NVDEC decode (-hwaccel cuda) when an NVIDIA GPU is visible, else []. ffmpeg falls back to
    software decoding by itself if the hwaccel cannot open. Cuts the decode CPU ~2-3x (41 s 1600x900 take: 4.5 -> 2 cpu-s)
    for ~1 s more wall. ANIMLAB_HWDEC=0 or the host file /etc/kah-no-gpu turns it off. Callers use decode() (Windows-
    native under WSL); these args are its WSL-fallback / Windows-host path."""
    global _hw
    if _hw is None:
        import shutil
        on = os.environ.get('ANIMLAB_HWDEC', '1') != '0' and not no_gpu() and bool(
            shutil.which('nvidia-smi') or os.path.exists('/usr/lib/wsl/lib/nvidia-smi'))
        _hw = ['-hwaccel', 'cuda'] if on else []
    return list(_hw)


class _Proc:
    """Popen + cleanup (temp copy, GPU slot) on wait()."""
    def __init__(self, p, ctx):
        self.p, self.ctx, self.stdout = p, ctx, p.stdout

    def wait(self, *a, **kw):
        try:
            return self.p.wait(*a, **kw)
        finally:
            for c in self.ctx[::-1]:
                c.__exit__(None, None, None)
            self.ctx = []

    def __getattr__(self, k):
        return getattr(self.p, k)


def decode_paths():
    """the decode paths decode() tries, in order: native (Windows ffmpeg.exe NVDEC), hw (ffmpeg NVDEC here), sw"""
    c = []
    if native_on() and os.path.exists(WIN_FFMPEG):
        c.append('native')
    if hwdec():
        c.append('hw')
    return c + ['sw']


def decode(video, pre=(), post=(), popen=False):
    """ffmpeg decode of `video` to stdout (post ends with '-'): pre = args before -i (-ss ...), post = filters + output.
    WSL: Windows ffmpeg.exe -hwaccel cuda (no GPU-PV) -> WSL ffmpeg NVDEC in a gpu_slot -> software. Windows host (4080):
    ffmpeg + hwdec() -> software. Returns a CompletedProcess (stdout bytes); popen=True: the first path as a Popen-like
    (stdout=PIPE; wait() releases its temp copy / slot). ANIMLAB_DECODE=native|hw|sw forces one path (tests)."""
    pre, post = list(pre), list(post)
    base = ['-nostdin', '-loglevel', 'error']
    paths = decode_paths()
    force = os.environ.get('ANIMLAB_DECODE')
    if force:
        paths = [force]
    r = None
    for kind in paths:
        ctx = []
        try:
            if kind == 'native':
                wf = win_file(video)
                vin = wf.__enter__()
                ctx.append(wf)
                cmd = [WIN_FFMPEG] + base + ['-hwaccel', 'cuda'] + pre + ['-i', vin] + post
            elif kind == 'hw':
                s = gpu_slot()
                s.__enter__()
                ctx.append(s)
                cmd = ['ffmpeg'] + base + ['-hwaccel', 'cuda'] + pre + ['-i', video] + post
            else:
                cmd = ['ffmpeg'] + base + pre + ['-i', video] + post
        except OSError:
            for c in ctx[::-1]:
                c.__exit__(None, None, None)
            continue
        if popen:
            return _Proc(subprocess.Popen(cmd, stdout=subprocess.PIPE), ctx)
        try:
            r = subprocess.run(cmd, capture_output=True)
        finally:
            for c in ctx[::-1]:
                c.__exit__(None, None, None)
        if r.returncode == 0 and r.stdout:
            return r
    return r


def native_check(fn):
    """Decorator for a check fn(video, ...) -> JSON-able result whose per-pixel work uses CuPy (gpu.py): in WSL with
    native_on() and WIN_PYTHON present, the call runs in Windows python (native_run.py on a content-hashed copy of this
    module directory, so a gate's snapshot sources are the ones that run) on the Windows path of the video (copied to
    WIN_TMP when Windows cannot see it). Local call when off, for frames=/still= calls, or when the native run fails.
    ANIMLAB_NATIVE_CHECKS=0 = local only."""
    import functools
    sig = inspect.signature(fn)

    @functools.wraps(fn)
    def wrapper(*args, **kw):
        if (not native_on() or os.environ.get('ANIMLAB_NATIVE_CHECKS', '1') == '0' or not os.path.exists(WIN_PYTHON)):
            return fn(*args, **kw)
        try:
            b = sig.bind(*args, **kw)
            b.apply_defaults()
        except TypeError:
            return fn(*args, **kw)
        p = dict(b.arguments)
        video = p.get('video')
        if p.get('frames') is not None or p.get('still') or not isinstance(video, str) or not os.path.isfile(video):
            return fn(*args, **kw)
        try:
            return native_call(fn, p)
        except Exception as e:   # noqa: BLE001  any native failure: the local (WSL) path, same verdict
            sys.stderr.write('framecache: native %s failed (%s): local run\n' % (fn.__name__, str(e)[:300]))
            return fn(*args, **kw)

    return wrapper


_snap_memo = {}


def _snapshot(srcdir):
    """WIN_TMP/src-<sha12 of every *.py in srcdir>: the Windows-side copy of the module directory (made once per content)"""
    import shutil
    if srcdir in _snap_memo:
        return _snap_memo[srcdir]
    names = sorted(n for n in os.listdir(srcdir) if n.endswith('.py'))
    h = hashlib.sha1()
    for n in names:
        h.update(n.encode() + b'\0' + open(os.path.join(srcdir, n), 'rb').read())
    d = os.path.join(WIN_TMP, 'src-' + h.hexdigest()[:12])
    if not os.path.isfile(os.path.join(d, '.complete')):
        os.makedirs(WIN_TMP, exist_ok=True)
        tmp = d + '.tmp%d' % os.getpid()
        os.makedirs(tmp, exist_ok=True)
        for n in names:
            shutil.copyfile(os.path.join(srcdir, n), os.path.join(tmp, n))
        open(os.path.join(tmp, '.complete'), 'w').close()
        try:
            os.rename(tmp, d)
        except OSError:   # another process made it first
            shutil.rmtree(tmp, ignore_errors=True)
        _prune_snapshots(keep=d)
    _snap_memo[srcdir] = d
    return d


def _prune_snapshots(keep, age=86400):
    import shutil
    try:
        for n in os.listdir(WIN_TMP):
            q = os.path.join(WIN_TMP, n)
            if n.startswith('src-') and q != keep and time.time() - os.path.getmtime(q) > age:
                shutil.rmtree(q, ignore_errors=True)
    except OSError:
        pass


def native_call(fn, params):
    """run fn(**params) in Windows python (see native_check); returns its result (tuples kept), echoes its output"""
    mod = sys.modules.get(fn.__module__)
    srcdir = os.path.dirname(os.path.abspath(mod.__file__))
    snap = _snapshot(srcdir)
    runner = winpath(os.path.join(snap, 'native_run.py'))
    if not runner:
        raise OSError('snapshot not visible to Windows')
    with win_file(params['video']) as wv:
        kw = dict(params)
        kw['video'] = wv
        env = {k: v for k, v in os.environ.items() if k.startswith('ANIMLAB_') and not k.startswith('ANIMLAB_WIN_')}
        if winpath(params['video']) is None:
            env['ANIMLAB_FRAMECACHE'] = '0'   # temp copy: no cache files left in WIN_TMP (the WSL wrapper caches the result)
        modname = fn.__module__ if fn.__module__ != '__main__' else os.path.splitext(os.path.basename(mod.__file__))[0]
        job = json.dumps({'module': modname, 'fn': fn.__name__, 'kw': kw, 'env': env})
        r = subprocess.run([WIN_PYTHON, '-P', runner], input=job.encode(), capture_output=True)
    res = None
    for ln in r.stdout.decode('utf-8', 'replace').splitlines():
        if ln.startswith('NATIVE-RESULT '):
            res = json.loads(ln[len('NATIVE-RESULT '):])
        else:
            print(ln)
    if r.stderr:
        err = r.stderr.decode('utf-8', 'replace')
        if r.returncode != 0 or res is None:
            raise RuntimeError('rc=%d %s' % (r.returncode, err.strip().splitlines()[-1] if err.strip() else ''))
        sys.stderr.write(err)
    if res is None:
        raise RuntimeError('rc=%d no NATIVE-RESULT' % r.returncode)
    v = res['v']
    return tuple(v) if res['tuple'] else v


def _probe(video):
    out = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', video],
                         capture_output=True, text=True).stdout.strip()
    try:
        return float(out)
    except ValueError:
        return None


def frames(video, fps, w, h, t0=None, t1=None):
    """uint8 (N, h, w, 3) memmap of the video at fps / w x h, frame i at i / fps; None when caching is off or too big."""
    import numpy as np
    if not enabled() or not os.path.isfile(video):
        return None
    dur = _probe(video)
    if dur is None or dur * fps * w * h * 3 / 1e6 > MAX_MB:
        return None
    base = os.path.join(cache_dir(video), 'f%g-%dx%d' % (fps, w, h))
    meta = base + '.json'
    if not os.path.exists(meta):
        with Lock(base):
            if not os.path.exists(meta):   # first caller decodes; the others waited on the lock and reuse it
                tmp = base + '.u8.tmp%d' % os.getpid()   # per process: a WSL and a Windows-native writer never share it
                r = decode(video, post=['-vf', 'fps=%g,scale=%d:%d' % (fps, w, h), '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'])
                if r is None or r.returncode != 0:
                    return None
                with open(tmp, 'wb') as f:
                    f.write(r.stdout)
                n = os.path.getsize(tmp) // (w * h * 3)
                os.replace(tmp, base + '.u8')
                with open(meta + '.tmp', 'w') as f:
                    json.dump({'n': n, 'fps': fps, 'w': w, 'h': h, 'video': os.path.basename(video)}, f)
                os.replace(meta + '.tmp', meta)
    with open(meta) as fh:
        n = json.load(fh)['n']
    if n == 0:
        return np.zeros((0, h, w, 3), np.uint8)
    a = np.memmap(base + '.u8', np.uint8, 'r', shape=(n, h, w, 3))
    i0 = max(0, int(round((t0 or 0) * fps)))
    i1 = n if t1 is None else min(n, int(round(t1 * fps)))
    return a[i0:i1]


def _src_hash(fn):
    mod = sys.modules.get(fn.__module__)
    p = getattr(mod, '__file__', None)
    if p not in _src_memo:
        try:
            _src_memo[p] = hashlib.sha1(open(p, 'rb').read() + open(__file__, 'rb').read()).hexdigest()[:12]
        except (OSError, TypeError):
            _src_memo[p] = 'nosrc'
    return _src_memo[p]


def cached_check(name, fn):
    """Wrap fn(video, ...) so identical calls on the same video content share one run (see module doc)."""
    sig = inspect.signature(fn)

    def wrapper(*args, **kw):
        try:
            b = sig.bind(*args, **kw); b.apply_defaults()
        except TypeError:
            return fn(*args, **kw)
        p = dict(b.arguments)
        video = p.pop('video', None)
        if not enabled() or p.get('frames') is not None or not isinstance(video, str) or not os.path.isfile(video):
            return fn(*args, **kw)
        p.pop('frames', None)
        p.pop('name', None)   # label only, never changes the verdict
        key = hashlib.sha1(json.dumps([name, _src_hash(fn), p], sort_keys=True, default=repr).encode()).hexdigest()[:16]
        path = os.path.join(cache_dir(video), 'r-%s-%s.json' % (name, key))
        if not os.path.exists(path):
            with Lock(path):
                if not os.path.exists(path):
                    r = fn(*args, **kw)
                    with open(path + '.tmp', 'w') as f:
                        json.dump({'tuple': isinstance(r, tuple), 'v': r, 'params': p}, f, default=repr)
                    os.replace(path + '.tmp', path)
                    return r
        d = json.load(open(path))
        return tuple(d['v']) if d['tuple'] else d['v']

    wrapper.__wrapped__ = fn
    wrapper.__doc__ = fn.__doc__
    return wrapper


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in ('info', 'clear'):
        print(__doc__); return 2
    d = cache_dir(sys.argv[2])
    for e in sorted(os.listdir(d)):
        print('%10d %s' % (os.path.getsize(os.path.join(d, e)), e))
        if sys.argv[1] == 'clear':
            os.remove(os.path.join(d, e))
    if sys.argv[1] == 'clear':
        os.rmdir(d)
    return 0


if __name__ == '__main__':
    sys.exit(main())
