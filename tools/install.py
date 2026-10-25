"""Install a validated local release with dated backups and SHA-256 verification.

The game must be closed. --dry-run validates and prints the plan without writing anything.
The optional profiler add-on is copied only with --profiler. Only .sdkmod files are installed: the mod builds
its HUD movie from the game's own files (PLAN_V13), so no game file is modified, and an old
GfxHUD_Minimap.upk is pointed out, not deleted.
"""
import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
import zipfile
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
from release import sha256  # noqa: E402

GAME = Path('C:/Program Files (x86)/Steam/steamapps/common/Borderlands')
INTERFACE = Path('WillowGame/CookedPC/Packages/Interface')
OLD_PACKAGE = INTERFACE / 'GfxHUD_Minimap.upk'
DESTINATIONS = {'classic_minimap.sdkmod': Path('sdk_mods/classic_minimap.sdkmod'),
                'classic_minimap_profiler.sdkmod': Path('sdk_mods/classic_minimap_profiler.sdkmod')}


def require_closed():
    if sys.platform == 'win32':
        result = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq Borderlands.exe', '/FO', 'CSV', '/NH'],
                                capture_output=True, text=True, errors='replace', check=True)
        running = any(row and row[0].lower() == 'borderlands.exe' for row in csv.reader(result.stdout.splitlines()))
    else:
        result = subprocess.run(['ps', '-A', '-o', 'comm='], capture_output=True, text=True, check=True)
        running = any(Path(line.strip()).name.lower() == 'borderlands.exe' for line in result.stdout.splitlines())
    if running:
        raise ValueError('Borderlands.exe is running; close the game before installing')


def archive_version(path, name):
    with zipfile.ZipFile(path) as archive:
        return tomllib.loads(archive.read(f'{name}/pyproject.toml').decode('utf-8'))['project']['version']


def validated_bundle(bundle, profiler):
    manifest = json.loads((bundle / 'release.json').read_bytes())
    files = manifest.get('files', {})
    required = {'classic_minimap.sdkmod'}
    allowed = required | {'classic_minimap_profiler.sdkmod'}
    if not isinstance(files, dict) or not required <= files.keys() or files.keys() - allowed:
        raise ValueError('release manifest contains missing or unexpected files')
    if manifest.get('schema_version') != 2:
        raise ValueError('unsupported release manifest schema (rebuild the release with release.py)')
    for name, digest in files.items():
        if sha256(bundle / name) != digest:
            raise ValueError(f'SHA-256 mismatch: {name}')
    if archive_version(bundle / 'classic_minimap.sdkmod', 'classic_minimap') != manifest.get('core_version'):
        raise ValueError('core archive version differs from manifest')
    if profiler:
        if 'classic_minimap_profiler.sdkmod' not in files:
            raise ValueError('release does not include the profiler; rebuild with --profiler')
        if archive_version(bundle / 'classic_minimap_profiler.sdkmod', 'classic_minimap_profiler') != manifest.get('profiler_version'):
            raise ValueError('profiler archive version differs from manifest')
    return manifest


def install(args):
    bundle, game = args.release.resolve(), args.game.resolve()
    manifest = validated_bundle(bundle, args.profiler)
    selected = {name: game / relative for name, relative in DESTINATIONS.items()
                if args.profiler or name != 'classic_minimap_profiler.sdkmod'}
    for target in selected.values():
        if target.resolve() != target or not target.parent.is_dir():
            raise ValueError(f'unsafe linked target or missing installation directory: {target}')
        if target.is_dir():
            raise ValueError(f'install target is a directory: {target}')
    backups = args.backups.resolve()
    if backups.is_relative_to(game) or backups.is_relative_to(bundle):
        raise ValueError('backups must be outside the game and release directories')
    require_closed()
    for name, target in selected.items():
        print(f'{"Would install" if args.dry_run else "Install"}: {name} -> {target}')
    if args.dry_run:
        print('Dry run: no files changed')
        return
    old_version = 'uninstalled'
    old_core = game / DESTINATIONS['classic_minimap.sdkmod']
    if old_core.exists():
        try:
            old_version = str(archive_version(old_core, 'classic_minimap'))
        except (OSError, KeyError, ValueError, zipfile.BadZipFile):
            old_version = 'unknown'
    # Version strings are untrusted archive contents, never path components verbatim.
    import re
    safe_version = re.sub(r'[^A-Za-z0-9._-]', '_', old_version)[:48]
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    backup = backups / f'v{safe_version}-{stamp}'
    backup.mkdir(parents=True, exist_ok=False)
    saved = {}
    for name, target in selected.items():
        if target.exists():
            shutil.copy2(target, backup / name)
            digest = sha256(target)
            if sha256(backup / name) != digest:
                raise ValueError(f'backup verification failed: {name}')
            saved[name] = digest
        else:
            saved[name] = None
    record = dict(replaced_core_version=old_version, release=str(bundle), created_utc=stamp,
                  previous_sha256=saved, installed_sha256={name: manifest['files'][name] for name in selected},
                  status='backed_up')
    record_path = backup / 'install.json'
    record_path.write_bytes((json.dumps(record, indent=2) + '\n').encode('utf-8'))
    staged = {}
    changed = []
    try:
        for name, target in selected.items():
            fd, temporary = tempfile.mkstemp(prefix='.minimap-', suffix='.tmp', dir=target.parent)
            os.close(fd)
            staged[name] = Path(temporary)
            shutil.copy2(bundle / name, temporary)
            if sha256(temporary) != manifest['files'][name]:
                raise ValueError(f'staged SHA-256 mismatch: {name}')
        require_closed()  # check again after validation and backup
        for name, target in selected.items():
            os.replace(staged[name], target)
            changed.append(name)
            if sha256(target) != manifest['files'][name]:
                raise ValueError(f'installed SHA-256 mismatch: {name}')
        record['status'] = 'installed'
    except BaseException:
        for name in reversed(changed):
            if saved[name] is None:
                selected[name].unlink(missing_ok=True)
            else:
                shutil.copy2(backup / name, selected[name])
                if sha256(selected[name]) != saved[name]:
                    raise ValueError(f'rollback verification failed: restore {backup / name} manually')
        record['status'] = 'rolled_back'
        raise
    finally:
        for temporary in staged.values():
            temporary.unlink(missing_ok=True)
        record_path.write_bytes((json.dumps(record, indent=2) + '\n').encode('utf-8'))
    print(f'Backup: {backup}')
    if (game / OLD_PACKAGE).exists():
        print(f'GfxHUD_Minimap.upk is no longer used (the mod builds its HUD movie itself); '
              f'delete {game / OLD_PACKAGE} when you like.')
    print('\nPROGRESS rows (SHA-256 verified):\n')
    print('| File | Version / SHA-256 |\n|---|---|')
    for name, target in selected.items():
        current = manifest['profiler_version'] if name == 'classic_minimap_profiler.sdkmod' else manifest['core_version']
        print(f'| `{target.relative_to(game).as_posix()}` | {current} / `{sha256(target)}` |')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('release', type=Path, help='directory produced by release.py')
    parser.add_argument('--game', type=Path, default=GAME)
    parser.add_argument('--backups', type=Path, default=ROOT / 'dist')
    parser.add_argument('--profiler', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)
    try:
        install(args)
    except (OSError, ValueError, KeyError, AssertionError, zipfile.BadZipFile, subprocess.CalledProcessError) as error:
        parser.exit(1, f'install failed: {error}\n')


if __name__ == '__main__':
    main()
