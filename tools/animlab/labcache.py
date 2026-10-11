#!/usr/bin/env python3
"""labcache.py -- content-addressed result cache for the animation lab (Shay 2026-10-10: cut the 5090's CPU load; the
gate / regress / pool / mutation / weapon-matrix / climb runs replayed the same recordings through the same solver for
every tree of every pipeline run).

What is cached (each entry = stdout + stderr + exit code + the output files, keyed by CONTENT, never by names or times):
  replay   an adapter run `<adapter> <rec> <out> [args]` (kfpvm_replay / kfpvm_drive builds): key = sha of the adapter
           binary + the recording + every argument (arguments that are existing files are hashed by content too).
           Outputs: <out> and every <out>.* sidecar it writes (e.g. <out>.bolt). A tree whose patch does not change the
           compiled solver (the adapter only compiles the viewmodel) gets identical binaries (build cache below) and
           therefore pure cache hits.
  build    build.sh's gcc step: key = sha of every compile input (the patched client copy, the harness main + headers in
           components/KenshiFP/animlab, -D flags, gcc version). Outputs: the binary.
  check    a pure recording check `animlab.py <check> <rec> ...` (metrics, hinge, bolt, churn, inline, branch, blade,
           stroke, guard, zoomband, stock, reload, spike, compare, ...): key = sha of all lab code (*.py of this dir) +
           every argument (+ content of file arguments and their `<file>.*` sidecars) + ANIMLAB_* / AL_* env.
Mode (env ANIMLAB_CACHE): 1 (default) use + fill; 0 off (always compute, store nothing); verify = always compute and
compare with the stored entry (a mismatch is printed to stderr and appended to <dir>/verify-mismatch.log; the computed
result is used), the proof that a key misses no input.
Store: ANIMLAB_CACHE_DIR (default /root/animlab-cache), entries <dir>/e/<k[:2]>/<k>/; LRU: a hit touches the entry, a
store prunes the oldest entries when the total passes ANIMLAB_CACHE_MAX_MB (default 6000). Writes are atomic (tmp dir +
rename) and a per-key flock makes concurrent identical computations (parallel gates of base/all trees) wait for the first
one instead of computing twice. Only clean results are stored (exit 0/1, no Python traceback, no signal).
CLI (shell callers, e.g. regress.sh):
  labcache.py replay <adapter> <rec> <out> [adapter args]   run (or restore) an adapter replay; prints its stdout/stderr, exits with its code
  labcache.py run --in <file>[,<file>] --out <file>[,<file>] [--tag <str>] [--nocmd] -- <command...>   generic memo of a
           command (key = content of --in + tag + the command line with file arguments hashed; --nocmd: the command line
           is left out of the key, --in must then name every input, e.g. build.sh's compile-input manifest)
  labcache.py stats | prune | clear | key <file>
"""
import contextlib, fcntl, hashlib, io, json, os, shlex, shutil, subprocess, sys, tempfile, time

DIR = os.environ.get('ANIMLAB_CACHE_DIR', '/root/animlab-cache')
MAX_MB = float(os.environ.get('ANIMLAB_CACHE_MAX_MB', '6000'))
HERE = os.path.dirname(os.path.abspath(__file__))
VERSION = 'labcache-1'   # bump to invalidate every entry (key format change)
_fh = {}
_code = {}


def mode():
    m = os.environ.get('ANIMLAB_CACHE', '1').strip().lower()
    return m if m in ('0', '1', 'verify') else '1'


def fhash(path):
    """sha256 of a file's content, memoised per (path, size, mtime)."""
    st = os.stat(path)
    k = (os.path.abspath(path), st.st_size, st.st_mtime_ns)
    if k not in _fh:
        h = hashlib.sha256()
        with open(path, 'rb') as f:
            for b in iter(lambda: f.read(1 << 22), b''):
                h.update(b)
        _fh[k] = h.hexdigest()
    return _fh[k]


def code_hash(d=HERE, exts=('.py',)):
    """sha of every lab source file in d (recursive, no tests/caches): the 'check code version'."""
    if d not in _code:
        h = hashlib.sha256()
        for root, dirs, files in os.walk(d):
            dirs[:] = sorted(x for x in dirs if x not in ('__pycache__', '.framecache'))
            for f in sorted(files):
                if f.endswith(exts):
                    p = os.path.join(root, f)
                    h.update(os.path.relpath(p, d).encode() + b'\0' + fhash(p).encode())
        _code[d] = h.hexdigest()
    return _code[d]


def argkey(args, sidecars=False, lists=False):
    """argument list -> key parts: literal text + content hash for every argument that is an existing file
    ('--opt=file' forms too); sidecars: also <file>.* next to it; lists: '@list' files + every file they name."""
    out = []
    for a in args:
        a = str(a)
        part = [a]
        cands = [a] + ([a.split('=', 1)[1]] if a.startswith('-') and '=' in a else [])
        if ' ' in a:   # a quoted command ('--adapter "/x/kfpvm --flag"'): hash its file tokens too
            try:
                cands += shlex.split(a)
            except ValueError:
                pass
        if lists and a.startswith('@') and os.path.isfile(a[1:]):
            d = os.path.dirname(a[1:]) or '.'
            names = [l.strip() for l in open(a[1:]) if l.strip() and not l.startswith('#')]
            part.append([fhash(a[1:])] + [[n, fhash(os.path.join(d, n))] for n in names if os.path.isfile(os.path.join(d, n))])
        for c in cands:
            if c and os.path.isfile(c):
                part.append(fhash(c))
                if sidecars:
                    dn, bn = os.path.split(os.path.abspath(c))
                    try:
                        sc = sorted(f for f in os.listdir(dn) if f.startswith(bn + '.') and os.path.isfile(os.path.join(dn, f)))
                    except OSError:
                        sc = []
                    part.append([[f[len(bn):], fhash(os.path.join(dn, f))] for f in sc])
        out.append(part)
    return out


def env_part():
    return sorted((k, v) for k, v in os.environ.items()
                  if (k.startswith('ANIMLAB_') or k.startswith('AL_')) and not k.startswith('ANIMLAB_CACHE')
                  and k not in ('ANIMLAB_WORK', 'ANIMLAB_FRAMECACHE', 'ANIMLAB_FRAMECACHE_MAX_MB'))


def make_key(kind, parts):
    return hashlib.sha256(json.dumps([VERSION, kind, parts], sort_keys=True, default=str).encode()).hexdigest()


def _edir(k):
    return os.path.join(DIR, 'e', k[:2], k)


class _Lock:
    def __init__(self, k):
        os.makedirs(os.path.join(DIR, 'locks'), exist_ok=True)
        self.p = os.path.join(DIR, 'locks', k[:16])

    def __enter__(self):
        self.f = open(self.p, 'a')
        fcntl.flock(self.f, fcntl.LOCK_EX)
        return self

    def __exit__(self, *e):
        fcntl.flock(self.f, fcntl.LOCK_UN)
        self.f.close()


def _load(k):
    d = _edir(k)
    try:
        meta = json.load(open(os.path.join(d, 'meta.json')))
    except (OSError, ValueError):
        return None
    try:
        os.utime(d)   # LRU
    except OSError:
        pass
    meta['dir'] = d
    return meta


def _restore(meta, outputs):
    """copy stored files back; outputs = list of (stored name, target path)."""
    for name, tgt in outputs:
        src = os.path.join(meta['dir'], 'f', name)
        if os.path.isfile(src):
            if os.path.dirname(tgt):
                os.makedirs(os.path.dirname(tgt), exist_ok=True)
            tmp = tgt + '.lc%d' % os.getpid()
            shutil.copyfile(src, tmp); shutil.copymode(src, tmp)
            os.replace(tmp, tgt)


def _store(k, meta, files):
    """files: {stored name: source path}. Atomic: written into a tmp dir, renamed into place."""
    if mode() == '0':
        return
    d = _edir(k)
    os.makedirs(os.path.dirname(d), exist_ok=True)
    tmp = tempfile.mkdtemp(prefix='.tmp-', dir=os.path.dirname(d))
    try:
        os.makedirs(os.path.join(tmp, 'f'))
        size = 0
        for name, src in files.items():
            shutil.copy2(src, os.path.join(tmp, "f", name))
            size += os.path.getsize(src)
        meta = dict(meta, size=size + len(meta.get('stdout', '')) + len(meta.get('stderr', '')), t=time.time())
        with open(os.path.join(tmp, 'meta.json'), 'w') as f:
            json.dump(meta, f)
        if os.path.isdir(d):
            shutil.rmtree(d, ignore_errors=True)
        os.rename(tmp, d)
    except OSError:
        shutil.rmtree(tmp, ignore_errors=True)
        return
    _account(meta['size'])


def _account(n):
    """running total in <dir>/size; prune when over the cap (checked every ~200 MB stored)."""
    p = os.path.join(DIR, 'size')
    try:
        with open(p, 'a+') as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            f.seek(0)
            v = f.read().split()
            tot, since = (int(v[0]), int(v[1])) if len(v) == 2 else (0, 1 << 40)
            tot += n
            since += n
            if since > 200 << 20:
                tot = prune(quiet=True)
                since = 0
            f.seek(0)
            f.truncate()
            f.write('%d %d' % (tot, since))
    except OSError:
        pass


def entries():
    r = []
    base = os.path.join(DIR, 'e')
    if not os.path.isdir(base):
        return r
    for a in os.listdir(base):
        for k in os.listdir(os.path.join(base, a)):
            d = os.path.join(base, a, k)
            if k.startswith('.tmp-'):
                if time.time() - os.path.getmtime(d) > 3600:
                    shutil.rmtree(d, ignore_errors=True)
                continue
            try:
                sz = json.load(open(os.path.join(d, 'meta.json'))).get('size', 0)
                r.append((os.path.getmtime(d), sz, d))
            except (OSError, ValueError):
                shutil.rmtree(d, ignore_errors=True)
    return r


def prune(quiet=False):
    """LRU: delete the least recently used entries until the total is under 80% of the cap. Returns the total."""
    es = sorted(entries())
    tot = sum(e[1] for e in es)
    cap = MAX_MB * (1 << 20)
    n = 0
    if tot > cap:
        for t, sz, d in es:
            if tot <= 0.8 * cap:
                break
            shutil.rmtree(d, ignore_errors=True)
            tot -= sz
            n += 1
    if not quiet:
        print('labcache: %d entries, %.0f MB (cap %.0f MB), pruned %d' % (len(es) - n, tot / (1 << 20), MAX_MB, n))
    return tot


def _clean(rc, stderr):
    return rc in (0, 1) and 'Traceback (most recent call last)' not in (stderr or '')


def _verify(k, old, rc, so, se, files):
    bad = []
    if old['rc'] != rc:
        bad.append('rc %s->%s' % (old['rc'], rc))
    if old.get('stdout') != so:
        bad.append('stdout')
    for name, src in files.items():
        p = os.path.join(old['dir'], 'f', name)
        if not os.path.isfile(p) or fhash(p) != fhash(src):
            bad.append('file ' + name)
    if bad:
        line = '%s %s %s MISMATCH %s' % (time.strftime('%F %T'), k[:16], old.get('what', '')[:200], ','.join(bad))
        sys.stderr.write('labcache: ' + line + '\n')
        try:
            with open(os.path.join(DIR, 'verify-mismatch.log'), 'a') as f:
                f.write(line + '\n')
        except OSError:
            pass
    return not bad


def _stat(kind, hit):
    """per-process hit counters, flushed into <dir>/stats.tsv at exit (cheap: one line per process)."""
    _counts[(kind, hit)] = _counts.get((kind, hit), 0) + 1


_counts = {}


def _flush():
    if not _counts:
        return
    try:
        os.makedirs(DIR, exist_ok=True)
        with open(os.path.join(DIR, 'stats.tsv'), 'a') as f:
            f.write('%d\t%s\n' % (time.time(), ' '.join('%s:%s=%d' % (k, 'hit' if h else 'miss', n) for (k, h), n in sorted(_counts.items()))))
    except OSError:
        pass


import atexit  # noqa: E402
atexit.register(_flush)


class _Budget:
    """One CPU budget (Shay 2026-10-10): a computed (cache-miss) adapter run / build outside any labnice.sh job takes one
    labnice slot (/tmp/labnice/slot.<i>, the same pool labnice.sh uses, LABNICE_SLOTS default nproc/2) and runs at
    nice 15, and waits while a 5090 take records (lab-recpause.sh --recording). So ad-hoc climbs, auto-review and
    weapon-matrix runs started without the wrapper still count against the one budget. Inside a labnice job
    (LABNICE_SLOT set) the job's own slots apply (pool sized by LABNICE_J). LABNICE_EXEMPT=1 skips it."""
    D = '/tmp/labnice'
    PAUSE = '/mnt/c/KenshiModding/tools/automation/lab-recpause.sh'

    def __enter__(self):
        self.f = None
        if os.environ.get('LABNICE_SLOT') or os.environ.get('LABNICE_EXEMPT') or not os.path.isdir('/proc'):
            return self
        try:
            os.nice(15 - os.nice(0)) if os.nice(0) < 15 else None
        except OSError:
            pass
        t0 = time.time()
        while os.path.isfile(self.PAUSE) and time.time() - t0 < 1800 and \
                subprocess.run(['bash', self.PAUSE, '--recording'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
            time.sleep(3)
        n = int(os.environ.get('LABNICE_SLOTS') or max(1, (os.cpu_count() or 2) // 2))
        os.makedirs(self.D, exist_ok=True)
        while True:
            for i in range(1, n + 1):
                f = open(os.path.join(self.D, 'slot.%d' % i), 'a')
                try:
                    fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    self.f = f
                    return self
                except OSError:
                    f.close()
            time.sleep(0.5)

    def __exit__(self, *e):
        if self.f:
            fcntl.flock(self.f, fcntl.LOCK_UN)
            self.f.close()


def memo_run(kind, parts, cmd, outs=(), sidecars_of=(), what='', cwd=None, capture=True):
    """Run cmd (list) or restore its stored result. parts = key parts (must name EVERY input by content).
    outs: output paths stored/restored; sidecars_of: output paths whose <path>.* files written by the run are stored too.
    Returns (rc, stdout, stderr)."""
    m = mode()
    k = make_key(kind, parts)
    with _Lock(k):
        old = _load(k) if m != '0' else None
        if old is not None and m == '1':
            _restore(old, [(n, (outs[i] if kd == 'o' else sidecars_of[i] + suf)) for n, kd, i, suf in old['outs']
                           if i < (len(outs) if kd == 'o' else len(sidecars_of))])
            _stat(kind, True)
            return old['rc'], old.get('stdout', ''), old.get('stderr', '')
        t0 = time.time()
        pre = {}
        for o in sidecars_of:
            dn, bn = os.path.split(os.path.abspath(o))
            if os.path.isdir(dn):
                for f in os.listdir(dn):
                    if f.startswith(bn + '.'):
                        try:
                            pre[os.path.join(dn, f)] = os.path.getmtime(os.path.join(dn, f))
                        except OSError:
                            pass
        with _Budget():
            if capture:
                p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, cwd=cwd)
                rc, so, se = p.returncode, p.stdout, p.stderr
            else:
                rc, so, se = subprocess.run(cmd, cwd=cwd).returncode, '', ''
        _stat(kind, False)
        files, omap = {}, []
        for i, o in enumerate(outs):
            if os.path.isfile(o):
                files['o%d' % i] = o
                omap.append(('o%d' % i, 'o', i, ''))
        for i, o in enumerate(sidecars_of):
            dn, bn = os.path.split(os.path.abspath(o))
            if os.path.isdir(dn):
                for f in sorted(os.listdir(dn)):
                    pth = os.path.join(dn, f)
                    if f.startswith(bn + '.') and '.lc' not in f[len(bn):] and os.path.isfile(pth) and \
                            (pth not in pre or os.path.getmtime(pth) != pre[pth]) and os.path.getmtime(pth) >= t0 - 1:
                        n = 's%d%s' % (i, f[len(bn):])
                        files[n] = pth
                        omap.append((n, 's', i, f[len(bn):]))   # restored next to the call's own output path
        if m == 'verify' and old is not None:
            _verify(k, old, rc, so, se, files)
        elif _clean(rc, se) and m != '0':
            _store(k, dict(rc=rc, stdout=so, stderr=se, outs=omap, what=what or ' '.join(map(str, cmd))[:300],
                           secs=round(time.time() - t0, 3)), files)
        return rc, so, se


def memo_call(kind, parts, fn, what=''):
    """Run fn() in this process with stdout/stderr captured, or replay its stored output. fn returns the exit code
    (SystemExit is caught). Returns the exit code; the output is written to the real stdout/stderr."""
    m = mode()
    k = make_key(kind, parts)
    with _Lock(k):
        old = _load(k) if m != '0' else None
        if old is not None and m == '1':
            sys.stdout.write(old.get('stdout', ''))
            sys.stderr.write(old.get('stderr', ''))
            sys.stdout.flush()
            _stat(kind, True)
            return old['rc']
        t0 = time.time()
        so, se = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(so), contextlib.redirect_stderr(se):
                try:
                    rc = fn()
                except SystemExit as e:
                    rc = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
                    if not isinstance(e.code, (int, type(None))):
                        se.write(str(e.code) + chr(10))
        except BaseException:
            sys.stdout.write(so.getvalue())
            sys.stderr.write(se.getvalue())
            raise
        rc = 0 if rc is None else rc
        _stat(kind, False)
        sys.stdout.write(so.getvalue())
        sys.stderr.write(se.getvalue())
        sys.stdout.flush()
        if m == 'verify' and old is not None:
            _verify(k, old, rc, so.getvalue(), se.getvalue(), {})
        elif _clean(rc, se.getvalue()) and m != '0':
            _store(k, dict(rc=rc, stdout=so.getvalue(), stderr=se.getvalue(), outs=[], what=what, secs=round(time.time() - t0, 3)), {})
        return rc


def replay(adapter_cmd, rec, out, args, cwd=None):
    """adapter run `<adapter...> <rec> <out> [args]` through the cache. adapter_cmd: list (binary first)."""
    exe = adapter_cmd[0]
    if not os.path.isabs(exe) and os.sep not in exe:
        exe = shutil.which(exe) or exe
    rec_p = rec if (cwd is None or os.path.isabs(rec)) else os.path.join(cwd, rec)
    parts = [fhash(exe), argkey(adapter_cmd[1:]), fhash(rec_p), argkey(args)]
    return memo_run('replay', parts, list(adapter_cmd) + [rec, out] + list(args), outs=[out], sidecars_of=[out],
                    what='replay %s %s %s' % (os.path.basename(exe), os.path.basename(rec), ' '.join(map(str, args))), cwd=cwd)


def run_cmd(cmd, outs, kind='cmd', cwd=None, what=''):
    """any deterministic command whose inputs are all on its command line (files hashed by content) and whose
    outputs are `outs` (+ their <out>.* sidecars), e.g. the drive adapter `<adapter> <body> <frames> <out> [args]`."""
    cmd = [str(x) for x in cmd]
    exe = cmd[0] if os.sep in cmd[0] else (shutil.which(cmd[0]) or cmd[0])
    old = os.getcwd()
    try:
        if cwd:
            os.chdir(cwd)
        parts = [fhash(exe) if os.path.isfile(exe) else exe, argkey([x for x in cmd[1:] if x not in outs])]
    finally:
        os.chdir(old)
    return memo_run(kind, parts, cmd, outs=list(outs), sidecars_of=list(outs), cwd=cwd, what=what or ' '.join(cmd)[:300])


def check_key(argv):
    """key parts of a pure `animlab.py <check> ...` call (lab code + args with file contents + sidecars + env)."""
    return [code_hash(), argkey(argv, sidecars=True, lists=True), env_part()]


def stats():
    es = entries()
    print('labcache: %s, %d entries, %.0f MB (cap %.0f MB), mode %s' % (DIR, len(es), sum(e[1] for e in es) / (1 << 20), MAX_MB, mode()))
    p = os.path.join(DIR, 'stats.tsv')
    if os.path.isfile(p):
        tot = {}
        for line in open(p).readlines()[-5000:]:
            for kv in line.split('\t', 1)[1].split():
                k, n = kv.split('=')
                tot[k] = tot.get(k, 0) + int(n)
        print('  last 5000 processes: ' + ' '.join('%s=%d' % kv for kv in sorted(tot.items())))
    mm = os.path.join(DIR, 'verify-mismatch.log')
    if os.path.isfile(mm):
        print('  verify mismatches logged: %d (%s)' % (sum(1 for _ in open(mm)), mm))


def main(argv):
    if not argv or argv[0] in ('-h', '--help'):
        print(__doc__)
        return 0
    c = argv[0]
    if c == 'replay':
        if len(argv) < 4:
            raise SystemExit('usage: labcache.py replay <adapter> <rec> <out> [args]')
        rc, so, se = replay([argv[1]], argv[2], argv[3], argv[4:])
        sys.stdout.write(so)
        sys.stderr.write(se)
        return rc
    if c == 'run':
        ins, outs, tag, i, nocmd = [], [], '', 1, False
        while i < len(argv) and argv[i] != '--':
            if argv[i] == '--nocmd':   # the key is --in + --tag only (the command line holds paths that differ per caller)
                nocmd = True
                i += 1
                continue
            if argv[i] == '--in':
                ins += [x for x in argv[i + 1].split(',') if x]
            elif argv[i] == '--out':
                outs += [x for x in argv[i + 1].split(',') if x]
            elif argv[i] == '--tag':
                tag = argv[i + 1]
            i += 2
        cmd = argv[i + 1:]
        missing = [x for x in ins if not os.path.isfile(x)]
        if missing or not cmd:
            raise SystemExit('labcache.py run: missing inputs %s or command' % missing)
        parts = [tag, [fhash(x) for x in ins], [] if nocmd else argkey(cmd), env_part()]
        rc, so, se = memo_run('run', parts, cmd, outs=outs, sidecars_of=outs)
        sys.stdout.write(so)
        sys.stderr.write(se)
        return rc
    if c == 'stats':
        stats()
        return 0
    if c == 'prune':
        prune()
        return 0
    if c == 'clear':
        shutil.rmtree(os.path.join(DIR, 'e'), ignore_errors=True)
        for f in ('size',):
            try:
                os.remove(os.path.join(DIR, f))
            except OSError:
                pass
        print('labcache: cleared ' + DIR)
        return 0
    if c == 'key':
        print(fhash(argv[1]))
        return 0
    raise SystemExit('labcache.py: unknown command ' + c)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
