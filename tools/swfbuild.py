"""Wrapper: the builder is sdk_mods/classic_minimap/swfbuild.py (PLAN_V13 decision 16).

Usage: python -I tools/swfbuild.py <HUD.gfx> <status_menu.gfx> <out.gfx> [<HUD_enhanced.gfx>]
Without the Enhanced HUD movie the build uses the original art.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mod_source  # noqa: E402

_module = mod_source.load('swfbuild')
if __name__ == '__main__':
    _module.main()
