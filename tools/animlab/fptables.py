#!/usr/bin/env python3
"""fptables.py -- KenshiFP live animation tables files (fp_tables.txt; game: harness `fp_tables`, kfp_tables.inc).

One format for the game, the lab and the sweep driver (KenshiFP kfp_tables.inc header):
    # comment
    <table> = v0 v1 ...          floats from element 0 (row-major)
    <table>.<key> = v0 v1 ...    from element <key>: <flat index> | <row> | <row>.<col> (names as in `fp_tables dump`)
    vm.<key> = v                 any `fp_vm set` key
A file is a whole variant: loading it resets every registered table to the compiled values first.
The hash (hash=<8 hex>) is computed by the game / the lab adapter (`kfpvm_tables check <file>`), never here, so the
number a take logs and the number the lab prints come from the same code.

Usage:
  fptables.py make <out> [--base <file>] [<lhs>=<v>[,<v>..]]...   write a variant (base lines, then the edits; an edit
                                                                   replaces a base line with the same lhs)
  fptables.py show <file>                                         the parsed lines (lhs: values)
  fptables.py check <file> [--adapter <kfpvm_tables>]             hash + bad lines via the lab adapter
  fptables.py expand <list> <outdir> [--adapter ..]               sweep list -> one file per variant + <outdir>/variants.tsv
                                                                   (name, file, hash); list lines: <name> [<base file>|-] [<lhs>=<v,..>]...
Adapter default: $KFP_TABLES_ADAPTER or /root/animlab-build/kfpvm_tables (build: components/KenshiFP/animlab/build.sh
--main kfpvm_tables.c --out /root/animlab-build/kfpvm_tables).
"""
import os, re, subprocess, sys

ADAPTER = os.environ.get('KFP_TABLES_ADAPTER', '/root/animlab-build/kfpvm_tables')


def parse(path):
    """[(lhs, [values as str])] in file order; comments/blank lines dropped."""
    out = []
    with open(path) as fh:
        for ln in fh:
            s = ln.split('#', 1)[0].strip() if not ln.lstrip().startswith('#') else ''
            if not s or s.startswith(';') or '=' not in s:
                continue
            lhs, rhs = s.split('=', 1)
            out.append((lhs.strip(), rhs.split()))
    return out


def write(path, lines, header=None):
    with open(path, 'w', newline='\n') as fh:
        if header:
            for h in header.splitlines():
                fh.write('# ' + h + '\n')
        for lhs, vals in lines:
            fh.write(f"{lhs} = {' '.join(str(v) for v in vals)}\n")


def edit(lines, edits):
    """edits: ['lhs=v1,v2', ...] -> lines with same-lhs lines replaced, new ones appended."""
    d = list(lines)
    for e in edits:
        if '=' not in e:
            raise SystemExit(f'fptables: bad edit {e!r} (want lhs=v[,v..])')
        lhs, rhs = e.split('=', 1)
        vals = [v for v in re.split(r'[,\s]+', rhs.strip()) if v]
        for v in vals:
            float(v)
        d = [(l, v) for l, v in d if l != lhs.strip()] + [(lhs.strip(), vals)]
    return d


def check(path, adapter=ADAPTER):
    """-> (hash or None, reply line)"""
    if not os.path.exists(adapter):
        return None, f'no adapter {adapter}'
    r = subprocess.run([adapter, 'check', path], capture_output=True, text=True)
    line = (r.stdout.strip().splitlines() or [r.stderr.strip()])[-1]
    m = re.search(r'hash=([0-9a-f]{8})', line)
    return (m.group(1) if m and r.returncode == 0 else None), line


def main(a):
    if len(a) >= 2 and a[0] == 'make':
        out, rest, base = a[1], a[2:], None
        if rest[:1] == ['--base']:
            base, rest = rest[1], rest[2:]
        lines = edit(parse(base) if base and base != '-' else [], rest)
        write(out, lines, f"variant: base={base or '-'} edits={' '.join(rest)}")
        print(f'wrote {out} lines={len(lines)}')
    elif len(a) == 2 and a[0] == 'show':
        for lhs, v in parse(a[1]):
            print(f"{lhs}: {' '.join(v)}")
    elif len(a) >= 2 and a[0] == 'check':
        ad = a[a.index('--adapter') + 1] if '--adapter' in a else ADAPTER
        h, line = check(a[1], ad)
        print(line)
        return 0 if h else 1
    elif len(a) >= 3 and a[0] == 'expand':
        ad = a[a.index('--adapter') + 1] if '--adapter' in a else ADAPTER
        os.makedirs(a[2], exist_ok=True)
        rows, bad = [], 0
        with open(a[1]) as fh:
            for ln in fh:
                p = ln.split('#', 1)[0].split()
                if not p:
                    continue
                name, rest = p[0], p[1:]
                base = None
                if rest and '=' not in rest[0]:
                    base, rest = rest[0], rest[1:]
                f = os.path.join(a[2], f'{name}.txt')
                write(f, edit(parse(base) if base and base != '-' else [], rest), f'variant {name}: base={base or "-"} edits={" ".join(rest)}')
                h, line = check(f, ad) if os.path.exists(ad) else ('-', 'no lab adapter: hash from the game only')
                if not h:
                    bad += 1
                    print(f'BAD {name}: {line}')
                rows.append((name, f, h or '-'))
        with open(os.path.join(a[2], 'variants.tsv'), 'w') as fh:
            for r in rows:
                fh.write('\t'.join(r) + '\n')
        print(f"expanded {len(rows)} variants -> {os.path.join(a[2], 'variants.tsv')} bad={bad}")
        return 1 if bad else 0
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
