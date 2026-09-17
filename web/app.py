# -*- coding: utf-8 -*-
"""Bootstrap: materialize full Flask app once from known-good commit, then exec."""
import os
import urllib.request

_DIR = os.path.dirname(os.path.abspath(__file__))
_FULL = os.path.join(_DIR, "_app_full.py")
_GOOD_URL = (
    "https://raw.githubusercontent.com/2584210631-star/mc-scanner-v3/"
    "1203edda6e31b1a43725e09a484974d88044d517/web/app.py"
)


def _patch(data: str) -> str:
    # 1) index() -> ui_inject
    old_index = (
        "@app.route('/')\n"
        "def index():\n"
        "    return send_from_directory(os.path.dirname(__file__), 'index.html')\n"
    )
    new_index = (
        "@app.route('/')\n"
        "def index():\n"
        "    import importlib.util\n"
        "    _p = os.path.join(os.path.dirname(__file__), 'ui_inject.py')\n"
        "    _spec = importlib.util.spec_from_file_location('ui_inject', _p)\n"
        "    _mod = importlib.util.module_from_spec(_spec)\n"
        "    _spec.loader.exec_module(_mod)\n"
        "    return _mod.serve_index(os.path.dirname(__file__))\n"
    )
    if old_index in data:
        data = data.replace(old_index, new_index)

    # 2) personas API -> core.ai_personas + preview
    old_api = (
        "@app.route('/api/ai_multi/personas')\n"
        "def ai_multi_personas():\n"
        "    from core.ai_bot import PRESET_PERSONAS\n"
        "    return jsonify({\"personas\": [{\"name\": p[\"name\"], \"label\": p.get(\"label\", p[\"name\"]), \"persona\": p[\"persona\"]} for p in PRESET_PERSONAS]})\n"
    )
    new_api = (
        "@app.route('/api/ai_multi/personas')\n"
        "def ai_multi_personas():\n"
        "    try:\n"
        "        from core.ai_personas import PRESET_PERSONAS\n"
        "    except Exception:\n"
        "        from core.ai_bot import PRESET_PERSONAS\n"
        "    out = []\n"
        "    for p in PRESET_PERSONAS:\n"
        "        persona = p.get(\"persona\") or \"\"\n"
        "        out.append({\n"
        "            \"name\": p.get(\"name\", \"\"),\n"
        "            \"label\": p.get(\"label\", p.get(\"name\", \"\")),\n"
        "            \"persona\": persona,\n"
        "            \"preview\": persona[:60].replace(\"\\n\", \" \"),\n"
        "        })\n"
        "    return jsonify({\"personas\": out})\n"
    )
    if old_api in data:
        data = data.replace(old_api, new_api)
    return data


def _ensure_full() -> str:
    if os.path.isfile(_FULL) and os.path.getsize(_FULL) > 50000:
        # re-patch in case older cache without personas API fix
        try:
            with open(_FULL, "r", encoding="utf-8") as f:
                cached = f.read()
            patched = _patch(cached)
            if patched != cached:
                with open(_FULL, "w", encoding="utf-8") as f:
                    f.write(patched)
        except OSError:
            pass
        return _FULL
    try:
        with urllib.request.urlopen(_GOOD_URL, timeout=45) as resp:
            data = resp.read().decode("utf-8")
    except Exception as e:
        raise RuntimeError(
            "web/app.py bootstrap download failed. Offline fix:\n"
            "  git show 1203edda6e31b1a43725e09a484974d88044d517:web/app.py > web/app.py\n"
            f"Original error: {e}"
        ) from e
    data = _patch(data)
    with open(_FULL, "w", encoding="utf-8") as f:
        f.write(data)
    return _FULL


_path = _ensure_full()
with open(_path, "r", encoding="utf-8") as f:
    _code = compile(f.read(), _path, "exec")
exec(_code, globals())
