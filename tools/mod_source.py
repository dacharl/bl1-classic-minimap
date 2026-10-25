"""Load a module that lives in sdk_mods/classic_minimap/ under its plain name (PLAN_V13 decision 16).

The builder moved into the mod so the in-game build and the offline tools run one copy of the code; the
tools/ files of the same names are wrappers around load().
"""
import importlib.util
import os
import sys

MOD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'sdk_mods', 'classic_minimap')


def load(name):
    """Import MOD_DIR/<name>.py as top-level module <name>, replacing a wrapper being imported under it."""
    if MOD_DIR not in sys.path:
        sys.path.insert(0, MOD_DIR)
    spec = importlib.util.spec_from_file_location(name, os.path.join(MOD_DIR, name + '.py'))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module
