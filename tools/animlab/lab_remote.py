#!/usr/bin/env python3
"""lab_remote.py -- remote lab slots on the 4080 PC (load-balance 2026-10-11: the 5090 lab ran serial optimizers while the
4080's CPU idled between takes). An objective that replays recordings through a kfpvm adapter and scores them in Python
(e.g. /root/strokefix/obj.py evaluate) runs part of each optimizer population on the 4080, in Windows Python, at IDLE
priority (takes and Kenshi keep the CPU; Windows Python, never the 4080's WSL: GPU-PV/TDR suspect + its LLM stays off).

5090 side (WSL):
  from lab_remote import Remote, split_batch
  rem = Remote('/root/strokefix/obj.py', 'evaluate', adapter='/root/animlab-build/sjl_v4',
               data=['/mnt/c/KenshiTestRuns/corpus/pools/sword-swing'], env={'TRAV': '2=0.40:0.46'}, workers=4)
  batch = split_batch(local_batch, rem.batch(lambda x: (s, kv(x), 'o')), on_result)   # local + remote share, adaptive
  rem.close()
  - adapter: the Linux adapter binary; its source dir <adapter>.d (build.sh layout) is cross-compiled with mingw
    (same -D flags as build.sh) into <adapter>.exe once (kept while the .d tree is unchanged) and copied to the 4080 by
    content hash. Windows libm differs in the last digit (measured pt30-sword s2: 8 of 427 lines, max |d| 0.0019), so
    re-check the final optimum locally.
  - module: copied to the 4080; '/mnt/c/' becomes 'C:/' in its source, the adapter env ADP points at the .exe, its temp dir
    lines are mapped with maps={'/root/strokefix/tmp': 'C:/KAH/lab/tmp'} (default: <module dir>/tmp).
  - data: local dirs under /mnt/c/ copied (tar over ssh, only when changed) to the same C:/ path on the 4080.
  - LAB_REMOTE=0 disables the remote (split_batch then runs everything locally); a dead ssh/remote error -> the points
    are evaluated locally (never lost), the remote is dropped for the rest of the run.

4080 side (started by Remote over ssh):  python lab_remote.py serve --module M --func F --workers N [--env K=V]...
  one JSON per line in: {"id": n, "args": [...]}; out: {"id": n, "r": result} | {"id": n, "err": "..."}; first line
  {"ready": N}.  selftest (WSL): python3 lab_remote.py selftest
"""
import hashlib, json, os, queue, shlex, subprocess, sys, threading, time

SSH = os.environ.get('LAB_REMOTE_SSH', '/mnt/c/Windows/System32/OpenSSH/ssh.exe')
HOST = os.environ.get('LAB_REMOTE_HOST', '4080')
RPY = os.environ.get('LAB_REMOTE_PY', 'C:/Users/Shay/AppData/Local/Programs/Python/Python313/python.exe')
RROOT = 'C:/KAH/lab'
ME_REMOTE = 'C:/KenshiModding/Kenshi-Automation-Harness/tools/animlab/lab_remote.py'
HERE = os.path.dirname(os.path.abspath(__file__))
BUILD_FLAGS = [('g_vm_elb_cb', 'AL_HAVE_ELB_CB'), ('g_vm_eclamp_n', 'AL_HAVE_ECLAMP'), ('g_vm_hcap_n', 'AL_HAVE_HINGE'),
               ('g_vm_2htau', 'AL_HAVE_2H'), ('g_vm_2hbw', 'AL_HAVE_2HB'), ('vm_pd_write', 'AL_HAVE_POSEDUMP'),
               ('g_al_hoff', 'AL_HAVE_HOFF'), ('g_al_l1n_rec', 'AL_HAVE_L1REC')]   # = components/KenshiFP/animlab/build.sh
ANIMLAB_SRC = '/mnt/c/KenshiModding/components/KenshiFP/animlab'


def sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def ssh(cmd, inp=None, timeout=600):
    return subprocess.run([SSH, '-o', 'BatchMode=yes', HOST, cmd], input=inp, capture_output=True, timeout=timeout)


def winbuild(adapter, main='kfpvm_replay.c'):
    """mingw build of a build.sh adapter (<adapter>.d source tree) -> <adapter>.exe, rebuilt only when inputs change."""
    d = adapter + '.d'
    v = os.path.join(d, 'client', 'kfp_viewmodel.inc')
    src = open(v, errors='replace').read()
    defs = ['-D' + m for k, m in BUILD_FLAGS if k in src]
    h = hashlib.sha256(' '.join(defs + [main]).encode())
    for root in (d, ANIMLAB_SRC):
        for dp, dn, fn in sorted(os.walk(root)):
            dn.sort()
            if root == ANIMLAB_SRC and dp != root:
                continue
            for f in sorted(fn):
                if root == ANIMLAB_SRC and not f.endswith(('.c', '.h')):
                    continue
                h.update(f.encode()); h.update(sha(os.path.join(dp, f)).encode())
    key = h.hexdigest()[:16]
    exe, stamp = adapter + '.exe', adapter + '.exe.key'
    if os.path.exists(exe) and os.path.exists(stamp) and open(stamp).read().strip() == key:
        return exe
    cmd = ['x86_64-w64-mingw32-gcc', '-O2', '-std=gnu11', '-w'] + defs + ['-I' + d, '-I' + os.path.join(d, 'client'),
                                                                          '-I' + ANIMLAB_SRC, '-static', '-o', exe,
                                                                          os.path.join(ANIMLAB_SRC, main), '-lm']
    subprocess.run(cmd, check=True)
    open(stamp, 'w').write(key + '\n')
    return exe


def push_file(local, remote_dir):
    """copy a file to <remote_dir>/<sha12>-<name> unless present; returns the remote path."""
    rp = '%s/%s-%s' % (remote_dir, sha(local)[:12], os.path.basename(local))
    r = ssh('if exist "%s" (echo HAVE) else (mkdir "%s" 2>nul & echo NEED)' % (rp.replace('/', '\\'), remote_dir.replace('/', '\\')))
    if b'NEED' in r.stdout:
        with open(local, 'rb') as f:
            data = f.read()
        r = ssh('%s -c "import sys;open(sys.argv[1],\'wb\').write(sys.stdin.buffer.read())" %s' % (RPY, rp), inp=data)
        if r.returncode:
            raise RuntimeError('push %s: %s' % (local, r.stderr.decode(errors='replace')[-300:]))
    return rp


def push_dir(local):
    """tar a /mnt/c/<x> dir to C:/<x> on the remote when its listing (names+sizes+mtimes) changed."""
    assert local.startswith('/mnt/c/'), local
    rdir = 'C:/' + local[len('/mnt/c/'):]
    lst = []
    for dp, dn, fn in os.walk(local):
        for f in fn:
            st = os.stat(os.path.join(dp, f)); lst.append('%s %d %d' % (os.path.relpath(os.path.join(dp, f), local), st.st_size, int(st.st_mtime)))
    key = hashlib.sha256('\n'.join(sorted(lst)).encode()).hexdigest()[:16]
    mark = rdir + '/.lab_remote.' + key
    r = ssh('if exist "%s" (echo HAVE) else (echo NEED)' % mark.replace('/', '\\'))
    if b'NEED' in r.stdout:
        tar = subprocess.run(['tar', '-C', local, '-cf', '-', '.'], capture_output=True, check=True).stdout
        r = ssh('mkdir "%s" 2>nul & tar -xf - -C "%s" && type nul > "%s"' % (rdir.replace('/', '\\'), rdir, mark.replace('/', '\\')), inp=tar)
        if r.returncode:
            raise RuntimeError('push dir %s: %s' % (local, r.stderr.decode(errors='replace')[-300:]))
    return rdir


class Remote:
    def __init__(self, module, func, adapter=None, data=(), env=None, workers=4, maps=None):
        self.ok, self.workers, self.lock = False, workers, threading.Lock()
        if os.environ.get('LAB_REMOTE', '1') == '0':
            return
        try:
            me = push_file(os.path.join(HERE, 'lab_remote.py'), RROOT + '/bin')
            env = dict(env or {})
            if adapter:
                env['ADP'] = push_file(winbuild(adapter), RROOT + '/bin')
            src = open(module).read().replace('/mnt/c/', 'C:/')
            mp = {os.path.join(os.path.dirname(module), 'tmp'): RROOT + '/tmp'}
            mp["os.system('rm -rf ' + d)"] = "__import__('shutil').rmtree(d, True)"   # obj.py temp cleanup, no rm on Windows
            mp.update(maps or {})
            for a, b in mp.items():
                src = src.replace(a, b)
            tmpm = '/tmp/lab_remote_%s' % os.path.basename(module)
            open(tmpm, 'w').write(src)
            mod = push_file(tmpm, RROOT + '/mod')
            for dd in data:
                push_dir(dd)
            env.setdefault('ANIMLAB_CACHE_DIR', RROOT + '/cache')
            env.setdefault('OBJ_J', '1')
            cmd = '%s -u %s serve --module %s --func %s --workers %d %s' % (
                RPY, me, mod, func, workers, ' '.join('--env "%s=%s"' % (k, v) for k, v in env.items()))
            self.p = subprocess.Popen([SSH, '-o', 'BatchMode=yes', '-o', 'ServerAliveInterval=30', HOST, cmd],
                                      stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
            line = self.p.stdout.readline()
            if '"ready"' not in line:
                raise RuntimeError('remote did not start: %r %s' % (line, self.p.stderr.read()[-500:] if self.p.poll() is not None else ''))
            self.ok, self.n = True, 0
        except Exception as e:   # noqa: BLE001
            print('lab_remote: remote off (%s)' % e, file=sys.stderr, flush=True)

    def map(self, argss, env=None):
        """evaluate a list of argument tuples on the remote; raises on any failure (caller falls back locally)."""
        with self.lock:
            ids = []
            for a in argss:
                self.n += 1; ids.append(self.n)
                self.p.stdin.write(json.dumps({'id': self.n, 'args': list(a), 'env': env or {}}) + '\n')
            self.p.stdin.flush()
            res = {}
            while len(res) < len(ids):
                line = self.p.stdout.readline()
                if not line:
                    self.p.wait(10)
                    raise RuntimeError('remote closed rc=%s: %s' % (self.p.returncode, self.p.stderr.read()[-800:]))
                m = json.loads(line)
                if 'err' in m:
                    raise RuntimeError('remote error: ' + m['err'][-500:])
                res[m['id']] = m['r']
            return [res[i] for i in ids]

    def close(self):
        if self.ok:
            try:
                # short wait: the 4080 side drains its pool + temp dirs on its own (a 30 s wait cost every run 30 s)
                self.p.stdin.close(); self.p.wait(3)
            except Exception:   # noqa: BLE001
                self.p.kill()
            self.ok = False


def split_batch(local_batch, remote, to_args, local_workers=12, on_result=None, inner_env='OBJ_J'):
    """batch(xs): the remote evaluates k of xs (to_args(x) -> args for the remote func, which returns value or
    [value, extra]) while local_batch(rest) runs. k adapts so both sides finish together: +1 when the remote finished
    under 80% of the local time, -1 when it took over 120% (down to 0 = remote idle; then one probe point every 5th
    batch). Each remote point gets inner parallelism <inner_env>=workers//k (e.g. OBJ_J replays at once) so a small
    share is not latency-bound (2026-10-11: 3 points x OBJ_J=1 took 14 s on the 4080 vs 8 s for 9 points locally).
    on_result(x, value, extra) for the remote points (local_batch reports its own)."""
    st = {'k': None, 'n': 0, 'tl': None, 'tr': None}

    def batch(xs):
        xs = [list(x) for x in xs]
        st['n'] += 1
        if not remote.ok or len(xs) < 2:
            return local_batch(xs)
        if st['k'] is None:
            st['k'] = max(1, int(round(len(xs) * remote.workers / float(remote.workers + local_workers) * 0.5)))
        k = min(st['k'], len(xs) - 1)
        if k == 0 and st['n'] % 5 == 0:
            k = 1   # probe: the 4080 may be free again
        if k == 0:
            return local_batch(xs)
        rx, lx = xs[:k], xs[k:]
        out = {}

        def rem():
            t = time.time()
            try:
                rs = remote.map([to_args(x) for x in rx], env={inner_env: str(max(1, remote.workers // k))} if inner_env else None)
                vals = []
                for x, r in zip(rx, rs):
                    v, extra = (r[0], r[1]) if isinstance(r, list) else (r, None)
                    if on_result:
                        on_result(x, v, extra)
                    vals.append(v)
                out['r'] = vals
                st['tr'] = time.time() - t
            except Exception as e:   # noqa: BLE001
                print('lab_remote: remote failed (%s), evaluating its %d points locally' % (e, len(rx)), file=sys.stderr, flush=True)
                remote.ok = False
        th = threading.Thread(target=rem); th.start()
        t = time.time(); lv = list(local_batch(lx)); st['tl'] = time.time() - t
        th.join()
        rv = out['r'] if 'r' in out else list(local_batch(rx))
        if os.environ.get('LAB_REMOTE_V'):
            print('lab_remote: batch %d k=%d/%d local %.1fs remote %s' % (st['n'], k, len(xs), st['tl'],
                  '%.1fs' % st['tr'] if 'r' in out else 'failed'), file=sys.stderr, flush=True)
        if 'r' in out:
            if st['tr'] < 0.8 * st['tl']:
                st['k'] = k + 1
            elif st['tr'] > 1.2 * st['tl']:
                st['k'] = k - 1
            else:
                st['k'] = k
        return rv + lv
    batch.stats = st
    return batch


# ---------------- 4080 side ----------------
_F = None


def _init(module, func, env):
    global _F
    os.environ.update(env)
    import importlib.util
    spec = importlib.util.spec_from_file_location('labremote_mod', module)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    _F = getattr(m, func)


def _call(args, env=None):
    os.environ.update(env or {})
    r = _F(*args)
    tmp = RROOT + '/tmp'   # modules that rm -rf their temp dirs with os.system leak them on Windows: drop old ones
    try:
        import shutil
        now = time.time()
        for d in os.listdir(tmp):
            p = os.path.join(tmp, d)
            if now - os.path.getmtime(p) > 300:
                shutil.rmtree(p, ignore_errors=True)
    except OSError:
        pass
    return list(r) if isinstance(r, tuple) else r


def serve(argv):
    import argparse
    from concurrent.futures import ProcessPoolExecutor
    ap = argparse.ArgumentParser()
    ap.add_argument('--module'); ap.add_argument('--func'); ap.add_argument('--workers', type=int, default=4)
    ap.add_argument('--env', action='append', default=[])
    a = ap.parse_args(argv)
    env = dict(e.split('=', 1) for e in a.env)
    os.makedirs(RROOT + '/tmp', exist_ok=True)
    now = time.time()   # pushed files are content-addressed and never reused once changed: drop ones unused for 2 days
    for sub in ('bin', 'mod'):
        try:
            for f in os.listdir(RROOT + '/' + sub):
                p = RROOT + '/' + sub + '/' + f
                if now - os.path.getatime(p) > 2 * 86400 and now - os.path.getmtime(p) > 2 * 86400:
                    os.remove(p)
        except OSError:
            pass
    # the protocol owns the ssh stdin: every child (pool workers, adapters, os.system shells) gets NUL instead, else a
    # child holding/reading the inherited pipe ended the loop after the first batch (2026-10-11, remote exited rc 0)
    proto = os.fdopen(os.dup(0), 'r')
    nul = os.open(os.devnull, os.O_RDONLY); os.dup2(nul, 0)
    if os.name == 'nt':
        import ctypes, msvcrt
        ctypes.windll.kernel32.SetStdHandle(-10, msvcrt.get_osfhandle(0))
    sys.stdin = open(os.devnull)
    if os.name == 'nt':   # IDLE priority class: inherited by the pool and the adapter processes; takes/Kenshi keep the CPU
        import ctypes
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x40)
    out_lock = threading.Lock()
    with ProcessPoolExecutor(a.workers, initializer=_init, initargs=(a.module, a.func, env)) as ex:
        print(json.dumps({'ready': a.workers}), flush=True)

        def done(fut, i):
            try:
                m = {'id': i, 'r': fut.result()}
            except Exception as e:   # noqa: BLE001
                m = {'id': i, 'err': repr(e)}
            with out_lock:
                print(json.dumps(m), flush=True)
        for line in proto:
            if not line.strip():
                continue
            q = json.loads(line)
            fut = ex.submit(_call, q['args'], q.get('env'))
            fut.add_done_callback(lambda f, i=q['id']: done(f, i))
    import shutil   # pool closed: drop this run's temp dirs (modules that rm -rf via os.system leak them on Windows)
    for d in os.listdir(RROOT + '/tmp'):
        shutil.rmtree(os.path.join(RROOT + '/tmp', d), ignore_errors=True)


def selftest():
    """objective round trip on the 4080 (tiny module, no adapter): split_batch result order + values, fallback when off."""
    mod = '/tmp/lab_remote_selftest_obj.py'
    open(mod, 'w').write('def evaluate(x):\n    import os\n    return (sum((v - 1) ** 2 for v in x), os.name)\n')
    rem = Remote(mod, 'evaluate', workers=2)
    assert rem.ok, 'remote did not start'
    seen = []

    def local(xs):
        return [sum((v - 1) ** 2 for v in x) for x in xs]
    b = split_batch(local, rem, lambda x: (x,), local_workers=2, on_result=lambda x, v, e: seen.append(e))
    xs = [[i * 0.1, 1.0] for i in range(8)]
    vals = b(xs)
    rem.close()
    assert all(abs(v - w) < 1e-12 for v, w in zip(vals, local(xs))), (vals, local(xs))
    assert seen and all(e == 'nt' for e in seen), seen
    os.environ['LAB_REMOTE'] = '0'
    off = Remote(mod, 'evaluate')
    assert not off.ok and split_batch(local, off, lambda x: (x,))(xs) == local(xs)
    print('lab_remote selftest PASS (remote evaluated %d of %d points on the 4080)' % (len(seen), len(xs)))


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'serve':
        serve(sys.argv[2:])
    elif len(sys.argv) > 1 and sys.argv[1] == 'selftest':
        selftest()
    else:
        print(__doc__)
