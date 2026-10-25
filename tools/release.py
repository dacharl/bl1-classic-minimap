"""Build and test a local minimap release; never installs or publishes game assets.

Players build the HUD movie themselves from their own game files (PLAN_V13), so the bundle holds only the
.sdkmod files and a manifest. The release still builds both art variants from local extracted inputs
(--inputs <checkout>/dist/phase2), runs both real-movie suites on each and records their hashes. --game
<Borderlands> also runs the mod's own in-game build on that folder's packages and requires the same bytes.
The output directory must not exist.
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


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def run(script, *args):
    subprocess.run([sys.executable, '-B', '-I', str(HERE / script), *map(str, args)], cwd=ROOT, check=True)


def in_mod_build(game, enhanced, movies, core_version):
    """The movie the mod builds in game from these folders (hudmovie), compared with the tested one."""
    import mod_source
    hudmovie = mod_source.load('hudmovie')
    interface = Path(game) / hudmovie.INTERFACE
    enh_package = Path(enhanced) / hudmovie.INTERFACE / hudmovie.HUD_PACKAGE if enhanced else None
    try:
        data, art, notes = hudmovie.build_movie(
            (interface / hudmovie.HUD_PACKAGE).read_bytes(), (interface / hudmovie.MENUS_PACKAGE).read_bytes(),
            enh_package.read_bytes() if enh_package is not None and enh_package.is_file() else None, core_version)
    except hudmovie.BuildFailed as ex:
        raise ValueError(f'the in-mod build from {game} failed: {ex}') from None
    for note in notes:
        print(note)
    if data != movies[art].read_bytes():
        raise ValueError(f'the in-mod build from {game} differs from the tested {art}-art movie')
    print(f'in-mod build matches ({art} art): {hashlib.sha256(data).hexdigest()}')


def release(args):
    inputs, output = args.inputs.resolve(), args.output.resolve()
    paths = [inputs / n for n in ('HUD_classic.gfx', 'status_menu.gfx', 'HUD_enhanced.gfx')]
    if output.exists():
        raise ValueError(f'output already exists: {output}; choose a new release directory')
    for path in paths:
        if not path.is_file():
            raise ValueError(f'missing build input: {path}')
    if bool(args.version) != bool(args.profiler_version):
        raise ValueError('--version and --profiler-version must be supplied together')
    if args.dry_run:
        if args.version:
            bump(ROOT, args.version, args.profiler_version, dry_run=True)
        print(f'Would build both art variants from {inputs}, run both suites on each,'
              + (f' check the in-mod build from {args.game},' if args.game else ''))
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
        work, stage = Path(directory) / 'movies', Path(directory) / 'bundle'
        work.mkdir()
        stage.mkdir()
        # The movies stay outside the bundle: they hold game assets and players build their own.
        movies = {'enhanced': work / 'HUD_minimap.gfx', 'original': work / 'HUD_minimap_original.gfx'}
        run('swfbuild.py', paths[0], paths[1], movies['enhanced'], paths[2])
        run('swfbuild.py', paths[0], paths[1], movies['original'])
        for movie in movies.values():
            run('test_minimap_as.py', movie)
            run('test_minimap_mod.py', movie)
        if args.game:
            in_mod_build(args.game, args.enhanced, movies, versions['classic_minimap'])
        run('build_sdkmod.py', ROOT / 'sdk_mods/classic_minimap', stage)
        if args.profiler:
            run('build_sdkmod.py', ROOT / 'sdk_mods/classic_minimap_profiler', stage)
        manifest = dict(schema_version=2, core_version=versions['classic_minimap'],
                        profiler_version=versions['classic_minimap_profiler'] if args.profiler else None,
                        created_utc=datetime.now(timezone.utc).isoformat(),
                        inputs={p.name: sha256(p) for p in paths},
                        movies={art: sha256(path) for art, path in movies.items()},
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
    parser.add_argument('--game', type=Path, help="classic's game folder: check the mod's in-game build against it")
    parser.add_argument('--enhanced', type=Path, help="with --game: Enhanced's game folder (default: none)")
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
