"""Wrapper: the AS2 assembler is sdk_mods/classic_minimap/as2asm.py (PLAN_V13 decision 16)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mod_source  # noqa: E402

mod_source.load('as2asm')
