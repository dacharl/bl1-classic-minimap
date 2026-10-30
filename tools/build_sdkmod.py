"""Package an sdk_mods/<name> folder as <name>.sdkmod (a zip with <name>/ as its single top folder).
Usage: python -I tools/build_sdkmod.py sdk_mods/classic_minimap [out_dir]
"""
import sys
import zipfile
from pathlib import Path

SKIP_DIRS = {"__pycache__", ".git"}
SKIP_SUFFIXES = {".pyc", ".pyo"}

def main(src: str, out_dir: str = "dist") -> None:
    src_dir = Path(src).resolve()
    out = Path(out_dir).resolve() / f"{src_dir.name}.sdkmod"
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(src_dir.rglob("*")):
            if f.is_dir() or SKIP_DIRS & set(f.parts) or f.suffix in SKIP_SUFFIXES:
                continue
            # posix separators: mods_base looks entries up with "/" first
            zf.write(f, f"{src_dir.name}/{f.relative_to(src_dir).as_posix()}")
    print(out)

if __name__ == "__main__":
    main(*sys.argv[1:])
