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
        try:
            from web.ui_inject import serve_index
        except ImportError:
            from ui_inject import serve_index
        return serve_index(os.path.dirname(__file__))

