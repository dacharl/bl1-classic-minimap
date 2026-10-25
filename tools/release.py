"""Build and test a local minimap release; never installs or publishes game assets.

Use --inputs <checkout>/dist/phase2 and --stock-package <checkout>/dist/phase1/GfxHUD.orig.upk
to reuse local extracted inputs from another worktree. The output directory must not exist.
"""
import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
import tomllib
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
from bump_version import bump, version  # noqa: E402
from quality_checks import declared_version  # noqa: E402
from upk import Pkg  # noqa: E402
from upkpatch import extract, guid_offset, replace  # noqa: E402


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def validate_package(stock, package, movie):
    """Reconstruct relocation from stock; every non-GUID byte must match.

    Unlike searching only for already-correct self references, this also detects missing or damaged
    bulk offsets by comparing all preserved export bytes with the independently supplied stock.
    """
    original = Pkg(str(stock))
    if extract(original, 'FlashMovie.HUD')[:3] not in (b'GFX', b'FWS'):
        raise ValueError('stock package does not contain an uncompressed HUD movie')
    data = Path(package).read_bytes()
    expected = replace(original, 'FlashMovie.HUD', Path(movie).read_bytes())
    offset = guid_offset(expected)
    if data[offset:offset + 16] == expected[offset:offset + 16]:
        raise ValueError('release package must have a fresh GUID')
    if data[:offset] + data[offset + 16:] != expected[:offset] + expected[offset + 16:]:
        raise ValueError('package movie, exports or bulk-data relocation differs from stock reconstruction')


def run(script, *args):
    subprocess.run([sys.executable, '-B', '-I', str(HERE / script), *map(str, args)], cwd=ROOT, check=True)


def release(args):
    inputs, stock, output = args.inputs.resolve(), args.stock_package.resolve(), args.output.resolve()
    paths = [inputs / n for n in ('HUD_classic.gfx', 'status_menu.gfx', 'HUD_enhanced.gfx')]
    if output.exists():
        raise ValueError(f'output already exists: {output}; choose a new release directory')
    for path in [stock, *paths]:
        if not path.is_file():
            raise ValueError(f'missing build input: {path}')
    if extract(Pkg(str(stock)), 'FlashMovie.HUD') != paths[0].read_bytes():
        raise ValueError('classic movie input does not match the original package')
    if bool(args.version) != bool(args.profiler_version):
        raise ValueError('--version and --profiler-version must be supplied together')
    if args.dry_run:
        if args.version:
            bump(ROOT, args.version, args.profiler_version, dry_run=True)
        print(f'Would build movie from {inputs}, run both suites, repack {stock} with --new-guid,')
        print('build core' + (' and profiler' if args.profiler else '') + f', and write manifest in {output}')
        return
    if args.version:
        bump(ROOT, args.version, args.profiler_version)
    versions = {}
    for name in ('classic_minimap', 'classic_minimap_profiler'):
        folder = ROOT / 'sdk_mods' / name
        current = tomllib.loads((folder / 'pyproject.toml').read_text(encoding='utf-8'))['project']['version']
        if declared_version(folder) != [current]:
            raise ValueError(f'{name}: version fields differ; run bump_version.py')
        versions[name] = current
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.release-', dir=output.parent) as directory:
        stage = Path(directory) / 'bundle'
        stage.mkdir()
        movie = stage / 'HUD_minimap.gfx'
        run('swfbuild.py', paths[0], paths[1], movie, paths[2])
        run('test_minimap_as.py', movie)
        run('test_minimap_mod.py', movie)
        package = stage / 'GfxHUD_Minimap.upk'
        run('upkpatch.py', 'replace', stock, 'FlashMovie.HUD', movie, package, '--new-guid')
        validate_package(stock, package, movie)
        run('build_sdkmod.py', ROOT / 'sdk_mods/classic_minimap', stage)
        if args.profiler:
            run('build_sdkmod.py', ROOT / 'sdk_mods/classic_minimap_profiler', stage)
        manifest = dict(schema_version=1, core_version=versions['classic_minimap'],
                        profiler_version=versions['classic_minimap_profiler'] if args.profiler else None,
                        created_utc=datetime.now(timezone.utc).isoformat(), stock_sha256=sha256(stock),
                        inputs={p.name: sha256(p) for p in paths},
                        files={p.name: sha256(p) for p in sorted(stage.iterdir())})
        (stage / 'release.json').write_bytes((json.dumps(manifest, indent=2) + '\n').encode('utf-8'))
        # Rename only the complete bundle. A failed build never leaves a valid-looking release.
        if output.exists():
            raise ValueError(f'output appeared during build: {output}')
        stage.rename(output)
    print(f'Release ready: {output}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inputs', type=Path, default=ROOT / 'dist/phase2')
    parser.add_argument('--stock-package', type=Path, default=ROOT / 'dist/phase1/GfxHUD.orig.upk')
    parser.add_argument('--output', type=Path, default=ROOT / 'dist/release')
    parser.add_argument('--version', type=version, help='explicit core bump before building')
    parser.add_argument('--profiler-version', type=version, help='paired profiler bump')
    parser.add_argument('--profiler', action='store_true', help='also build the optional add-on')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    try:
        release(args)
    except (OSError, ValueError, AssertionError, subprocess.CalledProcessError) as error:
        parser.exit(1, f'release failed: {error}\n')


if __name__ == '__main__':
    main()
