# -*- coding: utf-8 -*-
"""Routes: core"""
import os
try:
    from web import state
except ImportError:
    import state  # type: ignore


def register(app):
    def _log(msg):
        state.log_scan(msg)
    def _get_web_token():
        return state.get_web_token()
    def _safe_db_path(path):
        return state.safe_db_path(path)
    def parse_ports_spec(ports_spec):
        return state.parse_ports_spec(ports_spec)


    @app.route('/')
    def index():
        import importlib.util
        _p = os.path.join(os.path.dirname(__file__), 'ui_inject.py')
        _spec = importlib.util.spec_from_file_location('ui_inject', _p)
        _mod = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
        return _mod.serve_index(os.path.dirname(__file__))

