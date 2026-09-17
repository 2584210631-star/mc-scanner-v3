# -*- coding: utf-8 -*-
"""Bootstrap: assemble app from chunks if full module missing (recovery)."""
import os
import sys

_DIR = os.path.dirname(os.path.abspath(__file__))
_FULL = os.path.join(_DIR, '_app_full.py')

def _ensure_full():
    if os.path.isfile(_FULL) and os.path.getsize(_FULL) > 10000:
        return _FULL
    parts = []
    i = 0
    while True:
        p = os.path.join(_DIR, f'app_chunk_{i:02d}.txt')
        if not os.path.isfile(p):
            break
        with open(p, 'r', encoding='utf-8') as f:
            parts.append(f.read())
        i += 1
    if not parts:
        raise RuntimeError('web/app.py chunks missing; restore web/app.py from git history')
    data = ''.join(parts)
    with open(_FULL, 'w', encoding='utf-8') as f:
        f.write(data)
    return _FULL

_path = _ensure_full()
with open(_path, 'r', encoding='utf-8') as f:
    _code = compile(f.read(), _path, 'exec')
exec(_code, globals())
