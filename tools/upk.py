"""Wrapper: the package reader is sdk_mods/classic_minimap/upk.py (PLAN_V13 decision 16).

Usage: python -I tools/upk.py <package> [regex]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mod_source  # noqa: E402

_module = mod_source.load('upk')
if __name__ == '__main__':
    _module.main()
