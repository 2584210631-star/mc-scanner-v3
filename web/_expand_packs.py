# -*- coding: utf-8 -*-
"""One-shot: expand packed web route modules next to this file."""
import os, zlib, base64, json

_DIR = os.path.dirname(os.path.abspath(__file__))

def expand():
    packs = []
    i = 0
    while True:
        p = os.path.join(_DIR, f"_pack{i}.json")
        if not os.path.isfile(p):
            break
        with open(p, "r", encoding="utf-8") as f:
            packs.append(json.load(f))
        i += 1
    if not packs:
        return False
    for pack in packs:
        for name, b64 in pack.items():
            path = os.path.join(_DIR, name)
            data = zlib.decompress(base64.b64decode(b64))
            with open(path, "wb") as f:
                f.write(data)
            print("wrote", name, len(data))
    return True

if __name__ == "__main__":
    expand()
