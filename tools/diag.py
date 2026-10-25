"""Summarize a Windows or copied Proton unrealsdk.log without executing its contents."""
import argparse
import ast
import collections
import json
import re
import sys
from pathlib import Path

GAME = Path('C:/Program Files (x86)/Steam/steamapps/common/Borderlands')
DEFAULT_LOG = GAME / 'Binaries/Plugins/unrealsdk.log'
MARKER = '[Classic Minimap] '


class NonfiniteReads(ast.NodeTransformer):
    """GFx's missing numeric paths print as inf/nan; represent them as JSON null."""
    def visit_Name(self, node):
        return ast.copy_location(ast.Constant(None), node) if node.id in ('inf', 'nan') else node

    def visit_UnaryOp(self, node):
        if isinstance(node.op, (ast.USub, ast.UAdd)) and isinstance(node.operand, ast.Name) and node.operand.id in ('inf', 'nan'):
            return ast.copy_location(ast.Constant(None), node)
        return self.generic_visit(node)


def movie_name(value):
    match = re.search(r'(?:GFxMovieInfo\x27)?([\w]+)\.FlashMovie\.HUD', str(value))
    return match[1] if match else None


def diagnose(log, last, settings=None):
    snapshots = collections.deque(maxlen=last)
    warnings, events, errors = [], [], []
    foreign = set()
    latest = None
    with log.open(encoding='utf-8-sig', errors='replace') as stream:
        for number, line in enumerate(stream, 1):
            if MARKER not in line:
                continue
            prefix, message = line.rstrip().split(MARKER, 1)
            timestamp = re.match(r'\d{4}-\d\d-\d\d[ T]\d\d:\d\d:\d\d(?:\.\d+)?Z?', prefix)
            entry = {'line': number, 'timestamp': timestamp[0] if timestamp else None, 'message': message}
            if message.startswith('diagnostics: '):
                try:
                    text = message[len('diagnostics: '):]
                    if len(text) > 256 * 1024:
                        raise ValueError('snapshot exceeds 256 KiB')
                    state = ast.literal_eval(NonfiniteReads().visit(ast.parse(text, mode='eval')))
                    if not isinstance(state, dict):
                        raise ValueError('snapshot is not a dictionary')
                    state = json.loads(json.dumps(state, allow_nan=False))
                    latest = state
                    snapshots.append({'line': number, 'timestamp': entry['timestamp'], 'state': state})
                    for key in ('hud.MovieInfo', 'template.MovieInfo'):
                        name = movie_name(state.get(key))
                        if name and name not in ('GfxHUD', 'GfxHUD_Minimap'):
                            foreign.add(name)
                except (ValueError, TypeError, SyntaxError, RecursionError) as error:
                    errors.append(f'line {number}: invalid snapshot: {error}')
            else:
                if any(word in message.lower() for word in ('map ready', 'rebuild', 'rebuilding', 'map attached')):
                    events.append(entry)
                # warn_once uses print, so SDK severity alone does not distinguish its warnings.
                if re.search(r'\b(?:WARN|ERROR|CRITICAL)\b', prefix) or any(
                    word in message.lower() for word in ("couldn't", 'failed', 'unavailable', 'not found',
                                                          'waiting', 'current hud uses', 'ignored', 'missing')):
                    warnings.append(entry)
                if 'current HUD uses' in message:
                    name = movie_name(message)
                    if name and name not in ('GfxHUD', 'GfxHUD_Minimap'):
                        foreign.add(name)
    anchors = {'records': 0, 'frames': {}, 'latest': None}
    summary = None
    if settings is not None:
        path = settings / 'classic_minimap_anchors.jsonl'
        frames = collections.Counter()
        if path.exists():
            with path.open(encoding='utf-8-sig', errors='replace') as stream:
                for number, line in enumerate(stream, 1):
                    try:
                        record = json.loads(line)
                        if not isinstance(record, dict):
                            raise ValueError('anchor is not an object')
                        fields = record.get('fields') or {}
                        frame = str(fields.get('MapFrame', record.get('frame', 'unknown')))
                        frames[frame] += 1
                        anchors['records'] += 1
                        anchors['latest'] = {k: record.get(k) for k in
                                             ('t', 'version', 'anchor', 'level', 'frame', 'markers',
                                              'Transform', 'CoordScale', 'AnchorSize', 'ClipSize')}
                    except (ValueError, AttributeError) as error:
                        errors.append(f'anchors line {number}: {error}')
        anchors['frames'] = dict(frames)
        path = settings / 'classic_minimap_profiler/reports/BL1-classic-minimap-performance-summary.txt'
        if path.exists():
            summary = path.read_text(encoding='utf-8-sig', errors='replace')
    return dict(log=str(log), latest_state=latest, snapshots=list(snapshots),
                foreign_hud_movies=sorted(foreign), warnings=warnings, events=events,
                anchors=anchors, profiler_summary=summary, parse_errors=errors)


def human(report):
    state = report['latest_state'] or {}
    lines = [f"Log: {report['log']}", f"Phase: {state.get('phase', 'no F7 snapshot')}"]
    for key in ('template.MovieInfo', 'hud.MovieInfo'):
        lines.append(f'{key}: {state.get(key)}')
    for name in report['foreign_hud_movies']:
        lines.append(f'Foreign HUD movie: {name} (another mod replaced the HUD)')
    for snap in report['snapshots']:
        state = snap['state']
        lines.append(f"F7 {snap['timestamp']} line {snap['line']}: phase={state.get('phase')} "
                     f"map={state.get('map_frame')} markers={state.get('markers')}")
        fit = state.get('zoom_fit')
        if isinstance(fit, dict):
            lines.append(f"  zoom_fit: points={fit.get('points')} raw={fit.get('raw')} "
                         f"fitted={fit.get('fitted')} final={fit.get('final')}")
    for kind in ('events', 'warnings'):
        lines.append(f'{kind.capitalize()}: {len(report[kind])}')
        lines.extend(f"  {e['timestamp']} {e['message']}" for e in report[kind])
    lines.append(f"Anchors: {report['anchors']['records']}; frames={report['anchors']['frames']}")
    if report['anchors']['latest']:
        lines.append(f"Latest anchor: {report['anchors']['latest']}")
    if report['profiler_summary']:
        lines.append(report['profiler_summary'])
    lines.extend(report['parse_errors'])
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log', nargs='?', type=Path, default=DEFAULT_LOG)
    parser.add_argument('--last', type=int, default=3, help='number of F7 snapshots (default 3)')
    parser.add_argument('--settings', type=Path, help='sdk_mods/settings, local or copied from Proton')
    parser.add_argument('--json', action='store_true', help='machine-readable report')
    args = parser.parse_args()
    if args.last < 1:
        parser.error('--last must be positive')
    settings = args.settings
    if settings is None and args.log.resolve() == DEFAULT_LOG.resolve():
        settings = GAME / 'sdk_mods/settings'
    try:
        report = diagnose(args.log, args.last, settings)
    except OSError as error:
        parser.exit(1, f'diagnostics failed: {error}\n')
    sys.stdout.reconfigure(encoding='utf-8')
    print(json.dumps(report, indent=2, ensure_ascii=False) if args.json else human(report))


if __name__ == '__main__':
    main()
