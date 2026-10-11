#!/usr/bin/env python3
"""gpu.py -- optional CUDA path for per-frame image checks (Shay 2026-10-10: cut the 5090's CPU load; the frame checks
were single-core numpy at ~20 s per take each). Uses CuPy when it imports and sees a GPU (WSL: pip cupy-cuda12x +
nvidia-cuda-nvrtc-cu12 / nvidia-curand-cu12 / nvidia-cuda-runtime-cu12), else numpy: same code, same verdicts.
Work runs on a lowest-priority CUDA stream so Kenshi's rendering during takes keeps the GPU first.
  xp_of(a)    numpy or cupy module for array a (write array code as `np = gpu.xp_of(a)`)
  dev(a)      a on the GPU when the GPU path is on, else a unchanged
  host(a)     a as a numpy array (no-op for numpy)
ANIMLAB_GPU=0 forces the CPU path.  CLI: gpu.py  (prints which path is active)
"""
import os, sys

_cp = False   # False = not probed yet, None = unavailable
_stream = None


def cupy():
    global _cp, _stream
    if _cp is False:
        _cp = None
        if os.environ.get('ANIMLAB_GPU', '1') != '0':
            try:
                import cupy as cp
                if cp.cuda.runtime.getDeviceCount() > 0:
                    # CUDA stream priority: 0 = least (numbers below 0 are higher); our work never preempts others
                    _stream = cp.cuda.Stream(non_blocking=True, priority=0)
                    _stream.use()
                    (cp.arange(4) > 1).sum().get()   # JIT/driver smoke test: any failure -> CPU path
                    _cp = cp
            except Exception:
                _cp = None
    return _cp


def xp_of(a):
    cp = cupy()
    if cp is not None and isinstance(a, cp.ndarray):
        return cp
    import numpy
    return numpy


def dev(a):
    cp = cupy()
    return cp.asarray(a) if cp is not None else a


def host(a):
    cp = cupy()
    if cp is not None and isinstance(a, cp.ndarray):
        return cp.asnumpy(a)
    return a


if __name__ == '__main__':
    cp = cupy()
    print('gpu path: %s' % ('cupy %s on %s' % (cp.__version__, cp.cuda.runtime.getDeviceProperties(0)['name'].decode())
                            if cp is not None else 'off (numpy)'))
    sys.exit(0)
