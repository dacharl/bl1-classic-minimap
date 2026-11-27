"""Write a release's notes and its changes supplement for the release workflow.

The body is the hand-written notes (docs/release_notes/<version>.md, or the workflow's `notes` input when
that file is missing) followed by the install text. The supplement lists the commits since the previous
release tag, grouped by Conventional Commit type. A release with no notes at all fails here, before CI runs.

Usage: python -I tools/release_notes.py --version 1.0.0 [--notes TEXT] [--out-dir dist] [--notes-dir DIR]
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

NOTES_DIR = 'docs/release_notes'
BODY_NAME = 'release-notes.md'
CHANGES_NAME = 'classic_minimap-changes.md'

INSTALL_TEXT = (
    'Copy `classic_minimap.sdkmod` into your Borderlands `sdk_mods` folder. That is the whole install.\n\n'
    'Requires the willow1 PythonSDK and Borderlands GOTY (classic); GOTY Enhanced is optional. '
    'On first enable the mod builds its HUD movie from your own game files (a few seconds, once); '
    'no game files are included in this release. See `README.md` at the release tag.\n')

SECTIONS = (('feat', 'Features'), ('fix', 'Fixes'), ('perf', 'Performance'), ('refactor', 'Refactoring'),
            ('docs', 'Documentation'), ('test', 'Tests'), ('build', 'Build and CI'), ('ci', 'Build and CI'),
            ('chore', 'Chores'))
SUBJECT = re.compile(r'(\w+)(?:\([^)]*\))?(!)?: (.+)')
SEMVER_TAG = re.compile(r'v(\d+)\.(\d+)\.(\d+)')


class ReleaseNotesError(Exception):
    """A problem the release run should report as one line and a failing exit code."""


def resolve_notes(version, notes_dir, notes_input):
    """The version's notes file if it has text, else the typed input, else stop with how to supply them."""
    path = Path(notes_dir) / f'{version}.md'
    if path.is_file() and path.read_text(encoding='utf-8').strip():
        return path.read_text(encoding='utf-8').strip() + '\n'
    if notes_input and notes_input.strip():
        return notes_input.strip() + '\n'
    raise ReleaseNotesError(f'No release notes for {version}. Add {NOTES_DIR}/{version}.md to main, '
                     f"or run the workflow with the 'notes' input filled in.")


def version_key(tag):
    match = SEMVER_TAG.fullmatch(tag)
    return tuple(map(int, match.groups())) if match else None


def previous_tag(tags, version):
    """The highest vMAJOR.MINOR.PATCH tag below `version`, or None."""
    current = version_key(f'v{version}')
    older = [tag for tag in tags if (key := version_key(tag)) and key < current]
    return max(older, key=version_key, default=None)


def changes_text(version, previous, log):
    """Markdown list of `log` lines ("<sha>\\t<subject>") grouped by commit type, newest first within a group."""
    titles = dict(SECTIONS)
    groups = {}
    for line in log:
        sha, subject = line.split('\t', 1)
        match = SUBJECT.fullmatch(subject)
        if match and match[1] in titles:
            title, text = titles[match[1]], ('**breaking:** ' if match[2] else '') + match[3]
        else:
            title, text = 'Other', subject
        groups.setdefault(title, []).append(f'- {text} (`{sha}`)')
    count = f'{len(log)} commit' + ('' if len(log) == 1 else 's')
    since = f'Since {previous}' if previous else 'Since the first commit'
    out = [f'# Changes in v{version}\n', f'{since}: {count}.\n']
    for title in dict.fromkeys([*titles.values(), 'Other']):
        if title in groups:
            out.append(f'## {title}\n\n' + '\n'.join(groups[title]) + '\n')
    return '\n'.join(out)


def git(*args):
    result = subprocess.run(['git', *args], capture_output=True, text=True, encoding='utf-8')
    if result.returncode:
        raise ReleaseNotesError(f'git {" ".join(args)} failed: {result.stderr.strip()}')
    return result.stdout.splitlines()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--version', required=True)
    parser.add_argument('--notes', default=None, help="the workflow's `notes` input, used when no notes file exists")
    parser.add_argument('--out-dir', default='dist')
    parser.add_argument('--notes-dir', default=NOTES_DIR)
    args = parser.parse_args(argv)
    notes = resolve_notes(args.version, args.notes_dir, args.notes)
    previous = previous_tag(git('tag', '--list', 'v*'), args.version)
    log = git('log', '--no-merges', '--format=%h%x09%s', f'{previous}..HEAD' if previous else 'HEAD')
    since = f' since {previous}' if previous else ''
    body = (f'{notes}\n## Install\n\n{INSTALL_TEXT}\n'
            f'`{CHANGES_NAME}` lists every commit{since}.\n')
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / BODY_NAME).write_bytes(body.encode('utf-8'))
    (out / CHANGES_NAME).write_bytes(changes_text(args.version, previous, log).encode('utf-8'))
    print(f'release notes for {args.version}: {len(log)} commits{since}')


def run(argv=None):
    """main() as an exit code: errors print one line to stderr instead of a traceback."""
    try:
        main(argv)
    except ReleaseNotesError as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(run())
