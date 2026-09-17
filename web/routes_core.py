# -*- coding: utf-8 -*-
"""Routes: core"""
from flask import request, jsonify, Response, send_from_directory
import os, sys, json, time, threading
from datetime import datetime
from collections import deque
import config, logger
try:
    from web import state
except ImportError:
    import state  # type: ignore

def register(app):
    scan_state = state.scan_state
    scan_lock = state.scan_lock
    scan_stop_event = state.scan_stop_event
    observer_sessions = state.observer_sessions
    observer_lock = getattr(state, "observer_lock", state.scan_lock)
    health_monitor = state.health_monitor
    _ai_bots = state._ai_bots
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
