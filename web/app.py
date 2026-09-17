@app.route('/')
def index():
    import importlib.util
    _p = os.path.join(os.path.dirname(__file__), 'ui_inject.py')
    _spec = importlib.util.spec_from_file_location('ui_inject', _p)
    _mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    return _mod.serve_index(os.path.dirname(__file__))
