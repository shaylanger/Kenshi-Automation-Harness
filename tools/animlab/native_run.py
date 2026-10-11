#!/usr/bin/env python3
"""native_run.py -- Windows-python side of framecache.native_check (gpu-native 2026-10-11): runs one animlab check with
CuPy on the Windows GPU path instead of WSL CUDA (WSL GPU-PV caused the 5090 BSOD/TDRs). Started by framecache.native_call
as `python.exe -P <snapshot>\\native_run.py` with a JSON job on stdin: {"module", "fn", "kw", "env"}; calls the unwrapped
check (no caches here: the WSL caller stores the result) and prints `NATIVE-RESULT {"tuple": bool, "v": result}` last.
Not for direct use; `python native_run.py --selftest` prints the GPU path."""
import inspect, json, os, sys, warnings

warnings.filterwarnings('ignore', message='CUDA path could not be detected')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main():
    if sys.argv[1:] == ['--selftest']:
        import gpu
        cp = gpu.cupy()
        print('native gpu path: %s' % ('cupy %s' % cp.__version__ if cp is not None else 'off (numpy)'))
        return 0
    job = json.loads(sys.stdin.read())
    os.environ.update(job.get('env') or {})
    os.environ['KAH_NATIVE_CHILD'] = '1'
    mod = __import__(job['module'])
    fn = inspect.unwrap(getattr(mod, job['fn']))
    r = fn(**job['kw'])
    sys.stdout.flush()
    print('NATIVE-RESULT ' + json.dumps({'tuple': isinstance(r, tuple), 'v': r}, default=repr))
    return 0


if __name__ == '__main__':
    sys.exit(main())
