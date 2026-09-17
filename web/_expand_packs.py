# -*- coding: utf-8 -*-
import os, zlib, base64, json
_DIR = os.path.dirname(os.path.abspath(__file__))
def expand(force=False):
    i = wrote = 0
    while True:
        p = os.path.join(_DIR, f"_pack{i}.json")
        if not os.path.isfile(p):
            break
        with open(p, "r", encoding="utf-8") as f:
            pack = json.load(f)
        for name, b64 in pack.items():
            path = os.path.join(_DIR, name)
            data = zlib.decompress(base64.b64decode(b64))
            if force or (not os.path.isfile(path)) or os.path.getsize(path) < len(data) // 2:
                with open(path, "wb") as out:
                    out.write(data)
                wrote += 1
        i += 1
    return wrote
if __name__ == "__main__":
    print("wrote", expand(force=True), "files")
