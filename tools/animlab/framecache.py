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
        d = os.path.join(os.environ.get('TMPDIR', '/tmp'), 'animlab-framecache', '%s-%s' % (stem, fingerprint(video)[:12]))
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


def hwdec():
    """ffmpeg input args for NVDEC decode (-hwaccel cuda) when an NVIDIA GPU is visible, else []. ffmpeg falls back to
    software decoding by itself if the hwaccel cannot open. Cuts the decode CPU ~2-3x (41 s 1600x900 take: 4.5 -> 2 cpu-s)
    for ~1 s more wall. ANIMLAB_HWDEC=0 turns it off."""
    global _hw
    if _hw is None:
        import shutil
        on = os.environ.get('ANIMLAB_HWDEC', '1') != '0' and bool(
            shutil.which('nvidia-smi') or os.path.exists('/usr/lib/wsl/lib/nvidia-smi'))
        _hw = ['-hwaccel', 'cuda'] if on else []
    return list(_hw)


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
                tmp = base + '.u8.tmp'
                cmd = ['ffmpeg', '-nostdin', '-loglevel', 'error'] + hwdec() + ['-i', video, '-vf', 'fps=%g,scale=%d:%d' % (fps, w, h),
                       '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-y', tmp]
                rc = subprocess.run(cmd).returncode
                if rc != 0 and cmd[4] == '-hwaccel':
                    del cmd[4:6]   # NVDEC refused: software decode
                    rc = subprocess.run(cmd).returncode
                if rc != 0:
                    return None
                n = os.path.getsize(tmp) // (w * h * 3)
                os.replace(tmp, base + '.u8')
                with open(meta + '.tmp', 'w') as f:
                    json.dump({'n': n, 'fps': fps, 'w': w, 'h': h, 'video': os.path.basename(video)}, f)
                os.replace(meta + '.tmp', meta)
    n = json.load(open(meta))['n']
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
